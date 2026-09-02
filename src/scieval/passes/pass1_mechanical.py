"""Pass 1 - mechanical quality and spelling, one call per section."""

from __future__ import annotations

from ..schemas import Pass1Output
from .base import PaperContext, PassRunner, as_json, clip, load_prompt


def run(runner: PassRunner, paper: PaperContext) -> list[Pass1Output]:
    """Run the section-level mechanical checks and return one output per section."""
    prompt = load_prompt(runner.config, "pass1_mechanical")
    inventory_digest = _inventory_digest(paper)
    outputs: list[Pass1Output] = []

    for section in paper.reviewable_sections():
        candidates = paper.candidates.get(section.label, [])
        payload = _section_payload(runner, paper, section, candidates, inventory_digest)
        output = runner.structured(
            pass_name="pass1",
            label=f"pass1:{section.label[:40]}",
            task_prompt=prompt,
            payload=payload,
            schema=Pass1Output,
        )
        if output is None:
            continue
        if not output.section:
            output.section = section.label
        outputs.append(output)
    return outputs


def _section_payload(runner, paper, section, candidates, inventory_digest: str) -> str:
    limit = runner.config.limits.pass1_section_max_chars
    section_captions = [
        c.as_dict() for c in paper.captions if section.start_page <= c.page <= section.end_page
    ]
    return (
        f"=== PASS 0 INVENTORY (condensed) ===\n{inventory_digest}\n\n"
        f"=== SECTION UNDER REVIEW ===\n"
        f"title: {section.label}\n"
        f"pages: {section.start_page}-{section.end_page}\n\n"
        f"{clip(section.text, limit)}\n\n"
        f"=== FIGURES AND TABLES ON THESE PAGES ===\n{as_json(section_captions)}\n\n"
        f"=== SPELLCHECKER CANDIDATES FOR THIS SECTION ===\n"
        f"{as_json([c.as_dict() for c in candidates])}\n"
        f"({len(candidates)} candidates; classify every one of them.)"
    )


def _inventory_digest(paper: PaperContext) -> str:
    inventory = paper.inventory
    if inventory is None:
        return as_json({"language": paper.language, "note": "Pass 0 output unavailable"})
    return as_json(
        {
            "language": inventory.language,
            "title": inventory.title,
            "sections": [s.model_dump() for s in inventory.sections],
            "figures": [f.model_dump() for f in inventory.figures],
            "tables": [t.model_dump() for t in inventory.tables],
        },
        limit=12000,
    )
