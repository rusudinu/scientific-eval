"""Tokenisation and pre-filtering of spellcheck candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..extract.bibliography import Reference
from ..extract.sections import Section
from .backend import SpellBackend

TOKEN = re.compile(r"[A-Za-z][A-Za-z'\u2019\-]*")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[(])")
LATEX = re.compile(r"\\[A-Za-z]+|\$[^$]*\$")
URL = re.compile(r"https?://\S+|www\.\S+|\b10\.\d{4,9}/\S+")
HAS_DIGIT_OR_UNDERSCORE = re.compile(r"[\d_]")
ACRONYM_DEFINITION = re.compile(r"\(([A-Z][A-Za-z0-9]{1,9})s?\)")

# Tokens a general dictionary rejects but every paper legitimately contains.
COMMON_ACADEMIC = {
    "et", "al", "etal", "vs", "cf", "ibid", "eg", "ie", "arxiv", "doi", "isbn", "issn",
    "http", "https", "www", "pdf", "url", "dataset", "datasets", "preprint", "supplementary",
}


@dataclass
class Candidate:
    """One spellcheck hit handed to the model for triage."""

    token: str
    sentence: str
    location: str
    suggestion: str | None = None
    count: int = 1

    def as_dict(self) -> dict:
        data = {
            "token": self.token,
            "sentence": self.sentence,
            "location": self.location,
            "occurrences": self.count,
        }
        if self.suggestion:
            data["checker_suggestion"] = self.suggestion
        return data


def collect_allowlist(references: list[Reference], full_text: str) -> set[str]:
    """Tokens that must never be flagged: author surnames and defined acronyms."""
    allow: set[str] = set(COMMON_ACADEMIC)
    for ref in references:
        for author in ref.authors:
            allow.add(author.lower())
        # Every capitalised word in a reference is a name, venue or proper noun.
        for token in TOKEN.findall(ref.raw):
            if token[:1].isupper() and len(token) > 2:
                allow.add(token.lower())
    for acronym in ACRONYM_DEFINITION.findall(full_text):
        allow.add(acronym.lower())
    return allow


def candidates_for_section(
    section: Section,
    backend: SpellBackend,
    allowlist: set[str],
    *,
    min_length: int = 3,
    max_candidates: int = 120,
) -> list[Candidate]:
    """Run the checker over one section and pre-filter the obvious false positives."""
    text = LATEX.sub(" ", section.text)
    text = URL.sub(" ", text)

    occurrences: dict[str, Candidate] = {}
    for sentence in _sentences(text):
        for raw_token in _raw_tokens(sentence):
            token = _strip_possessive(raw_token.strip("'\u2019-"))
            if not _is_checkable(token, raw_token, allowlist, min_length):
                continue
            key = token.lower()
            if key in occurrences:
                occurrences[key].count += 1
                continue
            occurrences[key] = Candidate(
                token=token,
                sentence=_trim(sentence),
                location=f"{section.label} (p. {section.start_page})",
            )

    candidates = _unknown_candidates(list(occurrences.values()), backend, allowlist, min_length)
    for candidate in candidates:
        candidate.suggestion = backend.correction(candidate.token)
    candidates.sort(key=lambda c: (-c.count, c.token.lower()))
    return candidates[:max_candidates]


def _unknown_candidates(
    candidates: list[Candidate], backend: SpellBackend, allowlist: set[str], min_length: int
) -> list[Candidate]:
    """Ask the dictionary about each candidate, checking hyphenated words part by part.

    A general dictionary rejects "key-value" and "write-heavy" as wholes even
    though both parts are ordinary words. Only a token with an unknown part is
    worth the model's attention.
    """
    simple = [c for c in candidates if "-" not in c.token]
    compound = [c for c in candidates if "-" in c.token]

    parts: set[str] = set()
    for candidate in compound:
        parts.update(
            part for part in candidate.token.split("-")
            if len(part) >= min_length and part.lower() not in allowlist
        )
    unknown = backend.unknown([c.token for c in simple] + sorted(parts))

    kept = [c for c in simple if c.token in unknown]
    for candidate in compound:
        if any(part in unknown for part in candidate.token.split("-")):
            kept.append(candidate)
    return kept


def _strip_possessive(token: str) -> str:
    return re.sub(r"['\u2019]s$", "", token)


def _raw_tokens(sentence: str) -> list[str]:
    # Split on whitespace first so tokens containing digits or underscores are
    # rejected as a whole rather than silently broken into letter runs.
    return [chunk.strip(".,;:()[]{}\"") for chunk in sentence.split()]


def _is_checkable(token: str, raw: str, allowlist: set[str], min_length: int) -> bool:
    if len(token) < min_length:
        return False
    if not TOKEN.fullmatch(token):
        return False
    if HAS_DIGIT_OR_UNDERSCORE.search(raw):
        return False
    if token.isupper():           # acronyms are judged by the terminology task, not spelling
        return False
    if token.lower() in allowlist:
        return False
    return True


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"\s*\n\s*", " ", text)
    return [s.strip() for s in SENTENCE_SPLIT.split(flat) if s.strip()]


def _trim(sentence: str, limit: int = 300) -> str:
    return sentence if len(sentence) <= limit else sentence[: limit - 3] + "..."
