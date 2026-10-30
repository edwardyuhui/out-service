from __future__ import annotations

from datetime import UTC, datetime, timedelta

from algorithms.cleaning.pipeline import CleaningContext, CleaningParameters, CleaningPipeline
from algorithms.cleaning.quality import (
    build_quality_profile,
    classify_candidate_frozen_segments,
    enrich_freeze_diagnostics,
)


def _profile_for(values: list[float]) -> dict[str, object]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return build_quality_profile(
        dataset_id="00000000-0000-0000-0000-000000000001",
        version_id="00000000-0000-0000-0000-000000000002",
        headers=["timestamp", "control"],
        rows=[
            {
                "timestamp": (start + timedelta(seconds=index)).isoformat(),
                "control": str(value),
            }
            for index, value in enumerate(values)
        ],
        inferred_types={"timestamp": "datetime", "control": "float"},
        timestamps=[start + timedelta(seconds=index) for index in range(len(values))],
    ).payload


def test_periodic_piecewise_holds_are_retained_as_audit_data_but_not_reported_as_freezes() -> None:
    hold_length = 12
    values = [float(level) for level in range(10) for _ in range(hold_length)]

    profile = _profile_for(values)

    assert len(profile["frozen_segments"]) == 10
    assert profile["candidate_frozen_segments"] == []
    assert all(issue["code"] != "FROZEN_SEGMENTS" for issue in profile["quality_issues"])


def test_an_exceptionally_long_hold_is_reported_relative_to_the_column_baseline() -> None:
    normal_hold = 10
    values = [float(level) for level in range(5) for _ in range(normal_hold)]
    long_start = len(values)
    values.extend([99.0] * (normal_hold * 5))
    values.extend(float(level) for level in range(5, 10) for _ in range(normal_hold))

    profile = _profile_for(values)

    assert profile["candidate_frozen_segments"] == [
        {
            "column": "control",
            "start_index": long_start,
            "end_index": long_start + normal_hold * 5 - 1,
            "length": normal_hold * 5,
        }
    ]
    assert profile["freeze_detection_summary"]["longest_segment"]["length"] == normal_hold * 5


def test_a_constant_column_is_reported_as_a_candidate_freeze() -> None:
    profile = _profile_for([7.5] * 100)

    assert profile["constant_columns"] == ["control"]
    assert profile["candidate_frozen_segments"] == [
        {"column": "control", "start_index": 0, "end_index": 99, "length": 100}
    ]


def test_stored_profiles_receive_candidate_semantics_without_losing_raw_audit_segments() -> None:
    normal_hold = 8
    values = [float(level) for level in range(4) for _ in range(normal_hold)]
    long_start = len(values)
    values.extend([42.0] * (normal_hold * 5))
    values.extend(float(level) for level in range(4, 8) for _ in range(normal_hold))
    stored_profile = _profile_for(values)
    stored_profile.pop("candidate_frozen_segments")
    stored_profile.pop("freeze_detection_summary")
    stored_profile["quality_issues"] = [
        {
            "code": "FROZEN_SEGMENTS",
            "severity": "warning",
            "message": "检测到多段连续不变的变量值。",
            "affected_columns": ["control"],
        }
    ]
    stored_profile["recommendations"] = ["冻结段可能代表仪表死值，建议标记或剔除。"]

    enriched = enrich_freeze_diagnostics(stored_profile)

    assert len(enriched["frozen_segments"]) == 9
    assert enriched["candidate_frozen_segments"] == [
        {
            "column": "control",
            "start_index": long_start,
            "end_index": long_start + normal_hold * 5 - 1,
            "length": normal_hold * 5,
        }
    ]
    assert enriched["quality_issues"][0]["message"] == "检测到 1 段候选异常冻结段，需结合工艺记录复核。"


def test_cleaning_and_profile_share_candidate_freeze_semantics() -> None:
    normal_hold = 9
    values = [float(level) for level in range(6) for _ in range(normal_hold)]
    long_start = len(values)
    values.extend([88.0] * (normal_hold * 6))
    values.extend(float(level) for level in range(6, 12) for _ in range(normal_hold))
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        {
            "timestamp": (start + timedelta(seconds=index)).isoformat(),
            "control": str(value),
        }
        for index, value in enumerate(values)
    ]
    result = CleaningPipeline().execute(
        CleaningContext(
            headers=["timestamp", "control"],
            timestamp_column="timestamp",
            timestamps=[start + timedelta(seconds=index) for index in range(len(values))],
            rows=rows,
            inferred_types={"timestamp": "datetime", "control": "float"},
        ),
        CleaningParameters(
            resample_period_seconds=None,
            interpolation="linear",
            max_consecutive_missing=None,
            duplicate_strategy="mean",
            outlier_detector="hampel",
            outlier_strategy="keep",
            hampel_window=5,
            hampel_threshold=3.0,
            z_score_threshold=3.0,
            smoothing="none",
            smoothing_window=5,
        ),
    )
    profile = _profile_for(values)

    assert result.constant_value_segments == profile["frozen_segments"]
    assert result.candidate_frozen_segments == profile["candidate_frozen_segments"]
    assert result.candidate_frozen_segments == classify_candidate_frozen_segments(
        frozen_segments=result.constant_value_segments,
        constant_columns=[],
        row_count=len(values),
    )
    assert len(result.constant_value_segments) > len(result.candidate_frozen_segments)
    assert result.candidate_frozen_segments[0]["start_index"] == long_start
    assert all("候选异常冻结段" in warning for warning in result.warnings)
