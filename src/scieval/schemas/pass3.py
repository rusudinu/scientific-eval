"""Pass 3 - reference verification."""

from __future__ import annotations

from pydantic import Field

from .common import LimitedModel, ReferenceStatus, StrictModel, SupportsClaim


class CitingSentence(StrictModel):
    quote: str = ""
    location: str = ""


class ReferenceCheck(StrictModel):
    index: int = 0
    raw: str = ""
    status: ReferenceStatus = ReferenceStatus.could_not_verify
    found_at: str = ""
    mismatch_details: str = ""
    citing_sentences: list[CitingSentence] = Field(default_factory=list)
    supports_claim: SupportsClaim = SupportsClaim.could_not_check
    notes: str = ""


class MissingCitation(StrictModel):
    quote: str = ""
    location: str = ""
    why_needed: str = ""


class Pass3Output(LimitedModel):
    search_tool_available: bool = False
    references: list[ReferenceCheck] = Field(default_factory=list)
    missing_citations: list[MissingCitation] = Field(default_factory=list)
