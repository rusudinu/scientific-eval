"""Bibliography parsing and citation-to-sentence mapping."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .sections import Section
from .text import split_sentences

DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
YEAR = re.compile(r"\b(19|20)\d{2}[a-z]?\b")
NUMBERED_ENTRY = re.compile(r"^\s*(?:\[(\d{1,3})\]|(\d{1,3})[.)])\s+(?=\S)")
# In-text numeric citations: [3], [3, 5], [3-7], [3], [4]
NUMERIC_CITATION = re.compile(r"\[(\d{1,3}(?:\s*[-,;]\s*\d{1,3})*)\]")
AUTHOR_YEAR = re.compile(r"\(?\b([A-Z][A-Za-z'\-]+)(?:\s+et\s+al\.?|\s+(?:and|&)\s+[A-Z][A-Za-z'\-]+)?,?\s*\(?((?:19|20)\d{2})[a-z]?\)?")


@dataclass
class CitingSentence:
    quote: str
    location: str


@dataclass
class Reference:
    index: int
    raw: str
    doi: str | None = None
    title: str | None = None
    year: str | None = None
    authors: list[str] = field(default_factory=list)
    citing_sentences: list[CitingSentence] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "raw": self.raw,
            "doi": self.doi,
            "parsed_title": self.title,
            "parsed_year": self.year,
            "parsed_authors": self.authors,
            "citing_sentences": [
                {"quote": c.quote, "location": c.location} for c in self.citing_sentences
            ],
        }


def extract_references(sections: list[Section]) -> list[Reference]:
    """Parse the references section into entries."""
    block = "\n".join(s.text for s in sections if s.kind == "references")
    if not block.strip():
        return []
    entries = _split_entries(block)
    references: list[Reference] = []
    for i, raw in enumerate(entries, start=1):
        index, text = _strip_leading_number(raw)
        references.append(_parse_entry(index or i, text))
    return references


def _split_entries(block: str) -> list[str]:
    lines = [ln.strip() for ln in block.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return []

    numbered = [i for i, ln in enumerate(lines) if NUMBERED_ENTRY.match(ln)]
    if len(numbered) >= 2:
        entries = []
        for pos, start in enumerate(numbered):
            end = numbered[pos + 1] if pos + 1 < len(numbered) else len(lines)
            entries.append(" ".join(lines[start:end]))
        return entries

    # Unnumbered: a new entry starts at a line beginning with an author-like token,
    # and each entry ends where a year appears.
    entries: list[str] = []
    current: list[str] = []
    for line in lines:
        if current and re.match(r"^[A-Z][A-Za-z'\-]+,", line) and YEAR.search(" ".join(current)):
            entries.append(" ".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        entries.append(" ".join(current))
    return entries


def _strip_leading_number(raw: str) -> tuple[int | None, str]:
    m = NUMBERED_ENTRY.match(raw)
    if not m:
        return None, raw.strip()
    number = m.group(1) or m.group(2)
    return int(number), raw[m.end():].strip()


def _parse_entry(index: int, raw: str) -> Reference:
    doi_match = DOI.search(raw)
    year_match = YEAR.search(raw)
    return Reference(
        index=index,
        raw=raw,
        doi=doi_match.group(0).rstrip(".,;") if doi_match else None,
        title=_guess_title(raw),
        year=year_match.group(0) if year_match else None,
        authors=_guess_authors(raw),
    )


def _guess_title(raw: str) -> str | None:
    """Take the longest sentence-like chunk that is not the author list or venue."""
    working = DOI.sub("", raw)
    parts = [p.strip(" .,") for p in re.split(r"(?<=[.?])\s+", working) if p.strip(" .,")]
    candidates = [
        p for p in parts
        if len(p) > 15 and not re.fullmatch(r"[A-Z][A-Za-z'\-]+(,? (and |& )?[A-Z]\.)+", p)
    ]
    if not candidates:
        return None
    # The title is usually the first long chunk after the authors and year.
    for part in candidates:
        letters = re.sub(r"[^A-Za-z ]", "", part)
        initials = len(re.findall(r"\b[A-Z]\.", part))
        if initials <= 2 and len(letters.split()) >= 3:
            return part
    return candidates[0]


def _guess_authors(raw: str) -> list[str]:
    head = raw[:220]
    names = re.findall(r"\b([A-Z][A-Za-z'\-]{1,20})(?=,\s*(?:[A-Z]\.|[A-Z][a-z]))", head)
    unique: list[str] = []
    for name in names:
        if name not in unique and name.lower() not in {"and", "the"}:
            unique.append(name)
    return unique[:8]


def attach_citing_sentences(references: list[Reference], sections: list[Section]) -> None:
    """Populate each reference's citing sentences from the body text."""
    if not references:
        return
    by_index = {ref.index: ref for ref in references}
    surname_map = _surname_map(references)

    for section in sections:
        if section.kind in {"references", "back_matter"}:
            continue
        for sentence in _sentences(section.text):
            location = f"{section.label} (p. {section.start_page})"
            for group in NUMERIC_CITATION.findall(sentence):
                for number in _expand_citation_group(group):
                    ref = by_index.get(number)
                    if ref is not None:
                        _add_sentence(ref, sentence, location)
            for surname, year in AUTHOR_YEAR.findall(sentence):
                ref = surname_map.get((surname.lower(), year))
                if ref is not None:
                    _add_sentence(ref, sentence, location)


def _surname_map(references: list[Reference]) -> dict[tuple[str, str], Reference]:
    mapping: dict[tuple[str, str], Reference] = {}
    for ref in references:
        if not ref.year:
            continue
        for author in ref.authors[:1]:
            mapping.setdefault((author.lower(), ref.year[:4]), ref)
    return mapping


def _expand_citation_group(group: str) -> list[int]:
    numbers: list[int] = []
    for part in re.split(r"[,;]", group):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            bounds = [b.strip() for b in part.split("-", 1)]
            if all(b.isdigit() for b in bounds):
                lo, hi = int(bounds[0]), int(bounds[1])
                if 0 < hi - lo < 60:
                    numbers.extend(range(lo, hi + 1))
                continue
        if part.isdigit():
            numbers.append(int(part))
    return numbers


def _add_sentence(ref: Reference, sentence: str, location: str, limit: int = 4) -> None:
    quote = sentence.strip()
    if len(quote) > 400:
        quote = quote[:397] + "..."
    if len(ref.citing_sentences) >= limit:
        return
    if any(c.quote == quote for c in ref.citing_sentences):
        return
    ref.citing_sentences.append(CitingSentence(quote=quote, location=location))


def _sentences(text: str) -> list[str]:
    return split_sentences(text)
