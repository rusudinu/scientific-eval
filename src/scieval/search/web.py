"""Web search providers for Pass 4. Each is optional and off unless configured."""

from __future__ import annotations

import os

import httpx

from .base import SearchResult


class TavilySearch:
    name = "tavily"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        self._api_key = api_key or os.environ.get("TAVILY_API_KEY", "")
        self._client = httpx.Client(timeout=timeout)

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not self.available:
            return []
        try:
            response = self._client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": False,
                    "search_depth": "basic",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=(item.get("content") or "")[:800],
            )
            for item in payload.get("results", [])[:max_results]
        ]


class BraveSearch:
    name = "brave"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        self._api_key = api_key or os.environ.get("BRAVE_API_KEY", "")
        self._client = httpx.Client(timeout=timeout)

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not self.available:
            return []
        try:
            response = self._client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self._api_key,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=(item.get("description") or "")[:800],
            )
            for item in (payload.get("web") or {}).get("results", [])[:max_results]
        ]


class SearxngSearch:
    """Self-hosted SearXNG; needs `format: json` enabled in its settings."""

    name = "searxng"

    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        self._base_url = (base_url or os.environ.get("SEARXNG_URL", "")).rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    @property
    def available(self) -> bool:
        return bool(self._base_url)

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not self.available:
            return []
        try:
            response = self._client.get(
                f"{self._base_url}/search",
                params={"q": query, "format": "json", "language": "en"},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=(item.get("content") or "")[:800],
            )
            for item in payload.get("results", [])[:max_results]
        ]
