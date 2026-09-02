"""Pydantic schemas mirroring the JSON schemas in prompts/paper-review-prompts.md."""

from .common import (
    ClaimVerdict,
    Finding,
    LimitedModel,
    ReferenceStatus,
    Severity,
    Stability,
    StrictModel,
    SupportsClaim,
    TriageClass,
    Verdict,
    sort_findings,
)
from .pass0 import Pass0Output
from .pass1 import Pass1Output
from .pass2 import Pass2Output
from .pass3 import Pass3Output
from .pass4 import Pass4ClaimsOutput, Pass4Output

__all__ = [
    "ClaimVerdict", "Finding", "LimitedModel", "Pass0Output", "Pass1Output", "Pass2Output",
    "Pass3Output", "Pass4ClaimsOutput", "Pass4Output", "ReferenceStatus", "Severity",
    "Stability", "StrictModel", "SupportsClaim", "TriageClass", "Verdict", "sort_findings",
]
