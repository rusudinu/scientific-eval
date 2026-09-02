"""Pass 4 - external fact-checking, in three stages.

The prompt set assumes the model can call a search tool mid-turn. Local models
cannot do that reliably, so the pass is split: the model extracts checkable
claims, the tool runs the searches, and the model then judges only the results
it was handed. Fabricated URLs are impossible because every URL comes from the
search layer.
"""

from __future__ import annotations

from ..extract.sections import sections_of_kind
from ..schemas import Pass4ClaimsOutput, Pass4Output
from ..schemas.common import Verdict
from ..schemas.pass4 import FactCheck
from ..search.base import SearchResult, WebSearchProvider
from .base import PaperContext, PassRunner, as_json, clip, load_prompt

MAX_SEARCHED_CLAIMS = 25


def run(runner: PassRunner, paper: PaperContext, web: WebSearchProvider) -> Pass4Output:
    claims = _extract_claims(runner, paper)
    available = bool(getattr(web, "available", False))

    if claims is None:
        output = Pass4Output(search_tool_available=available)
        output.limitations.append("Claim extraction failed; no external fact-checking was done.")
        return output

    if not available:
        return _no_tool_output(claims)

    searched, main_results = _search(web, claims, runner.config.search.max_results_per_query)
    dropped = len(claims.claims) - len(searched)
    result = runner.structured(
        pass_name="pass4",
        label="pass4:verify",
        task_prompt=load_prompt(runner.config, "pass4_facts"),
        payload=(
            "search_tool_available: true\n\n"
            "=== CLAIMS WITH SEARCH RESULTS ===\n"
            + as_json(searched, limit=60000)
            + "\n\n=== SEARCH RESULTS FOR THE PAPER'S MAIN RESEARCH QUESTION ===\n"
            + as_json(
                {"query": claims.main_result_query, "results": [r.as_dict() for r in main_results]},
                limit=20000,
            )
        ),
        schema=Pass4Output,
    )
    if result is None:
        output = _no_tool_output(claims)
        output.search_tool_available = True
        output.limitations.append(
            "The verification call failed; claims were carried through unverified."
        )
        return output

    result.search_tool_available = True
    _drop_unsupplied_urls(result, searched, main_results)
    if dropped > 0:
        result.limitations.append(
            f"{dropped} extracted claims beyond the first {MAX_SEARCHED_CLAIMS} were not "
            f"searched and remain unchecked."
        )
    return result


def _extract_claims(runner: PassRunner, paper: PaperContext) -> Pass4ClaimsOutput | None:
    sections = sections_of_kind(paper.sections, "introduction", "background")
    if not sections:
        sections = [s for s in paper.reviewable_sections()][:2]
    budget = runner.config.limits.pass1_section_max_chars
    body = "\n\n".join(
        f"=== {s.label} (pages {s.start_page}-{s.end_page}) ===\n{clip(s.text, budget)}"
        for s in sections
    )
    questions = paper.inventory.research_questions_or_hypotheses if paper.inventory else []
    payload = (
        f"=== RESEARCH QUESTIONS (from Pass 0) ===\n{as_json(questions)}\n\n=== TEXT ===\n{body}"
    )
    return runner.structured(
        pass_name="pass4",
        label="pass4:claims",
        task_prompt=load_prompt(runner.config, "pass4_claims"),
        payload=payload,
        schema=Pass4ClaimsOutput,
    )


def _search(
    web: WebSearchProvider, claims: Pass4ClaimsOutput, max_results: int
) -> tuple[list[dict], list[SearchResult]]:
    searched: list[dict] = []
    for claim in claims.claims[:MAX_SEARCHED_CLAIMS]:
        query = claim.search_query or claim.claim_quote
        results = web.search(query, max_results=max_results) if query else []
        searched.append(
            {
                "claim_quote": claim.claim_quote,
                "location": claim.location,
                "query": query,
                "results": [r.as_dict() for r in results],
            }
        )
    main_results = (
        web.search(claims.main_result_query, max_results=max_results)
        if claims.main_result_query
        else []
    )
    return searched, main_results


def _no_tool_output(claims: Pass4ClaimsOutput) -> Pass4Output:
    """Rule 3: no tool means every external check is could_not_verify."""
    output = Pass4Output(search_tool_available=False)
    output.fact_checks = [
        FactCheck(
            claim_quote=claim.claim_quote,
            location=claim.location,
            source_url="",
            source_says=f"no_search_tool - suggested query: {claim.search_query}",
            verdict=Verdict.could_not_verify,
        )
        for claim in claims.claims
    ]
    output.limitations.append(
        "No web-search tool was available (reason: no_search_tool). A human should run the "
        "suggested query for each claim above and confirm it against an authoritative source."
    )
    if claims.main_result_query:
        output.limitations.append(
            "Related-work coverage was not checked. A human should search "
            f'"{claims.main_result_query}" for work the paper does not engage with.'
        )
    return output


def _drop_unsupplied_urls(
    output: Pass4Output, searched: list[dict], main_results: list[SearchResult]
) -> None:
    """Strip any URL the model produced that was not in the supplied results."""
    allowed = {r["url"] for entry in searched for r in entry["results"] if r.get("url")}
    allowed |= {r.url for r in main_results if r.url}
    for check in output.fact_checks:
        if check.source_url and check.source_url not in allowed:
            check.source_url = ""
            check.verdict = Verdict.could_not_verify
            check.source_says = (
                f"{check.source_says} [url discarded: not in the supplied search results]"
            ).strip()
    output.missing_engagement = [
        item for item in output.missing_engagement if not item.url or item.url in allowed
    ]
