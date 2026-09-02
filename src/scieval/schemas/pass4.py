"""Pass 4 - external fact-checking, in two stages (claim extraction, then verification)."""

from __future__ import annotations

from pydantic import Field

from .common import LimitedModel, StrictModel, Verdict


class ExtractedClaim(StrictModel):
    claim_quote: str = ""
    location: str = ""
    search_query: str = ""


class Pass4ClaimsOutput(LimitedModel):
    claims: list[ExtractedClaim] = Field(default_factory=list)
    main_result_query: str = ""


class FactCheck(StrictModel):
    claim_quote: str = ""
    location: str = ""
    source_url: str = ""
    source_says: str = ""
    verdict: Verdict = Verdict.could_not_verify


class MissingEngagement(StrictModel):
    work: str = ""
    url: str = ""
    why_relevant: str = ""


class Pass4Output(LimitedModel):
    search_tool_available: bool = False
    fact_checks: list[FactCheck] = Field(default_factory=list)
    missing_engagement: list[MissingEngagement] = Field(default_factory=list)
