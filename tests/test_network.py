"""Live checks against the real Crossref and OpenAlex APIs.

Skipped by default. A mocked test cannot catch a query parameter the service
rejects: an unsupported `select` field made every title lookup return 400, which
the code read as "no such paper" and no unit test could see.

Run with:  SCIEVAL_NETWORK_TESTS=1 uv run pytest tests/test_network.py -v
"""

from __future__ import annotations

import os

import pytest

from scieval.search.crossref import (
    TITLE_MATCH_THRESHOLD,
    TITLE_PLAUSIBLE_THRESHOLD,
    CrossrefLookup,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("SCIEVAL_NETWORK_TESTS"),
    reason="set SCIEVAL_NETWORK_TESTS=1 to run tests that call Crossref and OpenAlex",
)


@pytest.fixture(scope="module")
def lookup():
    client = CrossrefLookup(pause_s=1.0)
    yield client
    client.close()


def test_a_real_paper_is_found_by_title(lookup):
    record = lookup.lookup(
        raw="He, K. et al. Deep residual learning for image recognition. CVPR, 2016.",
        title="Deep residual learning for image recognition",
        year="2016",
    )
    assert record.found is True
    assert record.match_score >= TITLE_MATCH_THRESHOLD
    assert "residual learning" in record.title.lower()
    assert record.year == "2016"
    assert record.doi
    assert record.url


def test_a_real_paper_is_found_by_doi(lookup):
    record = lookup.lookup(raw="Optuna", doi="10.1145/3292500.3330701")
    assert record.found is True
    assert record.doi.lower() == "10.1145/3292500.3330701"
    assert record.year == "2019"
    assert record.is_retracted is False


def test_a_fabricated_reference_is_not_matched_to_a_real_paper(lookup):
    """The dangerous failure: a plausible-looking wrong record invites a false
    'verified'."""
    record = lookup.lookup(
        raw="Nonexistent, Q. A study of imaginary caching. Journal of Nowhere, 2021.",
        title="A study of imaginary caching in nonexistent distributed systems",
        year="2021",
    )
    if record.found:
        assert record.match_score < TITLE_PLAUSIBLE_THRESHOLD, (
            f"fabricated reference matched '{record.title}' at {record.match_score}"
        )
