"""Deterministic spellcheck backends. The checker finds tokens; the model judges them."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SpellBackend(Protocol):
    name: str

    def unknown(self, tokens: list[str]) -> set[str]:
        """Return the subset of tokens the dictionary does not know."""

    def correction(self, token: str) -> str | None:
        """Best-guess correction, or None."""


class NullBackend:
    """Used when spellchecking is disabled; flags nothing."""

    name = "none"

    def unknown(self, tokens: list[str]) -> set[str]:
        return set()

    def correction(self, token: str) -> str | None:
        return None


class PySpellcheckerBackend:
    """pyspellchecker: a frequency-list dictionary, no morphology."""

    name = "pyspellchecker"

    def __init__(self, language: str = "en") -> None:
        from spellchecker import SpellChecker

        self._checker = SpellChecker(language=_pyspell_language(language), distance=1)

    def unknown(self, tokens: list[str]) -> set[str]:
        if not tokens:
            return set()
        # pyspellchecker lowercases internally. Map each lowered form back to every
        # original casing, so "Recieve" and "recieve" are both returned.
        by_lowered: dict[str, set[str]] = {}
        for token in tokens:
            by_lowered.setdefault(token.lower(), set()).add(token)
        unknown_lower = self._checker.unknown(list(by_lowered))
        return {
            original
            for lowered in unknown_lower
            for original in by_lowered.get(lowered, set())
        }

    def correction(self, token: str) -> str | None:
        result = self._checker.correction(token.lower())
        if not result or result == token.lower():
            return None
        return result


class HunspellBackend:
    """hunspell dictionaries through spylls (pure Python, no system binary)."""

    name = "hunspell"

    def __init__(self, language: str = "en_US") -> None:
        from spylls.hunspell import Dictionary

        self._dictionary = Dictionary.from_files(_hunspell_language(language))

    def unknown(self, tokens: list[str]) -> set[str]:
        return {t for t in tokens if not self._dictionary.lookup(t)}

    def correction(self, token: str) -> str | None:
        for suggestion in self._dictionary.suggest(token):
            return suggestion
        return None


def _pyspell_language(language: str) -> str:
    # pyspellchecker ships one merged English dictionary.
    return "en" if language.lower().startswith("en") else language.lower()[:2]


def _hunspell_language(language: str) -> str:
    mapping = {"en-gb": "en_GB", "en_gb": "en_GB", "en-us": "en_US", "en_us": "en_US", "en": "en_US"}
    return mapping.get(language.lower(), language)


def build_backend(name: str, language: str = "en") -> SpellBackend:
    """Create a backend by name, falling back to pyspellchecker then to nothing."""
    if name == "none":
        return NullBackend()
    if name == "hunspell":
        try:
            return HunspellBackend(language)
        except Exception:
            name = "pyspellchecker"
    if name == "pyspellchecker":
        try:
            return PySpellcheckerBackend(language)
        except Exception:
            return NullBackend()
    return NullBackend()
