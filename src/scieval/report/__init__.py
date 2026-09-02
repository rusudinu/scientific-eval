"""Report generation: findings normalisation, run diffing, output files."""

from .diff import (
    dedupe,
    findings_from_pass1,
    findings_from_pass2,
    findings_from_pass3,
    findings_from_pass4,
    merge_runs,
    stability_summary,
)
from .writer import (
    RunPaths,
    fallback_report,
    prepare_paths,
    slugify,
    write_findings_csv,
    write_json,
    write_provenance,
    write_report,
)

__all__ = [
    "RunPaths",
    "dedupe",
    "fallback_report",
    "findings_from_pass1",
    "findings_from_pass2",
    "findings_from_pass3",
    "findings_from_pass4",
    "merge_runs",
    "prepare_paths",
    "slugify",
    "stability_summary",
    "write_findings_csv",
    "write_json",
    "write_provenance",
    "write_report",
]
