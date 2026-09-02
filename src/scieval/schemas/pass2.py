"""Pass 2 - internal consistency."""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from .common import ClaimVerdict, LimitedModel, Severity, StrictModel, Verdict


class ConsistencyCategory(str, Enum):
    numbers = "numbers"
    claims = "claims"
    alignment = "alignment"
    statistics = "statistics"
    reproducibility = "reproducibility"


class NumberCheck(StrictModel):
    quantity: str = ""
    locations: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    recomputation: str = ""
    verdict: Verdict = Verdict.could_not_verify


class ClaimCheck(StrictModel):
    claim_quote: str = ""
    location: str = ""
    supporting_evidence: str = ""
    verdict: ClaimVerdict = ClaimVerdict.supported
    explanation: str = ""


class QuestionAlignment(StrictModel):
    question: str = ""
    what_was_actually_tested: str = ""
    gap: str = ""


class ConsistencyFinding(StrictModel):
    severity: Severity = Severity.major
    category: ConsistencyCategory = ConsistencyCategory.numbers
    location: str = ""
    quote: str = ""
    description: str = ""


class Pass2Output(LimitedModel):
    number_checks: list[NumberCheck] = Field(default_factory=list)
    claim_checks: list[ClaimCheck] = Field(default_factory=list)
    research_question_alignment: list[QuestionAlignment] = Field(default_factory=list)
    findings: list[ConsistencyFinding] = Field(default_factory=list)
