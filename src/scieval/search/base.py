"""Search interfaces. Everything the model may cite has to come through here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""

    def as_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


@dataclass
class ReferenceRecord:
    """A bibliographic record retrieved for one reference entry."""

    found: bool
    url: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    venue: str = ""
    doi: str = ""
    type: str = ""
    is_retracted: bool = False
    retraction_notes: str = ""
    is_preprint: bool = False
    abstract: str = ""
    match_score: float = 0.0
    source: str = ""

    def as_dict(self) -> dict:
        return {
            "found": self.found,
            "url": self.url,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "doi": self.doi,
            "type": self.type,
            "is_retracted": self.is_retracted,
            "retraction_notes": self.retraction_notes,
            "is_preprint": self.is_preprint,
            "abstract": self.abstract[:1200],
            "match_score": self.match_score,
            "source": self.source,
        }


@runtime_checkable
class WebSearchProvider(Protocol):
    name: str
    available: bool

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        """Return search results, or an empty list when nothing is found."""


class NoWebSearch:
    """The no-tool mode required by rule 3 of the shared system prompt."""

    name = "none"
    available = False

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        return []


@runtime_checkable
class ReferenceLookup(Protocol):
    name: str
    available: bool

    def lookup(
        self, *, raw: str, doi: str | None = None, title: str | None = None, year: str | None = None
    ) -> ReferenceRecord:
        """Look up one bibliography entry."""


class NoReferenceLookup:
    name = "none"
    available = False

    def lookup(
        self, *, raw: str, doi: str | None = None, title: str | None = None, year: str | None = None
    ) -> ReferenceRecord:
        return ReferenceRecord(found=False, source="none")
