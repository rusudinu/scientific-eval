"""Synthesis pass - the final report, built only from the earlier pass outputs."""

from __future__ import annotations

from typing import Any

from .base import PassRunner, as_json, load_prompt

MAX_PAYLOAD_CHARS = 90000


def run(runner: PassRunner, pass_outputs: dict[str, Any], findings: list[dict]) -> str:
    payload = _payload(pass_outputs, findings)
    return runner.markdown(
        pass_name="synthesis",
        label="synthesis",
        task_prompt=load_prompt(runner.config, "synthesis"),
        payload=payload,
    )


ICONS = {
    "verified": "verified",
    "metadata_mismatch": "metadata mismatch",
    "not_found": "not found",
    "retracted": "RETRACTED",
    "could_not_verify": "could not verify",
}


def _payload(pass_outputs: dict[str, Any], findings: list[dict]) -> str:
    """Pass JSON, with the merged findings list given separately for the table."""
    return (
        "=== MERGED FINDINGS (deduplicated across repeated runs) ===\n"
        + as_json(findings, limit=40000)
        + "\n\n=== REFERENCE AUDIT (already resolved; reproduce these lines verbatim "
        "in section 3, do not re-judge any status) ===\n"
        + reference_audit(pass_outputs)
        + "\n\n=== PASS OUTPUTS ===\n"
        + as_json(pass_outputs, limit=MAX_PAYLOAD_CHARS)
    )


def reference_audit(pass_outputs: dict[str, Any]) -> str:
    """One line per bibliography entry, built from Pass 3 rather than re-judged.

    The status of a reference is a fact the lookup settled. Letting the synthesis
    model restate it from the raw JSON invites it to promote an unverified entry
    to verified.
    """
    pass3 = pass_outputs.get("pass3")
    entries = pass3.get("references", []) if isinstance(pass3, dict) else []
    if not entries:
        return "- No bibliography entries were checked."

    lines = []
    for entry in sorted(entries, key=lambda e: e.get("index", 0)):
        status = ICONS.get(entry.get("status", ""), "unknown")
        detail = entry.get("mismatch_details") or entry.get("notes") or ""
        url = entry.get("found_at") or ""
        line = f"- [{entry.get('index')}] {status}: {entry.get('raw', '')[:160]}"
        if url:
            line += f" ({url})"
        if detail and entry.get("status") != "verified":
            line += f" - {detail[:200]}"
        lines.append(line)
    return "\n".join(lines)
