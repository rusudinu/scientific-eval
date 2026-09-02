"""Search providers: deterministic reference lookup and optional web search."""

from __future__ import annotations

from ..config import Config
from .base import (
    NoReferenceLookup,
    NoWebSearch,
    ReferenceLookup,
    ReferenceRecord,
    SearchResult,
    WebSearchProvider,
)
from .crossref import CrossrefLookup
from .web import BraveSearch, SearxngSearch, TavilySearch

__all__ = [
    "BraveSearch",
    "CrossrefLookup",
    "NoReferenceLookup",
    "NoWebSearch",
    "ReferenceLookup",
    "ReferenceRecord",
    "SearchResult",
    "SearxngSearch",
    "TavilySearch",
    "WebSearchProvider",
    "build_reference_lookup",
    "build_web_search",
]


def build_reference_lookup(config: Config) -> ReferenceLookup:
    if config.search.reference_provider == "crossref":
        return CrossrefLookup()
    return NoReferenceLookup()


def build_web_search(config: Config) -> WebSearchProvider:
    """Return the configured provider, or the no-tool stub when it is unusable."""
    name = (config.search.web_provider or "none").lower()
    provider: WebSearchProvider
    if name == "tavily":
        provider = TavilySearch()
    elif name == "brave":
        provider = BraveSearch()
    elif name == "searxng":
        provider = SearxngSearch(config.search.searxng_url)
    else:
        return NoWebSearch()
    # A configured provider missing its key must degrade, not pretend.
    return provider if provider.available else NoWebSearch()
