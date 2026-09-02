"""Pass 1 - mechanical quality and spelling."""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from .common import LimitedModel, StrictModel, TriageClass


class MechanicalCategory(str, Enum):
    language = "language"
    grammar = "grammar"
    terminology = "terminology"
    notation = "notation"
    figure_table = "figure_table"


class MechanicalSeverity(str, Enum):
    minor = "minor"
    major = "major"


class TriageItem(StrictModel):
    token: str = ""
    classification: TriageClass = TriageClass.domain_term
    correction: str = ""
    quote: str = ""
    location: str = ""


class MechanicalFinding(StrictModel):
    severity: MechanicalSeverity = MechanicalSeverity.minor
    category: MechanicalCategory = MechanicalCategory.language
    location: str = ""
    quote: str = ""
    description: str = ""
    correction: str = ""


class Pass1Output(LimitedModel):
    section: str = ""
    spellcheck_triage: list[TriageItem] = Field(default_factory=list)
    findings: list[MechanicalFinding] = Field(default_factory=list)
