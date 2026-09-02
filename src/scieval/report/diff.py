"""Normalise pass outputs into findings, and diff repeated runs for stability."""

from __future__ import annotations

from collections import defaultdict

from rapidfuzz import fuzz

from ..schemas import (
    Finding,
    Pass1Output,
    Pass2Output,
    Pass3Output,
    Pass4Output,
    Severity,
    Stability,
    sort_findings,
)
from ..schemas.common import ReferenceStatus, SupportsClaim, TriageClass, Verdict

QUOTE_MATCH_THRESHOLD = 88.0


def findings_from_pass1(outputs: list[Pass1Output]) -> list[Finding]:
    findings: list[Finding] = []
    for output in outputs:
        for item in output.findings:
            findings.append(
                Finding(
                    severity=Severity(item.severity.value),
                    category=item.category.value,
                    location=item.location or output.section,
                    quote=item.quote,
                    description=item.description,
                    correction=item.correction,
                    source_pass="pass1",
                )
            )
        for triage in output.spellcheck_triage:
            if triage.classification is TriageClass.typo:
                findings.append(
                    Finding(
                        severity=Severity.minor,
                        category="spelling",
                        location=triage.location or output.section,
                        quote=triage.quote or triage.token,
                        description=f"Misspelling: '{triage.token}'.",
                        correction=triage.correction,
                        source_pass="pass1",
                    )
                )
            elif triage.classification is TriageClass.inconsistent:
                findings.append(
                    Finding(
                        severity=Severity.minor,
                        category="language",
                        location=triage.location or output.section,
                        quote=triage.quote or triage.token,
                        description=f"Inconsistent spelling of '{triage.token}' across the paper.",
                        correction=triage.correction,
                        source_pass="pass1",
                    )
                )
    return findings


def findings_from_pass2(output: Pass2Output | None) -> list[Finding]:
    if output is None:
        return []
    return [
        Finding(
            severity=Severity(item.severity.value),
            category=item.category.value,
            location=item.location,
            quote=item.quote,
            description=item.description,
            source_pass="pass2",
        )
        for item in output.findings
    ]


def findings_from_pass3(output: Pass3Output | None) -> list[Finding]:
    """Reference problems become findings deterministically, from the status field."""
    if output is None:
        return []
    findings: list[Finding] = []
    for check in output.references:
        severity, description = _reference_severity(check)
        if severity is None:
            continue
        findings.append(
            Finding(
                severity=severity,
                category="reference",
                location=_first_location(check),
                quote=check.raw[:300],
                description=description,
                source_pass="pass3",
                verdict=check.status.value,
                url=check.found_at,
            )
        )
    for missing in output.missing_citations:
        findings.append(
            Finding(
                severity=Severity.major,
                category="citation",
                location=missing.location,
                quote=missing.quote,
                description=f"Claim needs a citation and has none. {missing.why_needed}".strip(),
                source_pass="pass3",
            )
        )
    return findings


def _reference_severity(check) -> tuple[Severity | None, str]:
    detail = check.mismatch_details or check.notes
    if check.status is ReferenceStatus.retracted:
        return Severity.critical, f"Reference [{check.index}] is retracted. {detail}".strip()
    if check.status is ReferenceStatus.not_found:
        return (
            Severity.major,
            f"Reference [{check.index}] could not be found in a bibliographic database. {detail}".strip(),
        )
    if check.status is ReferenceStatus.metadata_mismatch:
        return (
            Severity.major,
            f"Reference [{check.index}] metadata does not match the published record. {detail}".strip(),
        )
    if check.supports_claim in {SupportsClaim.different, SupportsClaim.unrelated}:
        return (
            Severity.major,
            f"Reference [{check.index}] does not support the claim it is cited for "
            f"({check.supports_claim.value}). {detail}".strip(),
        )
    if check.supports_claim is SupportsClaim.weaker:
        return (
            Severity.minor,
            f"Reference [{check.index}] supports a weaker claim than the one it is cited for. "
            f"{detail}".strip(),
        )
    return None, ""


def _first_location(check) -> str:
    if check.citing_sentences:
        return check.citing_sentences[0].location
    return f"Reference [{check.index}]"


def findings_from_pass4(output: Pass4Output | None) -> list[Finding]:
    if output is None:
        return []
    findings: list[Finding] = []
    for check in output.fact_checks:
        if check.verdict is not Verdict.verified_incorrect:
            continue
        findings.append(
            Finding(
                severity=Severity.major,
                category="external_fact",
                location=check.location,
                quote=check.claim_quote,
                description=f"Contradicted by an external source: {check.source_says}",
                source_pass="pass4",
                verdict=check.verdict.value,
                url=check.source_url,
            )
        )
    for item in output.missing_engagement:
        findings.append(
            Finding(
                severity=Severity.minor,
                category="missing_engagement",
                location="",
                quote=item.work,
                description=f"Relevant work the paper does not engage with. {item.why_relevant}".strip(),
                source_pass="pass4",
                url=item.url,
            )
        )
    return findings


def merge_runs(runs: list[list[Finding]]) -> list[Finding]:
    """Merge repeated runs of the same pass, tagging findings stable or unstable.

    A finding present in every run is `stable`. One that appears in some runs only
    is `unstable`, which the prompt set calls a candidate for rubric ambiguity
    rather than a certain issue.
    """
    if not runs:
        return []
    if len(runs) == 1:
        return [f.model_copy(update={"stability": Stability.single_run}) for f in runs[0]]

    merged: list[Finding] = []
    runs_containing: list[set[int]] = []
    for run_number, run in enumerate(runs):
        for finding in run:
            index = _match_index(merged, finding)
            if index is None:
                merged.append(finding.model_copy())
                runs_containing.append({run_number})
            else:
                # Count runs, not occurrences: a finding reported twice in one run
                # is not evidence that it is stable across runs.
                runs_containing[index].add(run_number)

    total = len(runs)
    for finding, seen_in in zip(merged, runs_containing):
        finding.stability = Stability.stable if len(seen_in) >= total else Stability.unstable
    return merged


def dedupe(findings: list[Finding]) -> list[Finding]:
    """Collapse findings reporting the same issue, keeping the highest severity."""
    kept: list[Finding] = []
    for finding in sort_findings(findings):
        if _match_index(kept, finding) is None:
            kept.append(finding)
    return sort_findings(kept)


def _match_index(pool: list[Finding], finding: Finding) -> int | None:
    key = finding.dedupe_key()
    for i, existing in enumerate(pool):
        if existing.source_pass != finding.source_pass:
            continue
        other = existing.dedupe_key()
        if other == key:
            return i
        if other[0] != key[0]:
            continue
        if not key[2] or not other[2]:
            continue
        if fuzz.ratio(other[2], key[2]) >= QUOTE_MATCH_THRESHOLD:
            return i
    return None


def stability_summary(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for finding in findings:
        counts[finding.stability.value] += 1
    return dict(counts)
