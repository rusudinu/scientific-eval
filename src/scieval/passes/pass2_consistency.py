"""Pass 2 - internal consistency across numbers, claims, statistics and reproducibility."""

from __future__ import annotations

from ..extract.sections import sections_of_kind
from ..schemas import Pass2Output
from .base import PaperContext, PassRunner, as_json, clip, load_prompt


def run(runner: PassRunner, paper: PaperContext) -> Pass2Output | None:
    return runner.structured(
        pass_name="pass2",
        label="pass2:consistency",
        task_prompt=load_prompt(runner.config, "pass2_consistency"),
        payload=_payload(runner, paper),
        schema=Pass2Output,
    )


def _payload(runner: PassRunner, paper: PaperContext) -> str:
    budget = runner.config.limits.pass1_section_max_chars
    wanted = sections_of_kind(
        paper.sections, "abstract", "results", "discussion", "conclusion", "limitations"
    )
    if not wanted:
        # Heading detection found nothing usable; fall back to the second half of the paper,
        # where results and conclusions live.
        text = paper.document.text
        wanted_text = "=== PAPER TEXT (second half; section split unavailable) ===\n" + clip(
            text[len(text) // 2 :], budget * 2
        )
        missing_note = (
            "NOTE: the abstract/results/discussion/conclusion sections could not be identified. "
            "Record this in `limitations`."
        )
    else:
        wanted_text = "\n\n".join(
            f"=== {s.label} (pages {s.start_page}-{s.end_page}) ===\n{clip(s.text, budget)}"
            for s in wanted
        )
        missing_note = ""

    inventory = paper.inventory
    inventory_json = (
        as_json(
            {
                "title": inventory.title,
                "language": inventory.language,
                "research_questions_or_hypotheses": inventory.research_questions_or_hypotheses,
                "key_numbers": [k.model_dump() for k in inventory.key_numbers],
                "figures": [f.model_dump() for f in inventory.figures],
                "tables": [t.model_dump() for t in inventory.tables],
            },
            limit=30000,
        )
        if inventory
        else as_json({"note": "Pass 0 output unavailable"})
    )

    parts = [
        f"=== PASS 0 INVENTORY ===\n{inventory_json}",
        wanted_text,
        "=== TABLE CONTENTS (text around each table caption) ===\n"
        + clip(paper.tables_text, 20000),
    ]
    if missing_note:
        parts.insert(0, missing_note)
    return "\n\n".join(parts)
