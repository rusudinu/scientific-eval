"""Shared text utilities: abbreviation-aware sentence splitting."""

from __future__ import annotations

import re

_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[(])")

# A period after one of these does not end a sentence. "Smith et al. (2018) showed..."
# must stay in one piece or the citation mapper never sees the surname and the year
# together.
ABBREVIATIONS = {
    "al", "e.g", "eg", "i.e", "ie", "cf", "vs", "etc", "approx", "ca", "resp", "viz",
    "fig", "figs", "eq", "eqs", "no", "nos", "ref", "refs", "sec", "secs", "ch", "chap",
    "p", "pp", "vol", "vols", "ed", "eds", "trans", "dr", "prof", "mr", "mrs", "ms",
    "st", "inc", "ltd", "co", "dept", "univ", "est", "min", "max", "avg", "std", "vs",
}

_TRAILING_TOKEN = re.compile(r"([A-Za-z.]+)\.$")


def split_sentences(text: str) -> list[str]:
    """Split into sentences, keeping abbreviations and initials attached."""
    flat = re.sub(r"\s*\n\s*", " ", text).strip()
    if not flat:
        return []
    pieces = _SPLIT.split(flat)

    sentences: list[str] = []
    for piece in pieces:
        if sentences and _ends_with_abbreviation(sentences[-1]):
            sentences[-1] = f"{sentences[-1]} {piece}"
        else:
            sentences.append(piece)
    return [s.strip() for s in sentences if s.strip()]


def _ends_with_abbreviation(sentence: str) -> bool:
    match = _TRAILING_TOKEN.search(sentence.rstrip())
    if not match:
        return False
    token = match.group(1)
    # A single capital letter is an initial: "Belady, L. A study of..." keeps going.
    if len(token) == 1 and token.isupper():
        return True
    return token.lower().rstrip(".") in ABBREVIATIONS
