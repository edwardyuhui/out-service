"""Unit guards for evidence-constrained generalization explanations."""

from app.schemas.diagnostics import DelayPartitionDiagnostics
from app.services.generalization_diagnostics_service import _has_delay_variation


def test_zero_correlation_peak_is_not_reported_as_delay_drift() -> None:
    """A flat test input has an arbitrary argmax(0), not delay-change evidence."""

    peaks = {
        "u1": {
            "train": DelayPartitionDiagnostics(peak_lag=5, peak_correlation=0.43),
            "validation": DelayPartitionDiagnostics(peak_lag=5, peak_correlation=0.41),
            "test": DelayPartitionDiagnostics(peak_lag=0, peak_correlation=0.0),
        }
    }

    assert _has_delay_variation(peaks) is False
