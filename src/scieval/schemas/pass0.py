"""Pass 0 - structural inventory."""

from __future__ import annotations

from pydantic import Field

from .common import LimitedModel, StrictModel


class InventorySection(StrictModel):
    number: str = ""
    title: str = ""
    pages: str = ""


class InventoryFigure(StrictModel):
    id: str = ""
    caption: str = ""
    referenced_in_text: bool = True


class InventoryTable(StrictModel):
    id: str = ""
    caption: str = ""
    referenced_in_text: bool = True


class KeyNumber(StrictModel):
    value: str = ""
    meaning: str = ""
    locations: list[str] = Field(default_factory=list)


class BibliographyEntry(StrictModel):
    index: int = 0
    raw: str = ""


class Pass0Output(LimitedModel):
    language: str = ""
    title: str = ""
    sections: list[InventorySection] = Field(default_factory=list)
    research_questions_or_hypotheses: list[str] = Field(default_factory=list)
    figures: list[InventoryFigure] = Field(default_factory=list)
    tables: list[InventoryTable] = Field(default_factory=list)
    key_numbers: list[KeyNumber] = Field(default_factory=list)
    bibliography: list[BibliographyEntry] = Field(default_factory=list)
