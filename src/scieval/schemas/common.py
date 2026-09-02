"""Shared enums and the normalised Finding record used across passes and reports."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base for every pass schema: unknown keys are an error, not silent data loss."""

    model_config = ConfigDict(extra="forbid")


class Severity(str, Enum):
    critical = "critical"
    major = "major"
    minor = "minor"


class Verdict(str, Enum):
    verified_correct = "verified_correct"
    verified_incorrect = "verified_incorrect"
    could_not_verify = "could_not_verify"


class ClaimVerdict(str, Enum):
    supported = "supported"
    overreach = "overreach"
    unsupported = "unsupported"


class ReferenceStatus(str, Enum):
    verified = "verified"
    metadata_mismatch = "metadata_mismatch"
    not_found = "not_found"
    retracted = "retracted"
    could_not_verify = "could_not_verify"


class SupportsClaim(str, Enum):
    yes = "yes"
    weaker = "weaker"
    different = "different"
    unrelated = "unrelated"
    could_not_check = "could_not_check"


class TriageClass(str, Enum):
    typo = "typo"
    domain_term = "domain_term"
    inconsistent = "inconsistent"


class Stability(str, Enum):
    stable = "stable"
    unstable = "unstable"
    single_run = "single_run"


class Finding(StrictModel):
    """One reported problem, normalised across every pass for the CSV and the report."""

    severity: Severity
    category: str
    location: str = ""
    quote: str = ""
    description: str = ""
    correction: str = ""
    source_pass: str = ""
    verdict: str = ""
    url: str = ""
    stability: Stability = Stability.single_run

    def dedupe_key(self) -> tuple[str, str, str]:
        return (
            self.category.strip().lower(),
            self.location.strip().lower(),
            " ".join(self.quote.split()).lower()[:120],
        )


SEVERITY_ORDER = {Severity.critical: 0, Severity.major: 1, Severity.minor: 2}


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(
        findings,
        key=lambda f: (SEVERITY_ORDER.get(f.severity, 3), f.source_pass, f.category, f.location),
    )


class LimitedModel(StrictModel):
    """Every pass output carries the limitations list required by system rule 7."""

    limitations: list[str] = Field(default_factory=list)
