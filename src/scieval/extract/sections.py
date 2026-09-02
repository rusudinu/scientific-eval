"""Section detection: layout heuristics first, then a re-split from the Pass 0 inventory."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .pdf import Document, Line, lines_to_text

# Headings papers use even when they are not numbered.
KNOWN_HEADINGS = {
    "abstract", "introduction", "background", "related work", "related works",
    "literature review", "methods", "method", "methodology", "materials and methods",
    "experimental setup", "experiments", "approach", "results", "results and discussion",
    "evaluation", "discussion", "conclusion", "conclusions", "conclusion and future work",
    "future work", "limitations", "acknowledgements", "acknowledgments", "references",
    "bibliography", "appendix", "data availability", "declarations", "funding",
}

NUMBERED = re.compile(r"^(?P<number>\d+(?:\.\d+)*)\.?\s+(?P<title>\S.{0,110})$")
ROMAN = re.compile(r"^(?P<number>[IVXLC]+)\.\s+(?P<title>\S.{0,110})$")
APPENDIX = re.compile(r"^(?P<number>Appendix\s+[A-Z0-9]*)\.?\s*(?P<title>.{0,110})$", re.I)
_END_PUNCT = re.compile(r"[.!?,;:]$")


@dataclass
class Section:
    """A contiguous slice of the paper."""

    index: int
    number: str
    title: str
    text: str
    start_page: int
    end_page: int
    lines: list[Line] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.number} {self.title}".strip()

    @property
    def kind(self) -> str:
        """Coarse classification used to route sections to the right pass."""
        return classify(self.title)

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "number": self.number,
            "title": self.title,
            "kind": self.kind,
            "pages": f"{self.start_page}-{self.end_page}",
            "chars": len(self.text),
        }


def classify(title: str) -> str:
    t = title.lower().strip()
    if "abstract" in t:
        return "abstract"
    if "introduction" in t:
        return "introduction"
    if any(k in t for k in ("related work", "background", "literature", "prior work")):
        return "background"
    if any(k in t for k in ("method", "approach", "experimental setup", "materials", "design")):
        return "methods"
    if "result" in t or "evaluation" in t or "findings" in t:
        return "results"
    if "discussion" in t:
        return "discussion"
    if "conclusion" in t or "future work" in t:
        return "conclusion"
    if "limitation" in t:
        return "limitations"
    if "reference" in t or "bibliograph" in t:
        return "references"
    if "appendix" in t:
        return "appendix"
    if any(k in t for k in ("acknowledg", "funding", "declaration", "availability", "conflict")):
        return "back_matter"
    return "other"


def _heading_match(text: str) -> tuple[str, str] | None:
    """Return (number, title) when the text reads like a heading."""
    stripped = text.strip()
    if not stripped or len(stripped) > 120:
        return None
    if _END_PUNCT.search(stripped) and not APPENDIX.match(stripped):
        return None
    for pattern in (NUMBERED, ROMAN, APPENDIX):
        m = pattern.match(stripped)
        if m:
            title = (m.group("title") or "").strip()
            number = m.group("number").strip()
            if pattern is NUMBERED and not title:
                return None
            if pattern is NUMBERED and title[:1].islower():
                return None
            return number, title or number
    bare = stripped.rstrip(":").lower()
    if bare in KNOWN_HEADINGS:
        return "", stripped.rstrip(":")
    return None


def detect_sections(doc: Document) -> list[Section]:
    """Split the document on lines that look like headings."""
    heading_indexes: list[tuple[int, str, str]] = []
    for i, line in enumerate(doc.lines):
        match = _heading_match(line.text)
        if not match:
            continue
        number, title = match
        bigger = line.size >= doc.body_size + 0.4
        emphasised = line.bold or bigger or line.text.isupper()
        known = title.rstrip(":").lower() in KNOWN_HEADINGS
        if number or known or emphasised:
            heading_indexes.append((i, number, title))

    heading_indexes = _drop_duplicate_headings(heading_indexes, doc.lines)
    if len(heading_indexes) < 3:
        return [_whole_document(doc)]

    sections: list[Section] = []
    # Front matter before the first heading (title, authors, sometimes the abstract).
    first = heading_indexes[0][0]
    if first > 0:
        sections.append(_make_section(0, "", "Front matter", doc.lines[:first]))

    for pos, (start, number, title) in enumerate(heading_indexes):
        end = heading_indexes[pos + 1][0] if pos + 1 < len(heading_indexes) else len(doc.lines)
        body = doc.lines[start + 1 : end]
        sections.append(_make_section(len(sections), number, title, body, heading=doc.lines[start]))
    return sections


def _drop_duplicate_headings(
    headings: list[tuple[int, str, str]], lines: list[Line]
) -> list[tuple[int, str, str]]:
    """Drop repeated running headers and headings that carry no body text."""
    counts: dict[str, int] = {}
    kept: list[tuple[int, str, str]] = []
    for item in headings:
        key = item[2].lower()
        counts[key] = counts.get(key, 0) + 1
    for pos, item in enumerate(headings):
        key = item[2].lower()
        # A heading text repeated on many pages is a running header, not a section.
        if counts[key] > 2:
            continue
        next_start = headings[pos + 1][0] if pos + 1 < len(headings) else len(lines)
        if next_start - item[0] < 2:
            continue
        kept.append(item)
    return kept


def _make_section(
    index: int, number: str, title: str, body: list[Line], heading: Line | None = None
) -> Section:
    page_source = body or ([heading] if heading else [])
    start_page = page_source[0].page if page_source else 1
    end_page = page_source[-1].page if page_source else start_page
    return Section(
        index=index,
        number=number,
        title=title,
        text=lines_to_text(body),
        start_page=start_page,
        end_page=end_page,
        lines=body,
    )


def _whole_document(doc: Document) -> Section:
    return Section(
        index=0,
        number="",
        title="Full text",
        text=doc.text,
        start_page=1,
        end_page=doc.page_count,
        lines=doc.lines,
    )


def resplit_with_inventory(doc: Document, inventory_sections: list[dict]) -> list[Section]:
    """Re-split the document using the section list Pass 0 returned.

    Pass 0 sees the whole paper and names sections the layout heuristics miss
    (unnumbered or two-column headings). Titles it reports are matched back to
    document lines; anything unmatched is ignored so the split stays anchored in
    real text.
    """
    anchors: list[tuple[int, str, str]] = []
    used: set[int] = set()
    search_from = 0
    for entry in inventory_sections:
        title = str(entry.get("title") or "").strip()
        number = str(entry.get("number") or "").strip()
        if not title:
            continue
        idx = _find_heading_line(doc.lines, number, title, search_from, used)
        if idx is None:
            continue
        anchors.append((idx, number, title))
        used.add(idx)
        search_from = idx + 1

    if len(anchors) < 3:
        return []

    anchors.sort()
    sections: list[Section] = []
    if anchors[0][0] > 0:
        sections.append(_make_section(0, "", "Front matter", doc.lines[: anchors[0][0]]))
    for pos, (start, number, title) in enumerate(anchors):
        end = anchors[pos + 1][0] if pos + 1 < len(anchors) else len(doc.lines)
        sections.append(
            _make_section(len(sections), number, title, doc.lines[start + 1 : end], doc.lines[start])
        )
    return sections


def _normalise_title(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def _find_heading_line(
    lines: list[Line], number: str, title: str, start: int, used: set[int]
) -> int | None:
    target = _normalise_title(title)
    if not target:
        return None
    numbered_target = _normalise_title(f"{number} {title}") if number else target

    def sweep(begin: int) -> int | None:
        for i in range(begin, len(lines)):
            if i in used or len(lines[i].text) > 120:
                continue
            if _normalise_title(lines[i].text) in (target, numbered_target):
                return i
        return None

    # Sections normally appear in order, so search forward first; only fall back to
    # a full sweep when the inventory lists them out of document order.
    return sweep(start) if sweep(start) is not None else sweep(0)


def find_section(sections: list[Section], *kinds: str) -> Section | None:
    for kind in kinds:
        for section in sections:
            if section.kind == kind:
                return section
    return None


def sections_of_kind(sections: list[Section], *kinds: str) -> list[Section]:
    wanted = set(kinds)
    return [s for s in sections if s.kind in wanted]
