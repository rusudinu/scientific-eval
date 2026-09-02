"""Pass 0 - inventory. Everything downstream treats its output as ground truth."""

from __future__ import annotations

from ..schemas import Pass0Output
from .base import PaperContext, PassRunner, as_json, clip, load_prompt


def run(runner: PassRunner, paper: PaperContext) -> Pass0Output | None:
    """One call over the whole paper, or a condensed view when it is too long."""
    payload = _build_payload(runner, paper)
    return runner.structured(
        pass_name="pass0",
        label="pass0:inventory",
        task_prompt=load_prompt(runner.config, "pass0_inventory"),
        payload=payload,
        schema=Pass0Output,
    )


def _build_payload(runner: PassRunner, paper: PaperContext) -> str:
    limit = runner.config.limits.pass0_max_chars
    full_text = paper.document.text
    hints = _extraction_hints(paper)

    if len(full_text) <= limit:
        return f"{hints}\n\n=== FULL PAPER TEXT ===\n{full_text}"

    # Too long: front matter + headings + captions + bibliography, as the prompt allows.
    front = full_text[:20000]
    headings = "\n".join(
        f"{s.number} {s.title} (pages {s.start_page}-{s.end_page})".strip() for s in paper.sections
    )
    captions = "\n".join(f"{c.id}: {c.caption}" for c in paper.captions)
    bibliography = "\n".join(f"[{r.index}] {r.raw}" for r in paper.references)
    tail = clip(
        f"=== FRONT MATTER ===\n{front}\n\n=== SECTION HEADINGS ===\n{headings}\n\n"
        f"=== CAPTIONS ===\n{captions}\n\n=== BIBLIOGRAPHY ===\n{bibliography}",
        limit,
    )
    note = (
        "NOTE: the paper exceeded the input budget, so you are given the front matter, "
        "the section headings, all captions and the bibliography instead of the full text. "
        "Record this in `limitations`."
    )
    return f"{note}\n\n{hints}\n\n{tail}"


def _extraction_hints(paper: PaperContext) -> str:
    """Deterministic extraction results, given to the model as a starting point."""
    return (
        "=== EXTRACTION HINTS (from the PDF, deterministic) ===\n"
        + as_json(
            {
                "pdf_metadata": paper.document.metadata,
                "page_count": paper.document.page_count,
                "detected_sections": [s.as_dict() for s in paper.sections],
                "detected_captions": [c.as_dict() for c in paper.captions],
                "detected_reference_count": len(paper.references),
                "detected_bibliography": [
                    {"index": r.index, "raw": r.raw[:400]} for r in paper.references
                ],
            },
            limit=40000,
        )
        + "\nThese hints come from layout heuristics and may be wrong or incomplete. "
        "Correct them from the text where they disagree."
    )
