from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fixtures.paper_builder import build

from scieval.config import load_config
from scieval.pipeline import build_paper_context


@pytest.fixture(scope="session")
def paper_pdf(tmp_path_factory) -> Path:
    """The synthetic paper, built once per test session."""
    target = tmp_path_factory.mktemp("papers") / "synthetic-paper.pdf"
    return build(target)


@pytest.fixture(scope="session")
def config(tmp_path_factory):
    cfg = load_config()
    cfg.output_dir = tmp_path_factory.mktemp("out")
    return cfg


@pytest.fixture(scope="session")
def paper(paper_pdf, config):
    return build_paper_context(paper_pdf, config)
