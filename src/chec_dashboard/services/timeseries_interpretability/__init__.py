"""Structured UITI impact time-series interpretability workflow."""

from chec_dashboard.services.timeseries_interpretability.contracts import (
    EvidenceMatrixRow,
    EvidenceReference,
    InterpretabilityStatus,
    InterpretabilityTrace,
    PointNarrative,
    TimeseriesInterpretabilityNarrative,
)
from chec_dashboard.services.timeseries_interpretability.deterministic_narrative import (
    build_deterministic_narrative,
    flatten_narrative_to_text,
)

__all__ = [
    "EvidenceMatrixRow",
    "EvidenceReference",
    "InterpretabilityStatus",
    "InterpretabilityTrace",
    "PointNarrative",
    "TimeseriesInterpretabilityNarrative",
    "build_deterministic_narrative",
    "flatten_narrative_to_text",
]
