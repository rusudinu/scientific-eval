"""Command line interface."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .calibrate import GroundTruthError, TEMPLATE, render_markdown, run_calibration, write_csv
from .config import Config, ConfigError, load_config
from .extract.pdf import NoTextError
from .llm.client import LLMClient, LLMError
from .pipeline import ALL_PASSES, build_paper_context, run_review
from .report import write_json

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Multi-pass correctness review of scientific papers against a local or hosted LLM.",
)
console = Console()
error_console = Console(stderr=True)

ProviderOpt = Annotated[Optional[str], typer.Option("--provider", "-p", help="Provider profile from scieval.toml (lmstudio, openrouter, ...).")]
ModelOpt = Annotated[Optional[str], typer.Option("--model", "-m", help="Model id for every pass. Defaults to the server's first model.")]
ConfigOpt = Annotated[Optional[Path], typer.Option("--config", "-c", help="Path to scieval.toml.")]
SeedOpt = Annotated[Optional[int], typer.Option("--seed", help="Sampling seed sent with every call.")]
TempOpt = Annotated[Optional[float], typer.Option("--temperature", help="Sampling temperature. Keep at or near 0.")]
OutOpt = Annotated[Optional[Path], typer.Option("--out", "-o", help="Output directory (default: out/).")]


def _load_dotenv() -> None:
    """Read .env from the working directory without overriding real environment values."""
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent.parent / ".env"):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return


def _config(
    config_path: Path | None,
    provider: str | None = None,
    model: str | None = None,
    model_pass: list[str] | None = None,
    seed: int | None = None,
    temperature: float | None = None,
    output_dir: Path | None = None,
    web_provider: str | None = None,
) -> Config:
    _load_dotenv()
    overrides: dict[str, str] = {}
    for item in model_pass or []:
        if "=" not in item:
            raise typer.BadParameter(f"--model-pass expects pass=model, got '{item}'")
        name, value = item.split("=", 1)
        if name not in ALL_PASSES:
            raise typer.BadParameter(f"unknown pass '{name}'; expected one of {', '.join(ALL_PASSES)}")
        overrides[name] = value
    try:
        return load_config(
            config_path, provider=provider, model=model, model_overrides=overrides,
            seed=seed, temperature=temperature, output_dir=output_dir, web_provider=web_provider,
        )
    except ConfigError as exc:
        error_console.print(f"[red]configuration error:[/red] {exc}")
        raise typer.Exit(2) from exc


def _fail(message: str, code: int = 1) -> None:
    error_console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Print the version and exit.")] = False,
) -> None:
    if version:
        console.print(f"scientific-eval {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command()
def review(
    paper: Annotated[Path, typer.Argument(help="PDF to review.", exists=True, dir_okay=False)],
    provider: ProviderOpt = None,
    model: ModelOpt = None,
    model_pass: Annotated[Optional[list[str]], typer.Option("--model-pass", help="Per-pass model, e.g. --model-pass pass2=qwen2.5-32b. Repeatable.")] = None,
    config_path: ConfigOpt = None,
    repeats: Annotated[int, typer.Option("--repeats", "-r", min=1, max=5, help="Runs of passes 1 and 2; findings seen in every run are marked stable.")] = 1,
    only: Annotated[Optional[str], typer.Option("--only", help="Comma-separated passes to run, e.g. pass0,pass1.")] = None,
    seed: SeedOpt = None,
    temperature: TempOpt = None,
    out: OutOpt = None,
    web_search: Annotated[Optional[str], typer.Option("--web-search", help="Web search provider for Pass 4: none, tavily, brave, searxng.")] = None,
    quantization: Annotated[Optional[str], typer.Option("--quantization", help="Record this quantization in the run log when the server does not report one.")] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Only print the output directory.")] = False,
) -> None:
    """Review one paper and write JSON, CSV and a Markdown report."""
    config = _config(config_path, provider, model, model_pass, seed, temperature, out, web_search)
    selected = _parse_only(only)
    emit = (lambda _m: None) if quiet else (lambda m: console.print(f"[dim]{m}[/dim]"))

    try:
        result = run_review(
            paper, config, repeats=repeats, only=selected, quantization=quantization, emit=emit
        )
    except NoTextError as exc:
        _fail(str(exc), 2)
    except LLMError as exc:
        _fail(f"{exc}\nIs the server running at {config.provider.base_url}?")
    except ConfigError as exc:
        _fail(str(exc), 2)
    except Exception as exc:  # pragma: no cover - surfaced to the user, not swallowed
        _fail(f"{type(exc).__name__}: {exc}")

    if quiet:
        console.print(str(result.run_dir))
        return

    _print_summary(result)


def _parse_only(only: str | None) -> tuple[str, ...] | None:
    if not only:
        return None
    names = tuple(n.strip() for n in only.split(",") if n.strip())
    unknown = [n for n in names if n not in ALL_PASSES]
    if unknown:
        raise typer.BadParameter(
            f"unknown pass(es): {', '.join(unknown)}; expected {', '.join(ALL_PASSES)}"
        )
    return names


def _print_summary(result) -> None:
    counts = {"critical": 0, "major": 0, "minor": 0}
    for finding in result.findings:
        counts[finding.severity.value] += 1

    table = Table(title=f"{result.paper.name} - {len(result.findings)} findings", show_lines=False)
    table.add_column("Severity")
    table.add_column("Location")
    table.add_column("Description")
    for finding in result.findings[:20]:
        severity = finding.severity.value
        if finding.stability.value == "unstable":
            severity += " (unstable)"
        colour = {"critical": "red", "major": "yellow", "minor": "dim"}[finding.severity.value]
        table.add_row(
            f"[{colour}]{severity}[/{colour}]",
            (finding.location or "-")[:40],
            " ".join(finding.description.split())[:90],
        )
    if result.findings:
        console.print(table)
        if len(result.findings) > 20:
            console.print(f"[dim]...and {len(result.findings) - 20} more in findings.csv[/dim]")
    else:
        console.print("[green]No findings reported.[/green]")

    provenance = result.provenance
    console.print(
        f"critical {counts['critical']}  major {counts['major']}  minor {counts['minor']}  |  "
        f"model {provenance.model} ({provenance.quantization})  |  "
        f"prompts v{provenance.prompt_version}  seed {provenance.seed}  |  "
        f"{provenance.duration_s}s"
    )
    if provenance.errors:
        console.print(f"[yellow]{len(provenance.errors)} call error(s); see run.json[/yellow]")
    console.print(f"output: {result.run_dir}")


@app.command()
def calibrate(
    folder: Annotated[Path, typer.Argument(help="Folder of X.pdf + X.review.json pairs.", exists=True, file_okay=False)],
    provider: ProviderOpt = None,
    model: ModelOpt = None,
    config_path: ConfigOpt = None,
    repeats: Annotated[int, typer.Option("--repeats", "-r", min=1, max=5)] = 1,
    threshold: Annotated[float, typer.Option("--threshold", min=0.0, max=100.0, help="Similarity needed to call two findings the same issue.")] = 70.0,
    reuse: Annotated[bool, typer.Option("--reuse", help="Reuse the latest stored run per paper instead of calling the model.")] = False,
    seed: SeedOpt = None,
    temperature: TempOpt = None,
    out: OutOpt = None,
    report_dir: Annotated[Optional[Path], typer.Option("--report-dir", help="Where to write calibration.{md,csv,json} (default: the paper folder).")] = None,
) -> None:
    """Score the pipeline against human reviews and report agreement."""
    config = _config(config_path, provider, model, None, seed, temperature, out)
    try:
        report = run_calibration(
            folder, config, repeats=repeats, threshold=threshold, reuse=reuse,
            emit=lambda m: console.print(f"[dim]{m}[/dim]"),
        )
    except GroundTruthError as exc:
        _fail(str(exc), 2)
    except LLMError as exc:
        _fail(f"{exc}\nIs the server running at {config.provider.base_url}?")

    destination = report_dir or folder
    destination.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(report)
    (destination / "calibration.md").write_text(markdown, encoding="utf-8")
    write_csv(destination / "calibration.csv", report)
    write_json(destination / "calibration.json", report.as_dict())

    table = Table(title="Agreement with human reviews")
    table.add_column("Paper")
    table.add_column("Matched", justify="right")
    table.add_column("Missed", justify="right")
    table.add_column("Spurious", justify="right")
    table.add_column("P", justify="right")
    table.add_column("R", justify="right")
    table.add_column("F1", justify="right")
    for paper in report.papers:
        row = paper.row()
        table.add_row(
            row["paper"], str(row["matched"]), str(row["missed"]), str(row["spurious"]),
            f"{row['precision']:.2f}", f"{row['recall']:.2f}", f"{row['f1']:.2f}",
        )
    console.print(table)
    console.print(
        f"overall precision {report.overall.precision:.3f}  recall {report.overall.recall:.3f}  "
        f"F1 {report.overall.f1:.3f}  severity agreement {report.severity_agreement:.3f}"
    )
    console.print(f"output: {destination / 'calibration.md'}")


@app.command()
def models(
    provider: ProviderOpt = None,
    config_path: ConfigOpt = None,
    detail: Annotated[bool, typer.Option("--detail", help="Query the provider for quantization (slower).")] = True,
) -> None:
    """List the models the configured endpoint reports."""
    config = _config(config_path, provider)
    try:
        client = LLMClient(config)
        listed = client.list_models()
    except (LLMError, ConfigError) as exc:
        _fail(str(exc))

    if not listed:
        console.print(f"[yellow]{config.provider.base_url} reports no models.[/yellow]")
        return

    table = Table(title=f"{config.provider_name} - {config.provider.base_url}")
    table.add_column("id")
    table.add_column("quantization")
    table.add_column("context")
    for entry in listed:
        model_id = str(entry.get("id", ""))
        info = client.native_model_info(model_id) if detail else {}
        table.add_row(
            model_id,
            str(info.get("quantization") or "-"),
            str(info.get("context_length") or entry.get("context_length") or "-"),
        )
    console.print(table)


@app.command()
def extract(
    paper: Annotated[Path, typer.Argument(help="PDF to inspect.", exists=True, dir_okay=False)],
    config_path: ConfigOpt = None,
    json_out: Annotated[Optional[Path], typer.Option("--json", help="Write the full extraction to this file.")] = None,
    show: Annotated[str, typer.Option("--show", help="sections | references | candidates | captions | text")] = "sections",
) -> None:
    """Run extraction only. No model calls, so this works with the server offline."""
    config = _config(config_path)
    try:
        paper_context = build_paper_context(paper, config)
    except NoTextError as exc:
        _fail(str(exc), 2)

    if json_out:
        from .pipeline import extraction_summary

        write_json(json_out, extraction_summary(paper_context))
        console.print(f"wrote {json_out}")

    if show == "sections":
        table = Table(title=f"{paper.name} - {len(paper_context.sections)} sections")
        table.add_column("#")
        table.add_column("Title")
        table.add_column("Kind")
        table.add_column("Pages")
        table.add_column("Chars", justify="right")
        table.add_column("Candidates", justify="right")
        for section in paper_context.sections:
            table.add_row(
                section.number or "-",
                section.title[:50],
                section.kind,
                f"{section.start_page}-{section.end_page}",
                str(len(section.text)),
                str(len(paper_context.candidates.get(section.label, []))),
            )
        console.print(table)
    elif show == "references":
        for ref in paper_context.references:
            console.print(f"[bold][{ref.index}][/bold] {ref.raw[:160]}")
            console.print(
                f"     doi={ref.doi or '-'} year={ref.year or '-'} "
                f"cited in {len(ref.citing_sentences)} sentence(s)"
            )
        console.print(f"{len(paper_context.references)} references")
    elif show == "captions":
        for caption in paper_context.captions:
            mark = "referenced" if caption.referenced_in_text else "NOT referenced"
            console.print(f"[bold]{caption.id}[/bold] (p.{caption.page}, {mark}) {caption.caption[:120]}")
    elif show == "candidates":
        for label, candidates in paper_context.candidates.items():
            if not candidates:
                continue
            console.print(f"[bold]{label}[/bold]: {len(candidates)}")
            console.print("  " + ", ".join(c.token for c in candidates[:40]))
    elif show == "text":
        sys.stdout.write(paper_context.document.text)
    else:
        raise typer.BadParameter("--show must be sections, references, candidates, captions or text")


@app.command("config-show")
def config_show(
    provider: ProviderOpt = None,
    config_path: ConfigOpt = None,
) -> None:
    """Print the effective configuration."""
    config = _config(config_path, provider)
    console.print_json(
        json.dumps(
            {
                "config_file": str(config.source_path) if config.source_path else None,
                "provider": config.provider_name,
                "base_url": config.provider.base_url,
                "models": config.models or {"default": "(first model the server reports)"},
                "seed": config.seed,
                "temperature": config.temperature,
                "request_timeout_s": config.request_timeout_s,
                "output_dir": str(config.output_dir),
                "prompts_dir": str(config.prompts_dir),
                "spellcheck": vars(config.spellcheck),
                "search": vars(config.search),
                "limits": vars(config.limits),
            }
        )
    )


@app.command("init-review")
def init_review(
    paper: Annotated[Path, typer.Argument(help="PDF the review file belongs to.")],
) -> None:
    """Write a ground-truth template next to a paper, for calibration."""
    destination = paper.with_suffix("").with_name(paper.stem + ".review.json")
    if destination.exists():
        _fail(f"{destination} already exists")
    template = dict(TEMPLATE, paper=paper.name)
    destination.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    console.print(f"wrote {destination}")


if __name__ == "__main__":  # pragma: no cover
    app()
