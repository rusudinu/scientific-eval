"""Extraction: sections, captions, bibliography, citation mapping."""

from __future__ import annotations

from scieval.extract.bibliography import _expand_citation_group, extract_references
from scieval.extract.sections import detect_sections, resplit_with_inventory


def test_sections_are_detected_and_classified(paper):
    titles = [s.title for s in paper.sections]
    assert "Abstract" in titles
    assert "Introduction" in titles
    assert "References" in titles

    kinds = {s.kind for s in paper.sections}
    for expected in {"abstract", "introduction", "background", "methods", "results",
                     "discussion", "conclusion", "references"}:
        assert expected in kinds, f"missing section kind: {expected}"


def test_references_section_is_excluded_from_review(paper):
    reviewable = {s.kind for s in paper.reviewable_sections()}
    assert "references" not in reviewable


def test_bibliography_entries_are_parsed(paper):
    assert len(paper.references) == 4
    by_index = {r.index: r for r in paper.references}
    assert by_index[3].doi == "10.1000/jsr.2021.0042"
    assert by_index[1].year == "2018"
    assert "Static cache sizing" in (by_index[1].title or "")


def test_citing_sentences_are_attached(paper):
    for reference in paper.references:
        assert reference.citing_sentences, f"reference {reference.index} has no citing sentence"
    first = next(r for r in paper.references if r.index == 1)
    assert "static cache sizing" in first.citing_sentences[0].quote.lower()


def test_captions_and_in_text_references(paper):
    captions = {c.id: c for c in paper.captions}
    assert set(captions) == {"Figure 1", "Table 1"}
    # The synthetic paper cites Table 1 but never mentions Figure 1.
    assert captions["Table 1"].referenced_in_text is True
    assert captions["Figure 1"].referenced_in_text is False
    assert captions["Table 1"].caption.startswith("Mean latency by policy")


def test_caption_regex_does_not_swallow_cross_references(paper):
    table = next(c for c in paper.captions if c.id == "Table 1")
    assert "reports mean latency per policy" not in table.caption


def test_table_text_is_collected(paper):
    assert "Adaptive (ours)" in paper.tables_text


def test_citation_group_expansion():
    assert _expand_citation_group("3") == [3]
    assert _expand_citation_group("3, 5") == [3, 5]
    assert _expand_citation_group("3-6") == [3, 4, 5, 6]
    assert _expand_citation_group("1; 4") == [1, 4]
    # A range wide enough to be a page span is ignored rather than expanded.
    assert _expand_citation_group("1-500") == []


def test_resplit_uses_inventory_titles(paper):
    inventory = [
        {"number": "", "title": "Abstract"},
        {"number": "1", "title": "Introduction"},
        {"number": "2", "title": "Related Work"},
        {"number": "3", "title": "Method"},
        {"number": "4", "title": "Results"},
    ]
    resplit = resplit_with_inventory(paper.document, inventory)
    titles = [s.title for s in resplit]
    assert titles.count("Results") == 1
    assert "Introduction" in titles
    assert all(s.text for s in resplit if s.title != "Front matter")


def test_resplit_returns_nothing_when_titles_do_not_match(paper):
    assert resplit_with_inventory(paper.document, [{"title": "Nonexistent Section"}]) == []


def test_detect_sections_falls_back_to_whole_document(paper):
    document = paper.document
    trimmed = type(document)(
        path=document.path,
        lines=document.lines[:6],
        page_count=1,
        body_size=document.body_size,
        metadata={},
    )
    sections = detect_sections(trimmed)
    assert len(sections) == 1
    assert sections[0].title == "Full text"


def test_extract_references_handles_missing_section():
    assert extract_references([]) == []
