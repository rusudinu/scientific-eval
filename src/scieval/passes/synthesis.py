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


def _payload(pass_outputs: dict[str, Any], findings: list[dict]) -> str:
    """Pass JSON, with the merged findings list given separately for the table."""
    return (
        "=== MERGED FINDINGS (deduplicated across repeated runs) ===\n"
        + as_json(findings, limit=40000)
        + "\n\n=== PASS OUTPUTS ===\n"
        + as_json(pass_outputs, limit=MAX_PAYLOAD_CHARS)
    )
