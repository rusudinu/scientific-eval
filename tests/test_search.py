"""Reference lookup and web-search provider selection."""

from __future__ import annotations

import httpx
import respx

from scieval.config import load_config
from scieval.search import build_web_search
from scieval.search.crossref import CrossrefLookup

CROSSREF_ITEM = {
    "DOI": "10.1000/jsr.2021.0042",
    "title": ["Learned cache replacement"],
    "author": [{"given": "W.", "family": "Chen"}, {"given": "R.", "family": "Gupta"}],
    "issued": {"date-parts": [[2021]]},
    "container-title": ["Journal of Systems Research"],
    "type": "journal-article",
    "URL": "https://doi.org/10.1000/jsr.2021.0042",
    "abstract": "<jats:p>We learn cache replacement.</jats:p>",
}


def _lookup() -> CrossrefLookup:
    return CrossrefLookup(pause_s=0.0)


@respx.mock
def test_doi_lookup_returns_metadata():
    respx.get("https://api.crossref.org/works/10.1000/jsr.2021.0042").mock(
        return_value=httpx.Response(200, json={"message": CROSSREF_ITEM})
    )
    record = _lookup().lookup(raw="Chen et al.", doi="10.1000/jsr.2021.0042")
    assert record.found is True
    assert record.title == "Learned cache replacement"
    assert record.year == "2021"
    assert record.venue == "Journal of Systems Research"
    assert record.abstract == "We learn cache replacement."
    assert record.is_retracted is False


@respx.mock
def test_retraction_is_detected():
    retracted = dict(
        CROSSREF_ITEM, **{"update-to": [{"type": "retraction", "label": "Retraction"}]}
    )
    respx.get(url__startswith="https://api.crossref.org/works/10.1000").mock(
        return_value=httpx.Response(200, json={"message": retracted})
    )
    record = _lookup().lookup(raw="x", doi="10.1000/jsr.2021.0042")
    assert record.is_retracted is True
    assert "Retraction" in record.retraction_notes


@respx.mock
def test_preprint_is_flagged():
    preprint = dict(CROSSREF_ITEM, type="posted-content", **{"container-title": ["arXiv"]})
    respx.get(url__startswith="https://api.crossref.org/works/10.1000").mock(
        return_value=httpx.Response(200, json={"message": preprint})
    )
    assert _lookup().lookup(raw="x", doi="10.1000/x").is_preprint is True


@respx.mock
def test_title_search_rejects_a_poor_match():
    respx.get(url__startswith="https://api.crossref.org/works").mock(
        return_value=httpx.Response(
            200,
            json={"message": {"items": [dict(CROSSREF_ITEM, title=["Something else entirely"])]}},
        )
    )
    respx.get(url__startswith="https://api.openalex.org/works").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    record = _lookup().lookup(raw="Learned cache replacement", title="Learned cache replacement")
    assert record.found is False


@respx.mock
def test_openalex_is_the_fallback():
    respx.get(url__startswith="https://api.crossref.org/works").mock(
        return_value=httpx.Response(200, json={"message": {"items": []}})
    )
    respx.get(url__startswith="https://api.openalex.org/works").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "title": "Learned cache replacement",
                        "publication_year": 2021,
                        "type": "article",
                        "doi": "https://doi.org/10.1000/jsr.2021.0042",
                        "is_retracted": False,
                        "authorships": [{"author": {"display_name": "W. Chen"}}],
                        "primary_location": {"source": {"display_name": "JSR"}},
                    }
                ]
            },
        )
    )
    record = _lookup().lookup(raw="x", title="Learned cache replacement")
    assert record.found is True
    assert record.source == "openalex"
    assert record.doi == "10.1000/jsr.2021.0042"


@respx.mock
def test_network_failure_degrades_to_not_found():
    respx.get(url__startswith="https://api.crossref.org").mock(side_effect=httpx.ConnectError("x"))
    respx.get(url__startswith="https://api.openalex.org").mock(side_effect=httpx.ConnectError("x"))
    assert _lookup().lookup(raw="x", title="y").found is False


def test_web_search_without_a_key_degrades_to_no_tool(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    config = load_config()
    config.search.web_provider = "tavily"
    provider = build_web_search(config)
    assert provider.available is False
    assert provider.name == "none"
    assert provider.search("anything") == []


def test_configured_web_search_with_a_key_is_used(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    config = load_config()
    config.search.web_provider = "tavily"
    provider = build_web_search(config)
    assert provider.name == "tavily"
    assert provider.available is True


# --- title matching -------------------------------------------------------------


def test_a_survey_about_a_paper_is_not_that_paper():
    """token_set_ratio scored this pair 100; the survey is a different work."""
    from scieval.search.crossref import TITLE_MATCH_THRESHOLD, score_match

    score = score_match(
        "Deep residual learning for image recognition",
        "Deep Residual Learning for Image Recognition: A Survey",
    )
    assert score < TITLE_MATCH_THRESHOLD


def test_the_same_paper_matches_despite_casing():
    from scieval.search.crossref import TITLE_MATCH_THRESHOLD, score_match

    assert score_match("Attention is all you need", "Attention Is All You Need") >= (
        TITLE_MATCH_THRESHOLD
    )


def test_an_unrelated_paper_does_not_look_plausible():
    """A fabricated reference previously matched a real, unrelated paper at 84."""
    from scieval.search.crossref import TITLE_PLAUSIBLE_THRESHOLD, score_match

    score = score_match(
        "A study of imaginary caching in nonexistent distributed systems",
        "Write caching in distributed file systems",
    )
    assert score < TITLE_PLAUSIBLE_THRESHOLD


def test_a_matching_title_with_a_distant_year_is_penalised():
    from scieval.search.crossref import TITLE_MATCH_THRESHOLD, score_match

    same_year = score_match("Static cache sizing", "Static cache sizing", "2018", "2018")
    far_year = score_match("Static cache sizing", "Static cache sizing", "2018", "2003")
    assert same_year >= TITLE_MATCH_THRESHOLD
    assert far_year < TITLE_MATCH_THRESHOLD
    # A one-year difference is normal between preprint and publication.
    assert score_match("Static cache sizing", "Static cache sizing", "2018", "2019") == same_year


@respx.mock
def test_the_bibliographic_query_sends_no_select_parameter():
    """An unsupported `select` field made Crossref 400 the whole query, which read
    as 'no such paper'."""
    route = respx.get(url__startswith="https://api.crossref.org/works").mock(
        return_value=httpx.Response(200, json={"message": {"items": [CROSSREF_ITEM]}})
    )
    respx.get(url__startswith="https://api.openalex.org/works").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    _lookup().lookup(raw="x", title="Learned cache replacement", year="2021")
    assert "select" not in str(route.calls[0].request.url)
