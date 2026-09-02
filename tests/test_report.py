"""Findings normalisation, run diffing, and the written outputs."""

from __future__ import annotations

import csv

from scieval.llm.provenance import RunProvenance
from scieval.report import (
    dedupe,
    fallback_report,
    findings_from_pass1,
    findings_from_pass3,
    findings_from_pass4,
    merge_runs,
    slugify,
    stability_summary,
    write_findings_csv,
)
from scieval.schemas import Finding, Pass1Output, Pass3Output, Pass4Output, Severity, Stability


def _finding(quote: str, category: str = "numbers", severity=Severity.major, **kwargs) -> Finding:
    return Finding(severity=severity, category=category, quote=quote, source_pass="pass2", **kwargs)


def test_pass1_typos_and_findings_become_findings():
    output = Pass1Output.model_validate(
        {
            "section": "1 Introduction",
            "spellcheck_triage": [
                {"token": "allready", "classification": "typo", "correction": "already",
                 "quote": "was allready shown", "location": "1 Introduction"},
                {"token": "resizes", "classification": "domain_term", "correction": "",
                 "quote": "", "location": ""},
                {"token": "optimise", "classification": "inconsistent", "correction": "optimize",
                 "quote": "we optimise", "location": "2 Related Work"},
            ],
            "findings": [
                {"severity": "minor", "category": "grammar", "location": "1 Introduction",
                 "quote": "the results is clear", "description": "Subject-verb disagreement.",
                 "correction": "the results are clear"}
            ],
            "limitations": [],
        }
    )
    findings = findings_from_pass1([output])
    categories = {f.category for f in findings}
    assert categories == {"grammar", "spelling", "language"}
    # A domain term is not an error and must not become a finding.
    assert not any("resizes" in f.description for f in findings)
    typo = next(f for f in findings if f.category == "spelling")
    assert typo.correction == "already"
    assert typo.severity is Severity.minor


def test_retracted_reference_is_critical():
    output = Pass3Output.model_validate(
        {
            "search_tool_available": True,
            "references": [
                {"index": 1, "raw": "Some paper", "status": "retracted", "found_at": "http://x",
                 "mismatch_details": "", "citing_sentences": [], "supports_claim": "yes",
                 "notes": "Retraction notice: withdrawn"},
                {"index": 2, "raw": "Other paper", "status": "verified", "found_at": "http://y",
                 "mismatch_details": "", "citing_sentences": [], "supports_claim": "yes",
                 "notes": ""},
            ],
            "missing_citations": [
                {"quote": "40% of memory", "location": "1 Introduction", "why_needed": "A statistic."}
            ],
            "limitations": [],
        }
    )
    findings = findings_from_pass3(output)
    severities = {f.category: f.severity for f in findings}
    assert severities["reference"] is Severity.critical
    assert severities["citation"] is Severity.major
    # A verified reference produces no finding.
    assert len([f for f in findings if f.category == "reference"]) == 1


def test_reference_supporting_a_weaker_claim_is_minor():
    output = Pass3Output.model_validate(
        {
            "search_tool_available": True,
            "references": [
                {"index": 1, "raw": "Paper", "status": "verified", "found_at": "http://x",
                 "mismatch_details": "", "citing_sentences": [], "supports_claim": "weaker",
                 "notes": ""}
            ],
            "missing_citations": [], "limitations": [],
        }
    )
    assert findings_from_pass3(output)[0].severity is Severity.minor


def test_pass4_only_reports_contradicted_claims():
    output = Pass4Output.model_validate(
        {
            "search_tool_available": True,
            "fact_checks": [
                {"claim_quote": "released in 1979", "location": "1 Introduction",
                 "source_url": "http://src", "source_says": "It was 1989.",
                 "verdict": "verified_incorrect"},
                {"claim_quote": "cache misses dominate", "location": "1 Introduction",
                 "source_url": "http://ok", "source_says": "agrees", "verdict": "verified_correct"},
                {"claim_quote": "unknown", "location": "1", "source_url": "",
                 "source_says": "", "verdict": "could_not_verify"},
            ],
            "missing_engagement": [], "limitations": [],
        }
    )
    findings = findings_from_pass4(output)
    assert len(findings) == 1
    assert findings[0].url == "http://src"


def test_merge_runs_marks_stability():
    run_a = [_finding("value A"), _finding("value B")]
    run_b = [_finding("value A")]
    merged = merge_runs([run_a, run_b])
    by_quote = {f.quote: f.stability for f in merged}
    assert by_quote["value A"] is Stability.stable
    assert by_quote["value B"] is Stability.unstable
    assert stability_summary(merged) == {"stable": 1, "unstable": 1}


def test_a_finding_repeated_inside_one_run_is_not_stable():
    """Two occurrences in one run are not evidence of agreement between runs."""
    run_a = [_finding("value A"), _finding("value A")]
    run_b = [_finding("something else entirely")]
    merged = merge_runs([run_a, run_b])
    by_quote = {f.quote: f.stability for f in merged}
    assert by_quote["value A"] is Stability.unstable
    assert by_quote["something else entirely"] is Stability.unstable


def test_single_run_is_labelled_single_run():
    merged = merge_runs([[_finding("only")]])
    assert merged[0].stability is Stability.single_run


def test_merge_runs_matches_near_identical_quotes():
    run_a = [_finding("the mean latency was 5.90 ms in all runs")]
    run_b = [_finding("the mean latency was 5.90 ms in all runs.")]
    merged = merge_runs([run_a, run_b])
    assert len(merged) == 1
    assert merged[0].stability is Stability.stable


def test_dedupe_keeps_the_highest_severity_duplicate():
    findings = [
        _finding("same quote here", severity=Severity.minor),
        _finding("same quote here", severity=Severity.critical),
    ]
    deduped = dedupe(findings)
    assert len(deduped) == 1
    assert deduped[0].severity is Severity.critical


def test_findings_from_different_passes_are_not_merged():
    a = Finding(severity=Severity.major, category="numbers", quote="x", source_pass="pass1")
    b = Finding(severity=Severity.major, category="numbers", quote="x", source_pass="pass2")
    assert len(dedupe([a, b])) == 2


def test_csv_has_the_expected_columns(tmp_path):
    path = tmp_path / "findings.csv"
    write_findings_csv(path, [_finding("a quote", location="4 Results")])
    rows = list(csv.DictReader(path.open()))
    assert rows[0]["severity"] == "major"
    assert rows[0]["location"] == "4 Results"
    assert rows[0]["pass"] == "pass2"
    assert set(rows[0]) == {
        "pass", "severity", "category", "location", "quote", "description",
        "correction", "verdict", "url", "stability",
    }


def test_fallback_report_covers_all_six_sections():
    provenance = RunProvenance(
        run_id="r", paper="p.pdf", paper_sha256="abc", provider="lmstudio",
        base_url="http://x", model="m", quantization="Q4_K_M", model_info={},
        prompt_version="1.0.0", prompt_hashes={}, seed=42, temperature=0.0, repeats=1,
        reference_provider="crossref", web_search_provider="none", search_tool_available=True,
        started_at="now", passes_run=["pass0", "pass1"],
    )
    report = fallback_report(
        [_finding("a quote", severity=Severity.critical, description="Numbers disagree.")],
        provenance,
        {"pass0": {"language": "en-GB", "limitations": ["truncated input"]},
         "pass3": {"references": [{"index": 1, "status": "not_found", "raw": "X"}]}},
    )
    for heading in ("## 1. Verdict", "## 2. Findings", "## 3. Reference audit",
                    "## 4. Spelling and language", "## 5. Unverifiable items",
                    "## 6. Pass coverage"):
        assert heading in report
    assert "Numbers disagree." in report
    assert "Q4_K_M" in report
    assert "truncated input" in report


def test_slugify_makes_a_safe_directory_name():
    assert slugify("A Paper: Draft (v2).pdf") == "A-Paper-Draft-v2-.pdf"
    assert slugify("...") == "paper"


def test_same_quote_in_two_sections_is_two_findings():
    """Pass 1 quotes a bare token, so location has to separate the occurrences."""
    a = _finding("teh", category="spelling", location="1 Introduction (p. 1)")
    b = _finding("teh", category="spelling", location="4 Results (p. 6)")
    assert len(dedupe([a, b])) == 2
    merged = merge_runs([[a], [b]])
    assert len(merged) == 2
    assert all(f.stability is Stability.unstable for f in merged)


def test_fallback_report_reads_repeated_run_outputs():
    """With --repeats the pass outputs are stored as {"runs": [...]}."""
    provenance = RunProvenance(
        run_id="r", paper="p.pdf", paper_sha256="abc", provider="lmstudio", base_url="http://x",
        model="m", quantization="Q4", model_info={}, prompt_version="1.0.0", prompt_hashes={},
        seed=42, temperature=0.0, repeats=2, reference_provider="crossref",
        web_search_provider="none", search_tool_available=True, started_at="now",
    )
    report = fallback_report(
        [],
        provenance,
        {
            "pass0": {"language": "en-GB", "limitations": []},
            "pass1": {"runs": [[{"section": "1", "limitations": ["pass1 could not read table"]}]]},
            "pass2": {"runs": [{
                "limitations": ["pass2 limitation text"],
                "number_checks": [{"quantity": "sample size", "verdict": "could_not_verify"}],
            }]},
        },
    )
    assert "pass1 could not read table" in report
    assert "pass2 limitation text" in report
    assert "sample size" in report
    assert "en-GB" in report
