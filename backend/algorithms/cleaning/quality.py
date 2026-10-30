"""Deterministic, dependency-light industrial time-series quality diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import isclose, isfinite
from statistics import median
from typing import Any

import numpy as np

MISSING_TOKENS = {"", "na", "n/a", "null", "none", "nan"}


@dataclass(frozen=True)
class QualityProfileResult:
    """JSON-ready profile information calculated from the immutable raw rows."""

    payload: dict[str, Any]


def is_missing(value: str | None) -> bool:
    return value is None or value.strip().lower() in MISSING_TOKENS


def build_quality_profile(
    *,
    dataset_id: str,
    version_id: str,
    headers: Sequence[str],
    rows: Sequence[Mapping[str, str]],
    inferred_types: Mapping[str, str],
    timestamps: Sequence[datetime],
) -> QualityProfileResult:
    """Compute reproducible quality evidence without mutating raw source rows."""

    row_count = len(rows)
    column_count = len(headers)
    missing_counts = {
        column: sum(is_missing(row.get(column)) for row in rows) for column in headers
    }
    missing_rates = {
        column: (missing_counts[column] / row_count if row_count else 0.0) for column in headers
    }
    max_consecutive_missing = {
        column: _max_missing_run([row.get(column) for row in rows]) for column in headers
    }
    numeric_columns = [
        column for column in headers if inferred_types.get(column) in {"float", "integer"}
    ]
    statistics: dict[str, dict[str, float | int | None]] = {}
    anomaly_counts: dict[str, int] = {}
    frozen_segments: list[dict[str, int | str]] = []
    constant_columns: list[str] = []
    for column in numeric_columns:
        values = _numeric_values([row.get(column) for row in rows])
        statistics[column] = _statistics(values)
        anomaly_counts[column] = _iqr_anomaly_count(values)
        segments = _frozen_segments(column, [row.get(column) for row in rows])
        frozen_segments.extend(segments)
        if values and np.isclose(np.ptp(np.asarray(values, dtype=float)), 0.0):
            constant_columns.append(column)

    candidate_frozen_segments = classify_candidate_frozen_segments(
        frozen_segments=frozen_segments,
        constant_columns=constant_columns,
        row_count=row_count,
    )

    intervals = [
        (timestamps[index] - timestamps[index - 1]).total_seconds()
        for index in range(1, len(timestamps))
    ]
    positive_intervals = [value for value in intervals if value > 0]
    sample_period = float(median(positive_intervals)) if positive_intervals else None
    irregular_rate = _irregular_sampling_rate(intervals, sample_period)
    duplicate_count = len(timestamps) - len(set(timestamps))
    histogram = _histogram(positive_intervals)
    total_values = row_count * column_count
    total_missing = sum(missing_counts.values())
    overall_missing_rate = total_missing / total_values if total_values else 0.0
    total_anomalies = sum(anomaly_counts.values())
    numeric_count = sum(
        len(_numeric_values([row.get(column) for row in rows])) for column in numeric_columns
    )
    anomaly_rate = total_anomalies / numeric_count if numeric_count else 0.0
    duplicate_rate = duplicate_count / row_count if row_count else 0.0
    score = _quality_score(
        missing_rate=overall_missing_rate,
        irregular_rate=irregular_rate,
        duplicate_rate=duplicate_rate,
        anomaly_rate=anomaly_rate,
        frozen_segments=candidate_frozen_segments,
    )
    issues = _quality_issues(
        missing_rates=missing_rates,
        duplicate_count=duplicate_count,
        irregular_rate=irregular_rate,
        frozen_segments=candidate_frozen_segments,
        anomaly_counts=anomaly_counts,
    )
    recommendations = _recommendations(
        overall_missing_rate=overall_missing_rate,
        sample_period=sample_period,
        duplicate_count=duplicate_count,
        irregular_rate=irregular_rate,
        frozen_segments=candidate_frozen_segments,
        anomaly_counts=anomaly_counts,
    )
    payload: dict[str, Any] = {
        "dataset_id": dataset_id,
        "version_id": version_id,
        "row_count": row_count,
        "column_count": column_count,
        "total_rows": row_count,
        "total_cols": column_count,
        "missing_rate": _round(overall_missing_rate),
        "missing_rates": {column: _round(value) for column, value in missing_rates.items()},
        "max_consecutive_missing": max_consecutive_missing,
        "anomaly_counts": anomaly_counts,
        "interval_histogram": histogram,
        "duplicate_timestamp_count": duplicate_count,
        "irregular_sampling_rate": _round(irregular_rate),
        "constant_columns": constant_columns,
        "frozen_segments": frozen_segments,
        "candidate_frozen_segments": candidate_frozen_segments,
        "freeze_detection_summary": _freeze_detection_summary(candidate_frozen_segments),
        "recommended_downsample_factor": max(1, int(np.ceil(row_count / 10_000))),
        "quality_issues": issues,
        "time_range_start": min(timestamps).isoformat() if timestamps else None,
        "time_range_end": max(timestamps).isoformat() if timestamps else None,
        "sample_period_seconds": _round(sample_period) if sample_period is not None else None,
        "column_statistics": statistics,
        "quality_score": _round(score),
        "recommendations": recommendations,
        "column_missing_counts": missing_counts,
    }
    return QualityProfileResult(payload=payload)


def classify_candidate_frozen_segments(
    *,
    frozen_segments: Sequence[Mapping[str, int | str]],
    constant_columns: Sequence[str],
    row_count: int,
) -> list[dict[str, int | str]]:
    """Separate regular control holds from candidate abnormal frozen-value runs.

    ``frozen_segments`` intentionally remains a complete audit trail of all constant
    runs.  A regular staircase input naturally has many such runs, so it is not
    sufficient evidence of an instrument fault.  A run becomes a candidate only
    when the entire column is constant, it dominates the observed record, or it is
    a robust upper-tail outlier relative to that column's other constant runs.
    """

    by_column: dict[str, list[dict[str, int | str]]] = {}
    for segment in frozen_segments:
        column = segment.get("column")
        length = segment.get("length")
        start = segment.get("start_index")
        end = segment.get("end_index")
        if (
            not isinstance(column, str)
            or not isinstance(length, int)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or length <= 0
        ):
            continue
        by_column.setdefault(column, []).append(
            {
                "column": column,
                "start_index": start,
                "end_index": end,
                "length": length,
            }
        )

    candidates: list[dict[str, int | str]] = []
    constant_column_set = set(constant_columns)
    for column, segments in by_column.items():
        segments.sort(key=lambda item: int(item["start_index"]))
        if column in constant_column_set:
            candidates.append(max(segments, key=lambda item: int(item["length"])))
            continue

        lengths = np.asarray([int(segment["length"]) for segment in segments], dtype=float)
        dominant_runs = [
            segment
            for segment in segments
            if row_count > 0 and int(segment["length"]) / row_count >= 0.5
        ]
        if dominant_runs:
            candidates.extend(dominant_runs)
            continue
        if len(lengths) < 4:
            continue

        q25, q75 = np.quantile(lengths, [0.25, 0.75])
        typical_hold = float(np.median(lengths))
        robust_upper_fence = float(q75 + 1.5 * (q75 - q25))
        exceptional_hold = max(robust_upper_fence, typical_hold * 2.0)
        candidates.extend(
            segment for segment in segments if int(segment["length"]) > exceptional_hold
        )

    return sorted(
        candidates,
        key=lambda item: (str(item["column"]), int(item["start_index"])),
    )


def enrich_freeze_diagnostics(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Add current freeze semantics when serving a profile stored by an older build."""

    enriched = dict(payload)
    candidates = classify_candidate_frozen_segments(
        frozen_segments=_as_segment_sequence(enriched.get("frozen_segments")),
        constant_columns=_as_string_sequence(enriched.get("constant_columns")),
        row_count=_as_non_negative_int(enriched.get("row_count", enriched.get("total_rows", 0))),
    )
    enriched["candidate_frozen_segments"] = candidates
    enriched["freeze_detection_summary"] = _freeze_detection_summary(candidates)

    existing_issues = enriched.get("quality_issues")
    issues = [
        issue
        for issue in existing_issues
        if isinstance(issue, Mapping) and issue.get("code") != "FROZEN_SEGMENTS"
    ] if isinstance(existing_issues, Sequence) else []
    if candidates:
        issues.append(_frozen_segment_issue(candidates))
    enriched["quality_issues"] = issues

    existing_recommendations = enriched.get("recommendations")
    recommendations = [
        recommendation
        for recommendation in existing_recommendations
        if isinstance(recommendation, str)
        and "冻结段可能代表仪表死值" not in recommendation
        and "候选异常冻结段" not in recommendation
    ] if isinstance(existing_recommendations, Sequence) else []
    if candidates:
        recommendations.append("检测到候选异常冻结段，建议结合工艺操作记录复核后再处理。")
    elif not recommendations:
        recommendations.append("数据质量良好；确认输入和输出列映射后可进入后续分析。")
    enriched["recommendations"] = recommendations

    numeric_count = sum(
        _as_non_negative_int(statistics.get("count"))
        for statistics in _as_mapping_values(enriched.get("column_statistics"))
        if isinstance(statistics, Mapping)
    )
    anomaly_rate = sum(
        _as_non_negative_int(value) for value in _as_mapping_values(enriched.get("anomaly_counts"))
    ) / numeric_count if numeric_count else 0.0
    enriched["quality_score"] = _round(
        _quality_score(
            missing_rate=_as_float(enriched.get("missing_rate")),
            irregular_rate=_as_float(enriched.get("irregular_sampling_rate")),
            duplicate_rate=(
                _as_non_negative_int(enriched.get("duplicate_timestamp_count"))
                / _as_non_negative_int(enriched.get("row_count", enriched.get("total_rows", 0)))
                if _as_non_negative_int(enriched.get("row_count", enriched.get("total_rows", 0)))
                else 0.0
            ),
            anomaly_rate=anomaly_rate,
            frozen_segments=candidates,
        )
    )
    return enriched


def _numeric_values(values: Sequence[str | None]) -> list[float]:
    result: list[float] = []
    for value in values:
        if is_missing(value):
            continue
        try:
            parsed = float(value.strip()) if value is not None else float("nan")
        except ValueError:
            continue
        if isfinite(parsed):
            result.append(parsed)
    return result


def _statistics(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "mean": None,
            "std": None,
            "min": None,
            "max": None,
            "q25": None,
            "q50": None,
            "q75": None,
        }
    vector = np.asarray(values, dtype=float)
    return {
        "count": int(vector.size),
        "mean": _round(float(np.mean(vector))),
        "std": _round(float(np.std(vector, ddof=1))) if vector.size > 1 else 0.0,
        "min": _round(float(np.min(vector))),
        "max": _round(float(np.max(vector))),
        "q25": _round(float(np.quantile(vector, 0.25))),
        "q50": _round(float(np.quantile(vector, 0.50))),
        "q75": _round(float(np.quantile(vector, 0.75))),
    }


def _iqr_anomaly_count(values: Sequence[float]) -> int:
    if len(values) < 4:
        return 0
    vector = np.asarray(values, dtype=float)
    q25, q75 = np.quantile(vector, [0.25, 0.75])
    iqr = q75 - q25
    if np.isclose(iqr, 0.0):
        return 0
    return int(np.sum((vector < q25 - 1.5 * iqr) | (vector > q75 + 1.5 * iqr)))


def _max_missing_run(values: Sequence[str | None]) -> int:
    longest = 0
    current = 0
    for value in values:
        if is_missing(value):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _frozen_segments(column: str, values: Sequence[str | None]) -> list[dict[str, int | str]]:
    minimum_length = 5
    segments: list[dict[str, int | str]] = []
    start: int | None = None
    previous: float | None = None
    for index, raw_value in enumerate(values):
        if is_missing(raw_value):
            _append_frozen_segment(segments, column, start, index - 1, minimum_length)
            start, previous = None, None
            continue
        try:
            value = float(raw_value.strip()) if raw_value is not None else float("nan")
        except ValueError:
            _append_frozen_segment(segments, column, start, index - 1, minimum_length)
            start, previous = None, None
            continue
        if not isfinite(value):
            _append_frozen_segment(segments, column, start, index - 1, minimum_length)
            start, previous = None, None
        elif previous is not None and isclose(value, previous, rel_tol=1e-9, abs_tol=1e-12):
            if start is None:
                start = index - 1
            previous = value
        else:
            _append_frozen_segment(segments, column, start, index - 1, minimum_length)
            start, previous = None, value
    _append_frozen_segment(segments, column, start, len(values) - 1, minimum_length)
    return segments


def _append_frozen_segment(
    segments: list[dict[str, int | str]],
    column: str,
    start: int | None,
    end: int,
    minimum_length: int,
) -> None:
    if start is None or end - start + 1 < minimum_length:
        return
    segments.append(
        {
            "column": column,
            "start_index": start,
            "end_index": end,
            "length": end - start + 1,
        }
    )


def _irregular_sampling_rate(intervals: Sequence[float], sample_period: float | None) -> float:
    if not intervals or sample_period is None:
        return 0.0
    tolerance = max(abs(sample_period) * 0.05, 1e-6)
    irregular = sum(
        interval <= 0 or abs(interval - sample_period) > tolerance for interval in intervals
    )
    return irregular / len(intervals)


def _histogram(intervals: Sequence[float]) -> list[dict[str, float | int]]:
    if not intervals:
        return []
    minimum = min(intervals)
    maximum = max(intervals)
    if isclose(minimum, maximum):
        return [{"bin": round(minimum, 8), "count": len(intervals)}]
    bin_count = min(12, max(2, int(np.sqrt(len(intervals)))))
    counts, edges = np.histogram(np.asarray(intervals, dtype=float), bins=bin_count)
    return [
        {
            "bin": round(float((edges[index] + edges[index + 1]) / 2), 8),
            "count": int(count),
        }
        for index, count in enumerate(counts)
    ]


def _quality_score(
    *,
    missing_rate: float,
    irregular_rate: float,
    duplicate_rate: float,
    anomaly_rate: float,
    frozen_segments: Sequence[Mapping[str, int | str]],
) -> float:
    penalty = min(45.0, missing_rate * 200.0)
    penalty += min(20.0, irregular_rate * 30.0)
    penalty += min(15.0, duplicate_rate * 100.0)
    penalty += min(10.0, anomaly_rate * 100.0)
    penalty += min(10.0, len(frozen_segments) * 2.0)
    return max(0.0, 100.0 - penalty)


def _quality_issues(
    *,
    missing_rates: Mapping[str, float],
    duplicate_count: int,
    irregular_rate: float,
    frozen_segments: Sequence[Mapping[str, int | str]],
    anomaly_counts: Mapping[str, int],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    missing_columns = [column for column, rate in missing_rates.items() if rate > 0]
    if missing_columns:
        issues.append(
            {
                "code": "MISSING_VALUES",
                "severity": "warning",
                "message": "检测到缺失值，需要在建模前处理。",
                "affected_columns": missing_columns,
            }
        )
    if duplicate_count:
        issues.append(
            {
                "code": "DUPLICATE_TIMESTAMPS",
                "severity": "warning",
                "message": f"检测到 {duplicate_count} 个重复时间戳。",
                "affected_columns": [],
            }
        )
    if irregular_rate > 0.01:
        issues.append(
            {
                "code": "IRREGULAR_SAMPLING",
                "severity": "warning",
                "message": "采样间隔存在超过 5% 的偏离。",
                "affected_columns": [],
            }
        )
    if frozen_segments:
        issues.append(_frozen_segment_issue(frozen_segments))
    anomaly_columns = [column for column, count in anomaly_counts.items() if count]
    if anomaly_columns:
        issues.append(
            {
                "code": "IQR_ANOMALIES",
                "severity": "info",
                "message": "IQR 规则检测到候选异常点。",
                "affected_columns": anomaly_columns,
            }
        )
    return issues


def _recommendations(
    *,
    overall_missing_rate: float,
    sample_period: float | None,
    duplicate_count: int,
    irregular_rate: float,
    frozen_segments: Sequence[Mapping[str, int | str]],
    anomaly_counts: Mapping[str, int],
) -> list[str]:
    recommendations: list[str] = []
    if overall_missing_rate > 0:
        recommendations.append(
            f"检测到 {overall_missing_rate:.1%} 缺失，建议在清洗阶段选择插值策略。"
        )
    if sample_period is not None and irregular_rate > 0.01:
        recommendations.append(f"建议按 {sample_period:g}s 固定周期重采样后再进行系统辨识。")
    if duplicate_count:
        recommendations.append("请确认重复时间戳的保留规则，避免同一时刻观测重复进入模型。")
    if frozen_segments:
        recommendations.append("检测到候选异常冻结段，建议结合工艺操作记录复核后再处理。")
    if any(anomaly_counts.values()):
        recommendations.append("候选异常点可在清洗阶段使用 Hampel 或 IQR 方法复核。")
    if not recommendations:
        recommendations.append("数据质量良好；确认输入和输出列映射后可进入后续分析。")
    return recommendations


def _round(value: float | None) -> float | None:
    return round(value, 8) if value is not None else None


def _freeze_detection_summary(
    frozen_segments: Sequence[Mapping[str, int | str]],
) -> dict[str, Any]:
    longest = (
        max(
            frozen_segments,
            key=lambda item: (int(item["length"]), -int(item["start_index"])),
        )
        if frozen_segments
        else None
    )
    return {
        "candidate_count": len(frozen_segments),
        "affected_column_count": len({str(item["column"]) for item in frozen_segments}),
        "longest_segment": dict(longest) if longest is not None else None,
    }


def _frozen_segment_issue(
    frozen_segments: Sequence[Mapping[str, int | str]],
) -> dict[str, Any]:
    return {
        "code": "FROZEN_SEGMENTS",
        "severity": "warning",
        "message": f"检测到 {len(frozen_segments)} 段候选异常冻结段，需结合工艺记录复核。",
        "affected_columns": sorted({str(item["column"]) for item in frozen_segments}),
    }


def _as_segment_sequence(value: object) -> list[Mapping[str, int | str]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _as_string_sequence(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [item for item in value if isinstance(item, str)]


def _as_mapping_values(value: object) -> list[Mapping[str, object] | int | float]:
    if not isinstance(value, Mapping):
        return []
    return [item for item in value.values() if isinstance(item, Mapping | int | float)]


def _as_non_negative_int(value: object) -> int:
    if isinstance(value, Mapping):
        value = value.get("count")
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return max(0, int(value))
    return 0


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0
