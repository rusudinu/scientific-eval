"""Matching model findings against human findings."""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from ..schemas import Finding

DEFAULT_THRESHOLD = 70.0
MIN_QUOTE_SCORE = 55.0


@dataclass
class Match:
    truth: Finding
    predicted: Finding
    score: float
    severity_agrees: bool


@dataclass
class MatchResult:
    matches: list[Match]
    missed: list[Finding]  # in the human review, not produced by the model
    spurious: list[Finding]  # produced by the model, not in the human review

    @property
    def true_positives(self) -> int:
        return len(self.matches)


def pair_score(truth: Finding, predicted: Finding) -> float:
    """Similarity of two findings: mostly the quote, then location and description."""
    quote_score = _score(truth.quote, predicted.quote)
    location_score = _location_score(truth.location, predicted.location)
    description_score = _score(truth.description, predicted.description)

    if not truth.quote or not predicted.quote:
        # Without a shared quote, the description carries the match.
        return 0.65 * description_score + 0.35 * location_score
    if quote_score < MIN_QUOTE_SCORE and description_score < 70.0:
        return 0.0
    return 0.6 * quote_score + 0.15 * location_score + 0.25 * description_score


def _score(left: str, right: str) -> float:
    left, right = " ".join((left or "").split()).lower(), " ".join((right or "").split()).lower()
    if not left or not right:
        return 0.0
    return float(fuzz.token_set_ratio(left, right))


def _location_score(left: str, right: str) -> float:
    left, right = (left or "").lower(), (right or "").lower()
    if not left or not right:
        return 50.0  # unknown location is neutral, not disqualifying
    return float(fuzz.partial_ratio(left, right))


def match_findings(
    truth: list[Finding], predicted: list[Finding], *, threshold: float = DEFAULT_THRESHOLD
) -> MatchResult:
    """Greedy one-to-one matching, best pairs first."""
    pairs: list[tuple[float, int, int]] = []
    for i, expected in enumerate(truth):
        for j, produced in enumerate(predicted):
            score = pair_score(expected, produced)
            if score >= threshold:
                pairs.append((score, i, j))
    pairs.sort(key=lambda p: -p[0])

    used_truth: set[int] = set()
    used_pred: set[int] = set()
    matches: list[Match] = []
    for score, i, j in pairs:
        if i in used_truth or j in used_pred:
            continue
        used_truth.add(i)
        used_pred.add(j)
        matches.append(
            Match(
                truth=truth[i],
                predicted=predicted[j],
                score=round(score, 1),
                severity_agrees=truth[i].severity is predicted[j].severity,
            )
        )
    return MatchResult(
        matches=matches,
        missed=[f for i, f in enumerate(truth) if i not in used_truth],
        spurious=[f for j, f in enumerate(predicted) if j not in used_pred],
    )
