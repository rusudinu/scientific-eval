"""Orchestration: extraction, the six passes, and the written output."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import Config
from .extract.bibliography import attach_citing_sentences, extract_references
from .extract.captions import extract_captions, tables_text
from .extract.pdf import extract_document
from .extract.sections import detect_sections, resplit_with_inventory
from .llm.client import LLMClient
from .llm.provenance import RunProvenance, build_provenance, now_iso
from .passes import (
    PaperContext,
    PassRunner,
    pass0_inventory,
    pass1_mechanical,
    pass2_consistency,
    pass3_references,
    pass4_facts,
    synthesis,
)
from .report import (
    dedupe,
    fallback_report,
    findings_from_pass1,
    findings_from_pass2,
    findings_from_pass3,
    findings_from_pass4,
    merge_runs,
    prepare_paths,
    stability_summary,
    write_findings_csv,
    write_json,
    write_provenance,
    write_report,
)
from .schemas import Finding
from .search import build_reference_lookup, build_web_search
from .spellcheck.backend import build_backend
from .spellcheck.filters import candidates_for_section, collect_allowlist

Emit = Callable[[str], None]
ALL_PASSES = ("pass0", "pass1", "pass2", "pass3", "pass4", "synthesis")


@dataclass
class ReviewResult:
    paper: Path
    run_dir: Path
    findings: list[Finding]
    pass_outputs: dict[str, Any]
    provenance: RunProvenance
    report: str = ""
    extraction: dict[str, Any] = field(default_factory=dict)


def build_paper_context(path: Path, config: Config, *, language: str = "en") -> PaperContext:
    """Everything deterministic: text, sections, bibliography, captions, spell candidates."""
    document = extract_document(path)
    sections = detect_sections(document)
    return _finish_context(path, document, sections, config, language)


def _finish_context(
    path: Path, document, sections, config: Config, language: str
) -> PaperContext:
    references = extract_references(sections)
    attach_citing_sentences(references, sections)
    captions = extract_captions(document, sections)
    paper = PaperContext(
        path=path,
        document=document,
        sections=sections,
        references=references,
        captions=captions,
        tables_text=tables_text(document, captions),
        language=language,
    )
    compute_candidates(paper, config, language)
    return paper


def compute_candidates(paper: PaperContext, config: Config, language: str) -> None:
    """Run the deterministic spellchecker per section, after pre-filtering."""
    backend = build_backend(config.spellcheck.backend, language)
    allowlist = collect_allowlist(paper.references, paper.document.text)
    paper.candidates = {
        section.index: candidates_for_section(
            section,
            backend,
            allowlist,
            min_length=config.spellcheck.min_token_length,
            max_candidates=config.spellcheck.max_candidates_per_section,
        )
        for section in paper.reviewable_sections()
    }


def run_review(
    paper_path: Path,
    config: Config,
    *,
    repeats: int = 1,
    only: tuple[str, ...] | None = None,
    quantization: str | None = None,
    emit: Emit | None = None,
) -> ReviewResult:
    """Run the pipeline over one paper and write every output file."""
    started = time.monotonic()
    say: Emit = emit or (lambda _msg: None)
    selected = set(only) if only else set(ALL_PASSES)

    say(f"extracting {paper_path.name}")
    paper = build_paper_context(paper_path, config)
    say(
        f"{paper.document.page_count} pages, {len(paper.sections)} sections, "
        f"{len(paper.references)} references, {len(paper.captions)} captions"
    )

    client = LLMClient(config)
    reference_lookup = build_reference_lookup(config)
    web_search = build_web_search(config)
    search_available = bool(getattr(web_search, "available", False)) or bool(
        getattr(reference_lookup, "available", False)
    )

    model = client.resolve_model(config.model_for("pass0"))
    provenance = build_provenance(
        config,
        paper=paper_path,
        model=model,
        model_info=client.native_model_info(model),
        repeats=repeats,
        search_tool_available=search_available,
        quantization_override=quantization,
    )
    runner = PassRunner(client, config, provenance, on_event=say)
    paths = prepare_paths(config.output_dir, paper_path, provenance.run_id)

    pass_outputs: dict[str, Any] = {}
    findings: list[Finding] = []

    # Pass 0 - inventory.
    if "pass0" in selected:
        inventory = pass0_inventory.run(runner, paper)
        if inventory is not None:
            paper.inventory = inventory
            paper.language = inventory.language or paper.language
            pass_outputs["pass0"] = inventory.model_dump(mode="json")
            provenance.passes_run.append("pass0")
            resplit = _resplit(paper, config, say)
            if not resplit:
                # The split did not change, but the language did: the candidates were
                # generated with the default dictionary before Pass 0 reported one.
                compute_candidates(paper, config, paper.language)
        else:
            say("pass0 produced no inventory; later passes use heuristic extraction only")

    write_json(paths.run_dir / "extraction.json", extraction_summary(paper))

    # Pass 1 - mechanical, repeated.
    if "pass1" in selected:
        runs: list[list[Finding]] = []
        outputs_per_run: list[list[dict]] = []
        for attempt in range(1, repeats + 1):
            say(f"pass1 run {attempt}/{repeats}")
            outputs = pass1_mechanical.run(runner, paper)
            runs.append(findings_from_pass1(outputs))
            outputs_per_run.append([o.model_dump(mode="json") for o in outputs])
        pass_outputs["pass1"] = outputs_per_run[0] if repeats == 1 else {
            "runs": outputs_per_run
        }
        findings.extend(merge_runs(runs))
        provenance.passes_run.append("pass1")

    # Pass 2 - internal consistency, repeated.
    if "pass2" in selected:
        runs = []
        outputs_pass2: list[dict] = []
        for attempt in range(1, repeats + 1):
            say(f"pass2 run {attempt}/{repeats}")
            output = pass2_consistency.run(runner, paper)
            runs.append(findings_from_pass2(output))
            if output is not None:
                outputs_pass2.append(output.model_dump(mode="json"))
        pass_outputs["pass2"] = (
            outputs_pass2[0] if repeats == 1 and outputs_pass2 else {"runs": outputs_pass2}
        )
        findings.extend(merge_runs(runs))
        provenance.passes_run.append("pass2")

    # Pass 3 - references.
    if "pass3" in selected:
        say(f"pass3 references ({getattr(reference_lookup, 'name', 'none')})")
        output3 = pass3_references.run(runner, paper, reference_lookup)
        pass_outputs["pass3"] = output3.model_dump(mode="json")
        findings.extend(findings_from_pass3(output3))
        provenance.passes_run.append("pass3")

    # Pass 4 - external facts.
    if "pass4" in selected:
        say(f"pass4 fact-checking ({getattr(web_search, 'name', 'none')})")
        output4 = pass4_facts.run(runner, paper, web_search)
        pass_outputs["pass4"] = output4.model_dump(mode="json")
        findings.extend(findings_from_pass4(output4))
        provenance.passes_run.append("pass4")

    findings = dedupe(findings)

    # Synthesis.
    report = ""
    if "synthesis" in selected and pass_outputs:
        say("synthesis")
        report = synthesis.run(
            runner, pass_outputs, [f.model_dump(mode="json") for f in findings]
        )
        provenance.passes_run.append("synthesis")
    if not report.strip():
        report = fallback_report(findings, provenance, pass_outputs)

    provenance.finished_at = now_iso()
    provenance.duration_s = round(time.monotonic() - started, 2)

    for name, output in pass_outputs.items():
        write_json(paths.run_dir / f"{name}.json", output)
    write_findings_csv(paths.findings_csv, findings)
    write_report(paths.report_md, report)
    write_provenance(paths, provenance)
    write_json(
        paths.run_dir / "findings.json",
        {
            "counts": _counts(findings),
            "stability": stability_summary(findings),
            "findings": [f.model_dump(mode="json") for f in findings],
        },
    )
    _write_latest_pointer(paths)

    close = getattr(reference_lookup, "close", None)
    if callable(close):
        close()

    say(f"wrote {paths.run_dir}")
    return ReviewResult(
        paper=paper_path,
        run_dir=paths.run_dir,
        findings=findings,
        pass_outputs=pass_outputs,
        provenance=provenance,
        report=report,
        extraction=extraction_summary(paper),
    )


def _resplit(paper: PaperContext, config: Config, say: Emit) -> bool:
    """Re-split the document using the section list Pass 0 reported.

    Returns True when the split was replaced (and candidates recomputed with it).
    """
    if not paper.inventory or not paper.inventory.sections:
        return False
    inventory_sections = [s.model_dump() for s in paper.inventory.sections]
    resplit = resplit_with_inventory(paper.document, inventory_sections)
    if len(resplit) < len(paper.sections):
        # The inventory anchored fewer sections than the heuristics found; keep the split
        # that covers more of the paper.
        return False
    say(f"re-split into {len(resplit)} sections using the Pass 0 inventory")
    paper.sections = resplit
    paper.references = extract_references(resplit)
    attach_citing_sentences(paper.references, resplit)
    paper.captions = extract_captions(paper.document, resplit)
    paper.tables_text = tables_text(paper.document, paper.captions)
    compute_candidates(paper, config, paper.language)
    return True


def extraction_summary(paper: PaperContext) -> dict[str, Any]:
    return {
        "paper": str(paper.path),
        "pages": paper.document.page_count,
        "pdf_metadata": paper.document.metadata,
        "language": paper.language,
        "sections": [s.as_dict() for s in paper.sections],
        "captions": [c.as_dict() for c in paper.captions],
        "references": [r.as_dict() for r in paper.references],
        "spellcheck_candidates": {
            section.label: [c.as_dict() for c in paper.candidates_for(section)]
            for section in paper.sections
            if paper.candidates_for(section)
        },
    }


def _counts(findings: list[Finding]) -> dict[str, int]:
    counts = {"critical": 0, "major": 0, "minor": 0}
    for finding in findings:
        counts[finding.severity.value] = counts.get(finding.severity.value, 0) + 1
    counts["total"] = len(findings)
    return counts


def _write_latest_pointer(paths) -> None:
    (paths.paper_dir / "latest.txt").write_text(paths.run_dir.name + "\n", encoding="utf-8")
