"""Calibration: run the pipeline over human-reviewed papers and measure agreement."""

from .ground_truth import GroundTruth, GroundTruthError, TEMPLATE, find_pairs, load
from .matcher import Match, MatchResult, match_findings, pair_score
from .metrics import CalibrationReport, PaperReport, Scores, aggregate, render_markdown, write_csv
from .run import run_calibration

__all__ = [
    "CalibrationReport", "GroundTruth", "GroundTruthError", "Match", "MatchResult", "PaperReport",
    "Scores", "TEMPLATE", "aggregate", "find_pairs", "load", "match_findings", "pair_score",
    "render_markdown", "run_calibration", "write_csv",
]
