"""Spellcheck candidate generation and pre-filtering."""

from __future__ import annotations

from scieval.extract.sections import Section
from scieval.spellcheck.backend import NullBackend, build_backend
from scieval.spellcheck.filters import candidates_for_section, collect_allowlist


def _section(text: str) -> Section:
    return Section(index=0, number="1", title="Test", text=text, start_page=1, end_page=1)


def _candidates(text: str, allowlist: set[str] | None = None):
    backend = build_backend("pyspellchecker", "en")
    return candidates_for_section(_section(text), backend, allowlist or set())


def test_real_misspellings_are_flagged():
    tokens = {c.token for c in _candidates("This was allready splitted into parts.")}
    assert {"allready", "splitted"} <= tokens


def test_hyphenated_compounds_of_known_words_are_not_flagged():
    tokens = {c.token for c in _candidates("We use a key-value store with write-heavy traffic.")}
    assert "key-value" not in tokens
    assert "write-heavy" not in tokens


def test_hyphenated_compound_with_a_bad_part_is_flagged():
    tokens = {c.token for c in _candidates("A key-vlaue store was used throughout.")}
    assert "key-vlaue" in tokens


def test_tokens_with_digits_or_underscores_are_skipped():
    tokens = {c.token for c in _candidates("We set alpha_max and ran GPT4x for 5 epochs.")}
    assert "alpha_max" not in tokens
    assert "GPT4x" not in tokens


def test_all_caps_acronyms_are_skipped():
    tokens = {c.token for c in _candidates("The LRU and LFU policies were compared.")}
    assert "LRU" not in tokens and "LFU" not in tokens


def test_possessives_are_normalised():
    tokens = {c.token for c in _candidates("Belady's algorithm is optimal.", {"belady"})}
    assert not any(t.startswith("Belady") for t in tokens)


def test_latex_and_urls_are_stripped():
    text = r"See \citep{smith} at https://example.com/foo-bar for detials."
    tokens = {c.token for c in _candidates(text)}
    assert "detials" in tokens
    assert not any("example" in t for t in tokens)


def test_allowlist_covers_author_names_and_defined_acronyms(paper):
    allowlist = collect_allowlist(paper.references, paper.document.text)
    assert "belady" in allowlist
    assert "nakamura" in allowlist


def test_candidates_carry_sentence_and_location():
    candidates = _candidates("The result was allready known before.")
    candidate = next(c for c in candidates if c.token == "allready")
    assert "allready" in candidate.sentence
    assert candidate.location.startswith("1 Test")
    assert candidate.as_dict()["occurrences"] == 1


def test_repeated_token_is_reported_once_with_a_count():
    candidates = _candidates("It was allready done. It was allready wrong.")
    matching = [c for c in candidates if c.token == "allready"]
    assert len(matching) == 1
    assert matching[0].count == 2


def test_null_backend_flags_nothing():
    assert candidates_for_section(_section("allready splitted"), NullBackend(), set()) == []


def test_max_candidates_is_respected():
    text = " ".join(f"wrd{i}xq" for i in range(50))
    section = _section(text.replace("0", "o"))
    backend = build_backend("pyspellchecker", "en")
    limited = candidates_for_section(section, backend, set(), max_candidates=5)
    assert len(limited) <= 5


def test_unknown_backend_name_degrades_to_null():
    backend = build_backend("does-not-exist", "en")
    assert backend.unknown(["allready"]) == set()


def test_both_casings_of_a_misspelling_are_reported():
    """A lowercase and a capitalised occurrence must not collide into one."""
    from scieval.spellcheck.backend import PySpellcheckerBackend

    backend = PySpellcheckerBackend("en")
    assert backend.unknown(["Recieve", "recieve"]) == {"Recieve", "recieve"}
