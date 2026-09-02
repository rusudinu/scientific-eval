"""Reference lookup against Crossref, with OpenAlex as the fallback."""

from __future__ import annotations

import re
import time

import httpx
from rapidfuzz import fuzz

from .base import ReferenceRecord

CROSSREF_API = "https://api.crossref.org/works"
OPENALEX_API = "https://api.openalex.org/works"
# `token_set_ratio` scores a superset title 100 ("... : A Survey" against the paper
# it surveys), so titles are compared with a symmetric, length-sensitive ratio.
# Measured separation on real pairs: true matches 100, near misses 51-91.
TITLE_MATCH_THRESHOLD = 92.0
TITLE_PLAUSIBLE_THRESHOLD = 78.0
# A title that matches but whose year is years away is a different paper.
YEAR_TOLERANCE = 1
YEAR_PENALTY = 25.0
PREPRINT_MARKERS = ("arxiv", "biorxiv", "medrxiv", "ssrn", "preprint", "posted-content", "chemrxiv")


class CrossrefLookup:
    """Deterministic metadata retrieval. No model involvement, so no hallucinated DOIs."""

    name = "crossref"
    available = True

    def __init__(
        self,
        *,
        mailto: str | None = None,
        timeout: float = 20.0,
        pause_s: float = 0.15,
        client: httpx.Client | None = None,
    ) -> None:
        self._pause = pause_s
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": (
                    "scientific-eval/0.1 (https://github.com/rusudinu/scientific-eval"
                    + (f"; mailto:{mailto}" if mailto else "")
                    + ")"
                )
            },
            follow_redirects=True,
        )

    def lookup(
        self, *, raw: str, doi: str | None = None, title: str | None = None, year: str | None = None
    ) -> ReferenceRecord:
        if doi:
            record = self._by_doi(doi)
            if record.found:
                return record
        record = self._by_bibliographic(raw, title, year)
        if record.found:
            return record
        if title:
            return self._openalex(title)
        return ReferenceRecord(found=False, source="crossref")

    def close(self) -> None:
        self._client.close()

    def _get(self, url: str, params: dict | None = None) -> dict | None:
        try:
            response = self._client.get(url, params=params)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except Exception:
            return None
        finally:
            if self._pause:
                time.sleep(self._pause)

    def _by_doi(self, doi: str) -> ReferenceRecord:
        data = self._get(f"{CROSSREF_API}/{doi.strip().rstrip('.')}")
        if not data or "message" not in data:
            return ReferenceRecord(found=False, source="crossref")
        return self._to_record(data["message"], score=100.0)

    def _by_bibliographic(
        self, raw: str, title: str | None, year: str | None = None
    ) -> ReferenceRecord:
        query = (title or raw)[:400]
        # No `select`: an unsupported field name there makes Crossref reject the whole
        # query with a 400, which is indistinguishable from "no such paper".
        data = self._get(CROSSREF_API, params={"query.bibliographic": query, "rows": 5})
        items = ((data or {}).get("message") or {}).get("items") or []
        best: ReferenceRecord | None = None
        for item in items:
            candidate = self._to_record(item)
            candidate.match_score = score_match(title or raw, candidate.title, year, candidate.year)
            if best is None or candidate.match_score > best.match_score:
                best = candidate
        if best and best.match_score >= TITLE_MATCH_THRESHOLD:
            return best
        # A near miss is still worth returning so the model can call a mismatch; a poor
        # one is not, because a plausible-looking wrong paper is worse than nothing.
        if best and best.match_score >= TITLE_PLAUSIBLE_THRESHOLD:
            best.found = True
            return best
        return ReferenceRecord(found=False, source="crossref")

    def _openalex(self, title: str) -> ReferenceRecord:
        data = self._get(OPENALEX_API, params={"search": title[:300], "per-page": 3})
        for item in (data or {}).get("results", []):
            score = score_match(title, item.get("title") or "")
            if score < TITLE_PLAUSIBLE_THRESHOLD:
                continue
            location = (item.get("primary_location") or {}).get("source") or {}
            return ReferenceRecord(
                found=True,
                url=item.get("id", ""),
                title=item.get("title") or "",
                authors=[
                    (a.get("author") or {}).get("display_name", "")
                    for a in (item.get("authorships") or [])[:10]
                ],
                year=str(item.get("publication_year") or ""),
                venue=location.get("display_name") or "",
                doi=(item.get("doi") or "").replace("https://doi.org/", ""),
                type=item.get("type") or "",
                is_retracted=bool(item.get("is_retracted")),
                is_preprint=(item.get("type") == "preprint"),
                match_score=score,
                source="openalex",
            )
        return ReferenceRecord(found=False, source="openalex")

    def _to_record(self, item: dict, score: float = 0.0) -> ReferenceRecord:
        title_list = item.get("title") or []
        title = title_list[0] if title_list else ""
        venue_list = item.get("container-title") or []
        venue = venue_list[0] if venue_list else ""
        item_type = item.get("type") or ""
        subtype = item.get("subtype") or ""
        updates = item.get("update-to") or []
        retraction_labels = [
            u.get("label", "")
            for u in updates
            if "retract" in str(u.get("type", "")).lower()
            or "retract" in str(u.get("label", "")).lower()
        ]
        blob = f"{item_type} {subtype} {venue} {title}".lower()
        return ReferenceRecord(
            found=True,
            url=item.get("URL") or (f"https://doi.org/{item['DOI']}" if item.get("DOI") else ""),
            title=title,
            authors=[
                " ".join(filter(None, [a.get("given"), a.get("family")]))
                for a in (item.get("author") or [])[:10]
            ],
            year=_issued_year(item),
            venue=venue,
            doi=item.get("DOI", ""),
            type=item_type,
            is_retracted=bool(retraction_labels) or item_type == "retraction",
            retraction_notes="; ".join(retraction_labels),
            is_preprint=any(marker in blob for marker in PREPRINT_MARKERS),
            abstract=_strip_jats(item.get("abstract") or ""),
            match_score=score,
            source="crossref",
        )


def _issued_year(item: dict) -> str:
    parts = ((item.get("issued") or {}).get("date-parts") or [[]])[0]
    return str(parts[0]) if parts else ""


def score_match(
    title: str, candidate_title: str, year: str | None = None, candidate_year: str | None = None
) -> float:
    """How well a retrieved record matches the reference, 0-100."""
    if not title or not candidate_title:
        return 0.0
    score = float(fuzz.token_sort_ratio(_norm(title), _norm(candidate_title)))
    return max(0.0, score - _year_penalty(year, candidate_year))


def _year_penalty(year: str | None, candidate_year: str | None) -> float:
    left, right = _as_year(year), _as_year(candidate_year)
    if left is None or right is None:
        return 0.0
    return YEAR_PENALTY if abs(left - right) > YEAR_TOLERANCE else 0.0


def _as_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def _strip_jats(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text).replace("&amp;", "&").strip()
