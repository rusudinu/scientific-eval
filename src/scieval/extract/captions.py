"""Figure and table caption extraction, plus in-text reference detection."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .pdf import Document
from .sections import Section

CAPTION = re.compile(
    r"^(?P<kind>Figure|Fig\.?|Table|Chart|Algorithm|Listing)\s*(?P<id>\d+|[IVXLC]+)"
    r"(?P<separator>\s*[.:\-\u2013]\s*|\s+)(?P<caption>.*)$",
    re.IGNORECASE,
)
REFERENCE_IN_TEXT = re.compile(
    r"\b(?P<kind>Figure|Fig\.?|Table|Chart|Algorithm|Listing)s?\.?\s*(?P<id>\d+|[IVXLC]+)\b",
    re.IGNORECASE,
)


@dataclass
class Caption:
    kind: str          # "figure" | "table" | "other"
    id: str            # e.g. "Figure 1"
    caption: str
    page: int
    referenced_in_text: bool = False

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "caption": self.caption,
            "page": self.page,
            "referenced_in_text": self.referenced_in_text,
        }


def _is_caption(match: re.Match) -> bool:
    """Tell a caption line from a sentence that merely mentions the figure.

    "Table 1. Mean latency by policy." is a caption; "Table 1 reports mean
    latency per policy." is a cross-reference. The separator, or a capitalised
    first word, is what distinguishes them.
    """
    text = match.group("caption").strip()
    if len(text) < 10:
        # A bare "Figure 3" line is an in-figure label, not a caption.
        return False
    separator = match.group("separator").strip()
    if separator:
        return True
    return text[:1].isupper()


def _canonical_kind(raw: str) -> str:
    low = raw.lower().rstrip(".")
    if low in {"figure", "fig"}:
        return "figure"
    if low == "table":
        return "table"
    return "other"


def _canonical_id(kind: str, number: str) -> str:
    label = {"figure": "Figure", "table": "Table"}.get(kind, kind.title())
    return f"{label} {number.upper() if not number.isdigit() else number}"


def extract_captions(doc: Document, sections: list[Section]) -> list[Caption]:
    """Find caption lines, then check whether the body text refers to each one."""
    captions: dict[str, Caption] = {}
    for line in doc.lines:
        match = CAPTION.match(line.text)
        if not match:
            continue
        kind = _canonical_kind(match.group("kind"))
        if kind == "other":
            continue
        if not _is_caption(match):
            continue
        text = match.group("caption").strip()
        cap_id = _canonical_id(kind, match.group("id"))
        if cap_id in captions:
            continue
        captions[cap_id] = Caption(kind=kind, id=cap_id, caption=text, page=line.page)

    referenced = _referenced_ids(doc, sections, set(captions))
    for cap_id, caption in captions.items():
        caption.referenced_in_text = cap_id in referenced
    return sorted(captions.values(), key=lambda c: (c.kind, _sort_key(c.id)))


def _sort_key(cap_id: str) -> tuple[int, str]:
    tail = cap_id.split()[-1]
    return (int(tail), "") if tail.isdigit() else (10**6, tail)


def _referenced_ids(doc: Document, sections: list[Section], known: set[str]) -> set[str]:
    """Ids mentioned in body text outside their own caption line."""
    caption_lines = {
        line.text
        for line in doc.lines
        if (match := CAPTION.match(line.text)) and _is_caption(match)
    }
    referenced: set[str] = set()
    for section in sections:
        if section.kind == "references":
            continue
        for line in section.text.splitlines():
            if line in caption_lines:
                continue
            for match in REFERENCE_IN_TEXT.finditer(line):
                kind = _canonical_kind(match.group("kind"))
                if kind == "other":
                    continue
                cap_id = _canonical_id(kind, match.group("id"))
                if cap_id in known:
                    referenced.add(cap_id)
    return referenced


def tables_text(doc: Document, captions: list[Caption], window: int = 40) -> str:
    """Text around each table caption, for the pass that checks table values."""
    chunks: list[str] = []
    for caption in captions:
        if caption.kind != "table":
            continue
        for i, line in enumerate(doc.lines):
            if line.text.startswith(caption.id) or caption.caption[:40] in line.text:
                block = doc.lines[max(0, i - 2) : i + window]
                chunks.append("\n".join(ln.text for ln in block))
                break
    return "\n\n".join(chunks)
