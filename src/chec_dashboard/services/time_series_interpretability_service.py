from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from chec_dashboard.services.impact_metrics import metric_keys, normalize_metric_key


METRICS = metric_keys()


@dataclass(frozen=True)
class CriticalityThresholds:
    high_robust_z: float = 3.0
    low_robust_z: float = -2.5
    delta_robust_z: float = 3.0
    high_percentile: float = 0.95
    low_percentile: float = 0.05
    top_contributor_pct: float = 0.10
    sustained_percentile: float = 0.80
    sustained_min_days: int = 3
    max_points: int = 5


STRUCTURAL_NON_WARNING_FLAGS = {
    "missing_dates",
    "short_window",
    "all_zero_window",
    "empty_time_series",
}


def _as_float(value: Any, default: float = 0.0) -> float:
    coerced = pd.to_numeric(value, errors="coerce")
    if pd.isna(coerced):
        return default
    return float(coerced)


def _as_int(value: Any, default: int = 0) -> int:
    coerced = pd.to_numeric(value, errors="coerce")
    if pd.isna(coerced):
        return default
    return int(coerced)


def _round(value: Any, digits: int = 4) -> float:
    return round(_as_float(value), digits)


def _date_text(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.date().isoformat()


def _metric_key(metric: str) -> str:
    return metric.lower()


def _user_facing_flags(flags: list[str]) -> list[str]:
    return sorted({flag for flag in flags if flag not in STRUCTURAL_NON_WARNING_FLAGS})


def _selected_metric_keys(metric_key: str | None) -> tuple[str, ...]:
    return (normalize_metric_key(metric_key),)


def _first_existing_column(frame: pd.DataFrame, candidates: list[str]) -> str | None:
    for column in candidates:
        if column in frame.columns:
            return column
    return None


def _numeric_series(frame: pd.DataFrame, candidates: list[str]) -> pd.Series:
    column = _first_existing_column(frame, candidates)
    if column is None or frame.empty:
        return pd.Series([0.0] * len(frame), index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def normalize_daily_frame(
    daily_data: pd.DataFrame | list[dict[str, Any]],
    *,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
) -> pd.DataFrame:
    frame = pd.DataFrame(daily_data).copy()
    if "metrics" in frame.columns:
        metric_values = pd.json_normalize(frame["metrics"]).reindex(frame.index)
        for metric in METRICS:
            if metric not in frame.columns and metric in metric_values.columns:
                frame[metric] = metric_values[metric]
    if frame.empty:
        if start_date is None or end_date is None:
            return pd.DataFrame(
                columns=[
                    "fecha_dia",
                    *METRICS,
                    "event_count",
                    "duration_raw_total",
                    "users_affected_total",
                ]
            )
        date_index = pd.date_range(start=start_date, end=end_date, freq="D")
        frame = pd.DataFrame({"fecha_dia": date_index})

    if "fecha_dia" not in frame.columns:
        raise ValueError("daily_data must include fecha_dia")

    frame["fecha_dia"] = pd.to_datetime(frame["fecha_dia"], errors="coerce")
    frame = frame.dropna(subset=["fecha_dia"]).copy()
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "fecha_dia",
                *METRICS,
                "event_count",
                "duration_raw_total",
                "users_affected_total",
            ]
        )

    for metric in METRICS:
        if metric not in frame.columns:
            frame[metric] = 0.0
        frame[metric] = pd.to_numeric(frame[metric], errors="coerce").fillna(0.0)

    aggregate_columns = {
        "event_count": 0,
        "duration_raw_total": 0.0,
        "users_affected_total": 0.0,
    }
    if "event_count" not in frame.columns and "EVENT_COUNT" in frame.columns:
        frame["event_count"] = frame["EVENT_COUNT"]
    if "duration_raw_total" not in frame.columns and "DURATION_RAW" in frame.columns:
        frame["duration_raw_total"] = frame["DURATION_RAW"]
    if "users_affected_total" not in frame.columns and "USERS" in frame.columns:
        frame["users_affected_total"] = frame["USERS"]
    for column, default in aggregate_columns.items():
        if column not in frame.columns:
            frame[column] = default
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(default)

    grouped = (
        frame.groupby("fecha_dia", as_index=False)
        .agg(
            **{metric: (metric, "sum") for metric in METRICS},
            event_count=("event_count", "sum"),
            duration_raw_total=("duration_raw_total", "sum"),
            users_affected_total=("users_affected_total", "sum"),
        )
        .sort_values("fecha_dia")
    )

    first_date = pd.to_datetime(start_date).date() if start_date is not None else grouped["fecha_dia"].min().date()
    last_date = pd.to_datetime(end_date).date() if end_date is not None else grouped["fecha_dia"].max().date()
    if first_date > last_date:
        first_date, last_date = last_date, first_date
    date_index = pd.date_range(start=first_date, end=last_date, freq="D")
    normalized = (
        grouped.set_index("fecha_dia")
        .reindex(date_index, fill_value=0.0)
        .reset_index()
        .rename(columns={"index": "fecha_dia"})
    )
    return normalized


def _robust_z(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    if values.empty:
        return pd.Series(dtype="float64")
    median = float(values.median())
    mad = float((values - median).abs().median())
    scale = 1.4826 * mad
    if scale <= 0:
        scale = float(values.std(ddof=0))
    if scale <= 0:
        return pd.Series([0.0] * len(values), index=values.index, dtype="float64")
    return (values - median) / scale


def compute_time_series_features(daily_data: pd.DataFrame) -> pd.DataFrame:
    features = normalize_daily_frame(daily_data)
    if features.empty:
        return features

    for metric in METRICS:
        key = _metric_key(metric)
        total = float(features[metric].sum())
        features[f"{key}_rolling_median_7d"] = features[metric].rolling(7, min_periods=3).median()
        features[f"{key}_rolling_median_30d"] = features[metric].rolling(30, min_periods=7).median()
        features[f"{key}_robust_z"] = _robust_z(features[metric])
        features[f"{key}_delta_1d"] = features[metric].diff().fillna(0.0)
        previous = features[metric].shift(1)
        features[f"{key}_delta_pct"] = (
            features[f"{key}_delta_1d"] / previous.where(previous.abs() > 1e-9)
        ).replace([float("inf"), float("-inf")], pd.NA)
        features[f"{key}_delta_robust_z"] = _robust_z(features[f"{key}_delta_1d"])
        features[f"{key}_contribution_pct"] = features[metric] / total if total > 0 else 0.0
        features[f"rolling_7d_{key}_sum"] = features[metric].rolling(7, min_periods=1).sum()

    return features


def compute_data_quality_flags(daily_data: pd.DataFrame, event_frame: pd.DataFrame | None = None) -> list[str]:
    flags: list[str] = []
    frame = pd.DataFrame(daily_data).copy()
    if frame.empty:
        return ["empty_time_series"]
    dates = pd.to_datetime(frame.get("fecha_dia"), errors="coerce")
    if dates.isna().any():
        flags.append("invalid_dates")
    valid_dates = dates.dropna()
    if not valid_dates.empty:
        expected_days = len(pd.date_range(valid_dates.min().date(), valid_dates.max().date(), freq="D"))
        if expected_days > valid_dates.dt.floor("D").nunique():
            flags.append("missing_dates")
    if valid_dates.dt.floor("D").duplicated().any():
        flags.append("duplicated_dates")
    for metric in METRICS:
        if metric in frame.columns and (pd.to_numeric(frame[metric], errors="coerce").fillna(0.0) < 0).any():
            flags.append(f"negative_{metric.lower()}_values")
    if len(frame) < 7:
        flags.append("short_window")
    if all(metric in frame.columns for metric in METRICS):
        total = sum(pd.to_numeric(frame[metric], errors="coerce").fillna(0.0).sum() for metric in METRICS)
        if total == 0:
            flags.append("all_zero_window")
    if event_frame is not None and event_frame.empty and "all_zero_window" not in flags:
        flags.append("missing_event_attribution")
    return sorted(set(flags))


def _reason(
    reason_type: str,
    metric: str,
    score: float,
    *,
    value: Any = None,
    baseline: Any = None,
    threshold: Any = None,
    detail: str,
) -> dict[str, Any]:
    return {
        "reason_type": reason_type,
        "metric": metric,
        "score": round(max(float(score), 0.0), 4),
        "value": None if value is None else _round(value),
        "baseline": None if baseline is None else _round(baseline),
        "threshold": None if threshold is None else _round(threshold),
        "detail": detail,
    }


def _selection_reason_text(reasons: list[dict[str, Any]]) -> str:
    details = [
        str(reason.get("detail")).strip()
        for reason in sorted(reasons, key=lambda item: float(item.get("score") or 0), reverse=True)
        if str(reason.get("detail") or "").strip()
    ]
    if details:
        return " ".join(details[:2])
    reason_types = [
        str(reason.get("reason_type")).strip()
        for reason in reasons
        if str(reason.get("reason_type") or "").strip()
    ]
    if reason_types:
        return "Seleccionado por tipos de criticidad calculados: " + ", ".join(reason_types[:4]) + "."
    return "Seleccionado por el detector de puntos de interes del periodo analizado."


def detect_point_reasons(
    feature_frame: pd.DataFrame,
    *,
    metric_key: str = "UITI",
    thresholds: CriticalityThresholds | None = None,
) -> dict[str, list[dict[str, Any]]]:
    thresholds = thresholds or CriticalityThresholds()
    if feature_frame.empty:
        return {}
    frame = feature_frame.copy()
    reasons_by_date: dict[str, list[dict[str, Any]]] = {}

    for metric in _selected_metric_keys(metric_key):
        key = _metric_key(metric)
        values = pd.to_numeric(frame[metric], errors="coerce").fillna(0.0)
        if values.sum() <= 0:
            continue
        high_value = float(values.quantile(thresholds.high_percentile))
        low_value = float(values.quantile(thresholds.low_percentile))
        baseline = float(values.median())
        nonzero_days = max(int((values > 0).sum()), 1)
        dynamic_top_contributor_pct = max(
            thresholds.top_contributor_pct,
            min(0.5, 1.5 / nonzero_days),
        )

        for index, row in frame.iterrows():
            date_key = _date_text(row["fecha_dia"])
            metric_value = _as_float(row[metric])
            robust_z = _as_float(row.get(f"{key}_robust_z"))
            contribution = _as_float(row.get(f"{key}_contribution_pct"))
            delta = _as_float(row.get(f"{key}_delta_1d"))
            delta_z = _as_float(row.get(f"{key}_delta_robust_z"))
            point_reasons = reasons_by_date.setdefault(date_key, [])

            percentile_high_signal = len(values) >= 7 and metric_value >= high_value > 0 and robust_z >= 1.0
            if metric_value > 0 and (robust_z >= thresholds.high_robust_z or percentile_high_signal):
                score = max(abs(robust_z) / max(thresholds.high_robust_z, 1.0), contribution)
                point_reasons.append(
                    _reason(
                        f"{key}_high_outlier",
                        metric,
                        min(score, 2.0),
                        value=metric_value,
                        baseline=baseline,
                        threshold=thresholds.high_robust_z,
                        detail=f"{metric} esta por encima de la linea base robusta de la ventana.",
                    )
                )

            if baseline > 0 and metric_value <= low_value and robust_z <= thresholds.low_robust_z:
                point_reasons.append(
                    _reason(
                        f"{key}_low_outlier",
                        metric,
                        abs(robust_z) / max(abs(thresholds.low_robust_z), 1.0),
                        value=metric_value,
                        baseline=baseline,
                        threshold=thresholds.low_robust_z,
                        detail=f"{metric} esta inusualmente bajo frente a la ventana seleccionada.",
                    )
                )

            if delta > 0 and (
                delta_z >= thresholds.delta_robust_z
                or (baseline > 0 and delta >= baseline and metric_value >= high_value)
            ):
                point_reasons.append(
                    _reason(
                        f"sharp_{key}_increase",
                        metric,
                        max(delta_z / max(thresholds.delta_robust_z, 1.0), contribution),
                        value=delta,
                        baseline=baseline,
                        threshold=thresholds.delta_robust_z,
                        detail=f"{metric} sube bruscamente frente al dia anterior.",
                    )
                )

            if delta < 0 and (
                delta_z <= -thresholds.delta_robust_z
                or (baseline > 0 and abs(delta) >= baseline and index > 0)
            ):
                point_reasons.append(
                    _reason(
                        f"sharp_{key}_decrease",
                        metric,
                        abs(delta_z) / max(thresholds.delta_robust_z, 1.0),
                        value=delta,
                        baseline=baseline,
                        threshold=-thresholds.delta_robust_z,
                        detail=f"{metric} cae bruscamente frente al dia anterior.",
                    )
                )

            if contribution >= dynamic_top_contributor_pct and metric_value > 0:
                point_reasons.append(
                    _reason(
                        f"top_{key}_contributor",
                        metric,
                        contribution / max(dynamic_top_contributor_pct, 1e-9),
                        value=metric_value,
                        baseline=baseline,
                        threshold=dynamic_top_contributor_pct,
                        detail=f"El dia aporta una fraccion alta del {metric} total de la ventana.",
                    )
                )

        local_max = (
            values[(values.shift(1) < values) & (values.shift(-1) < values) & (values > high_value)]
            if len(values) >= 7
            else pd.Series(dtype="float64")
        )
        for index, metric_value in local_max.items():
            date_key = _date_text(frame.loc[index, "fecha_dia"])
            reasons_by_date.setdefault(date_key, []).append(
                _reason(
                    f"local_{key}_peak",
                    metric,
                    _as_float(frame.loc[index, f"{key}_contribution_pct"]),
                    value=metric_value,
                    baseline=baseline,
                    threshold=high_value,
                    detail=f"{metric} forma un pico local dentro de la serie.",
                )
            )

    return {
        date_key: [reason for reason in reasons if reason["score"] > 0]
        for date_key, reasons in reasons_by_date.items()
        if reasons
    }


def detect_critical_periods(
    feature_frame: pd.DataFrame,
    *,
    metric_key: str = "UITI",
    thresholds: CriticalityThresholds | None = None,
) -> list[dict[str, Any]]:
    thresholds = thresholds or CriticalityThresholds()
    periods: list[dict[str, Any]] = []
    if feature_frame.empty:
        return periods

    for metric in _selected_metric_keys(metric_key):
        values = pd.to_numeric(feature_frame[metric], errors="coerce").fillna(0.0)
        if values.sum() <= 0:
            continue
        baseline = float(values.median())
        percentile_cutoff = float(values.quantile(thresholds.sustained_percentile))
        baseline_cutoff = max(baseline * 1.5, baseline + 0.01)
        cutoff = min(percentile_cutoff, baseline_cutoff) if percentile_cutoff > baseline else baseline_cutoff
        active = values > cutoff
        start_index: int | None = None
        for index, is_active in enumerate(active.tolist() + [False]):
            if is_active and start_index is None:
                start_index = index
            if not is_active and start_index is not None:
                end_index = index - 1
                days = end_index - start_index + 1
                if days >= thresholds.sustained_min_days:
                    period_values = values.iloc[start_index : end_index + 1]
                    start_date = _date_text(feature_frame.iloc[start_index]["fecha_dia"])
                    end_date = _date_text(feature_frame.iloc[end_index]["fecha_dia"])
                    metric_key = _metric_key(metric)
                    periods.append(
                        {
                            "start_date": start_date,
                            "end_date": end_date,
                            "metric": metric,
                            "period_type": f"sustained_{metric_key}_elevated_period",
                            "score": _round(period_values.sum() / max(values.sum(), 1e-9)),
                            "days": int(days),
                            "summary": (
                                f"{metric} permanecio elevado durante {days} dias "
                                f"entre {start_date} y {end_date}."
                            ),
                        }
                    )
                start_index = None
    return sorted(periods, key=lambda item: item["score"], reverse=True)[:5]


def rank_and_merge_critical_points(
    feature_frame: pd.DataFrame,
    reasons_by_date: dict[str, list[dict[str, Any]]],
    *,
    max_points: int,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    if feature_frame.empty:
        return points

    indexed = feature_frame.copy()
    indexed["fecha_text"] = indexed["fecha_dia"].map(_date_text)
    indexed = indexed.set_index("fecha_text")
    for date_key, reasons in reasons_by_date.items():
        if date_key not in indexed.index or not reasons:
            continue
        row = indexed.loc[date_key]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        reason_score = sum(float(reason["score"]) for reason in reasons)
        contribution_score = max(_as_float(row.get(f"{_metric_key(metric)}_contribution_pct")) for metric in METRICS)
        criticality_score = min(reason_score + contribution_score, 10.0)
        points.append(
            {
                "fecha_dia": date_key,
                "criticality_score": round(criticality_score, 4),
                "criticality_types": sorted({str(reason["reason_type"]) for reason in reasons}),
                "selection_reason": _selection_reason_text(reasons),
                "reasons": sorted(reasons, key=lambda reason: reason["score"], reverse=True),
                "metrics": _row_metrics(row),
                "daily_aggregates": {
                    "event_count": _as_int(row.get("event_count")),
                    "duration_raw_total": _round(row.get("duration_raw_total"), 2),
                    "users_affected_total": _round(row.get("users_affected_total"), 2),
                },
            }
        )

    points = sorted(points, key=lambda item: (item["criticality_score"], item["fecha_dia"]), reverse=True)
    for rank, point in enumerate(points[:max_points], start=1):
        point["rank"] = rank
    return points[:max_points]


def _row_metrics(row: pd.Series) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    columns: list[str] = []
    for metric in METRICS:
        key = _metric_key(metric)
        columns.extend(
            [
                metric,
                f"{key}_robust_z",
                f"{key}_delta_1d",
                f"{key}_delta_pct",
                f"{key}_contribution_pct",
                f"rolling_7d_{key}_sum",
            ]
        )
    for column in columns:
        value = row.get(column)
        metrics[column] = None if value is None or pd.isna(value) else _round(value)
    return metrics


def _date_filtered_frame(frame: pd.DataFrame | None, fecha_dia: str) -> pd.DataFrame:
    if frame is None or frame.empty or "fecha_dia" not in frame.columns:
        return pd.DataFrame()
    work = frame.copy()
    work["fecha_text"] = pd.to_datetime(work["fecha_dia"], errors="coerce").dt.date.astype(str)
    return work[work["fecha_text"] == fecha_dia].copy()


def _attribution_items(
    frame: pd.DataFrame,
    group_candidates: list[str],
    *,
    limit: int = 5,
    daily_total: float = 0.0,
) -> list[dict[str, Any]]:
    group_column = _first_existing_column(frame, group_candidates)
    if group_column is None or frame.empty:
        return []
    work = pd.DataFrame(
        {
            "label": frame[group_column].fillna("Sin dato").astype(str).str.strip().replace("", "Sin dato"),
            "event_count": _numeric_series(frame, ["event_count"]),
            "uiti_total": _numeric_series(frame, ["uiti_total", "UITI"]),
            "uiti_vano_total": _numeric_series(frame, ["uiti_vano_total", "UITI_VANO"]),
            "duration_raw_total": _numeric_series(frame, ["duration_raw_total", "DURATION_RAW", "duration_raw", "duracion_h"]),
            "users_affected_total": _numeric_series(frame, ["users_affected_total", "USERS", "users_affected", "cnt_usus"]),
        }
    )
    if work["event_count"].sum() == 0:
        work["event_count"] = 1
    grouped = (
        work.groupby("label", dropna=False)
        .agg(
            event_count=("event_count", "sum"),
            uiti_total=("uiti_total", "sum"),
            uiti_vano_total=("uiti_vano_total", "sum"),
            duration_raw_total=("duration_raw_total", "sum"),
            users_affected_total=("users_affected_total", "sum"),
        )
        .reset_index()
    )
    grouped["impact_score"] = grouped["uiti_total"]
    grouped = grouped.sort_values(
        ["impact_score", "event_count", "duration_raw_total"],
        ascending=[False, False, False],
    ).head(limit)
    return [
        {
            "label": str(row["label"]),
            "event_count": _as_int(row["event_count"]),
            "metric_totals": {
                "UITI": _round(row["uiti_total"]),
                "UITI_VANO": _round(row["uiti_vano_total"]),
                "EVENT_COUNT": _round(row["event_count"]),
                "USERS": _round(row["users_affected_total"], 2),
                "DURATION_RAW": _round(row["duration_raw_total"], 2),
            },
            "impact_total": _round(row["uiti_total"]),
            "duration_raw_total": _round(row["duration_raw_total"], 2),
            "users_affected_total": _round(row["users_affected_total"], 2),
            "contribution_pct": (
                _round(row["uiti_total"] / daily_total)
                if daily_total > 0
                else None
            ),
        }
        for _, row in grouped.iterrows()
    ]


def _event_text(row: pd.Series, candidates: list[str]) -> str | None:
    column = _first_existing_column(pd.DataFrame(columns=row.index), candidates)
    value = row.get(column) if column else None
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    return str(value)


def _top_events(frame: pd.DataFrame, *, limit: int = 5) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    work = frame.copy()
    work["uiti"] = _numeric_series(work, ["UITI", "uiti_total"])
    work["uiti_vano"] = _numeric_series(work, ["UITI_VANO", "uiti_vano_total"])
    work["duration_raw"] = _numeric_series(work, ["DURATION_RAW", "duration_raw", "duration_raw_total", "duracion_h"])
    work["users_affected"] = _numeric_series(work, ["USERS", "users_affected", "users_affected_total", "cnt_usus"])
    work["impact_score"] = work["uiti_vano"].where(work["uiti_vano"] > 0, work["uiti"])
    work = work.sort_values(
        ["impact_score", "duration_raw", "users_affected"],
        ascending=[False, False, False],
    ).head(limit)
    events = []
    for _, row in work.iterrows():
        event_id = _event_text(row, ["event_id", "evento"])
        events.append(
            {
                "event_id": event_id,
                "evento": _event_text(row, ["evento", "display_label"]),
                "inicio_ts": _event_text(row, ["inicio_ts", "inicio"]),
                "fin_ts": _event_text(row, ["fin_ts", "fin"]),
                "causa": _event_text(row, ["causa"]),
                "event_family": _event_text(row, ["event_family", "tipo_equi_ope"]),
                "circuito": _event_text(row, ["circuito", "cto_equi_ope", "FPARENT"]),
                "municipio": _event_text(row, ["municipio", "MUN"]),
                "equipo_ope": _event_text(row, ["equipo_ope", "CODE"]),
                "tipo_equi_ope": _event_text(row, ["tipo_equi_ope"]),
                "tipo_elemento": _event_text(row, ["tipo_elemento"]),
                "duration_raw": _round(row["duration_raw"], 2),
                "uiti": _round(row["uiti"]),
                "uiti_vano": _round(row["uiti_vano"]),
                "users_affected": _round(row["users_affected"], 2),
            }
        )
    return events


def _external_signals(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}
    signals: dict[str, Any] = {}
    for column in frame.columns:
        if column in {"fecha_dia", "fecha_text"}:
            continue
        series = pd.to_numeric(frame[column], errors="coerce")
        if series.notna().any():
            signals[column] = _round(series.fillna(0.0).sum(), 2)
    return signals


def enrich_critical_points_with_attribution(
    critical_points: list[dict[str, Any]],
    *,
    attribution_frame: pd.DataFrame | None = None,
    event_frame: pd.DataFrame | None = None,
    environment_frame: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for point in critical_points:
        fecha_dia = str(point["fecha_dia"])
        attribution = _date_filtered_frame(attribution_frame, fecha_dia)
        events = _date_filtered_frame(event_frame, fecha_dia)
        environment = _date_filtered_frame(environment_frame, fecha_dia)
        source = attribution if not attribution.empty else events
        metrics = point.get("metrics") or {}
        daily_total = _as_float(metrics.get("UITI"))

        data_quality_flags: list[str] = []
        if source.empty and (point.get("daily_aggregates") or {}).get("event_count", 0):
            data_quality_flags.append("missing_event_attribution")
        if not events.empty:
            event_metric_total = _numeric_series(events, ["UITI_VANO", "UITI", "uiti_total"]).sum()
        else:
            event_metric_total = 0.0
        if not events.empty and event_metric_total == 0:
            data_quality_flags.append("event_detail_without_metric_contribution")

        confidence = "high"
        if data_quality_flags:
            confidence = "low"
        elif source.empty:
            confidence = "medium"

        enriched.append(
            {
                **point,
                "top_causes": _attribution_items(source, ["causa"], daily_total=daily_total),
                "top_event_families": _attribution_items(
                    source,
                    ["event_family", "tipo_equi_ope"],
                    daily_total=daily_total,
                ),
                "top_equipment": _attribution_items(
                    source,
                    ["equipo_ope", "tipo_equi_ope", "tipo_elemento", "CODE"],
                    daily_total=daily_total,
                ),
                "top_circuits": _attribution_items(
                    source,
                    ["circuito", "cto_equi_ope", "FPARENT"],
                    daily_total=daily_total,
                ),
                "top_events": _top_events(events),
                "external_signals": _external_signals(environment),
                "data_quality_flags": data_quality_flags,
                "confidence": confidence,
            }
        )
    return enriched


def deterministic_insight_text(payload: dict[str, Any]) -> str:
    points = payload.get("critical_points") or []
    start_date = payload.get("start_date") or "N/D"
    end_date = payload.get("end_date") or "N/D"
    if not points:
        return (
            f"No se detectaron puntos criticos entre {start_date} y {end_date}. "
            "La serie no muestra picos, aportes concentrados ni cambios bruscos bajo los umbrales actuales."
        )

    first = points[0]
    metrics = first.get("metrics") or {}
    aggregates = first.get("daily_aggregates") or {}
    reason_labels = ", ".join(first.get("criticality_types") or [])
    dominant = "sin agrupacion dominante disponible"
    for group_key in ("top_causes", "top_event_families", "top_equipment", "top_circuits"):
        groups = first.get(group_key) or []
        if groups:
            dominant = f"{groups[0].get('label')} ({group_key})"
            break
    return (
        f"Se detectaron {len(points)} eventos de interes entre {start_date} y {end_date}. "
        f"El evento de mayor criticidad fue {first.get('fecha_dia')}, con UITI={_round(metrics.get('UITI'))} "
        f"y UITI_VANO={_round(metrics.get('UITI_VANO'))}. Se selecciono por: "
        f"{first.get('selection_reason') or reason_labels}. "
        f"En ese dia se registraron {aggregates.get('event_count', 0)} eventos, "
        f"{aggregates.get('duration_raw_total', 0)} unidades de duracion fuente acumulada y "
        f"{aggregates.get('users_affected_total', 0)} usuarios afectados. "
        f"La principal agrupacion observada fue {dominant}. "
        "Los intervalos sin evento registrado no se interpretan como anomalias por si mismos."
    )


def _daily_indicator_rows(frame: pd.DataFrame, *, limit: int = 400) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    work = normalize_daily_frame(frame)
    for _, row in work.head(limit).iterrows():
        rows.append(
            {
                "fecha_dia": _date_text(row.get("fecha_dia")),
                "UITI": _round(row.get("UITI")),
                "UITI_VANO": _round(row.get("UITI_VANO")),
                "event_count": _as_int(row.get("event_count")),
                "DURATION_RAW": _round(row.get("DURATION_RAW"), 2),
                "USERS": _round(row.get("USERS"), 2),
            }
        )
    return rows


def _aggregate_totals(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"UITI": 0.0, "UITI_VANO": 0.0, "EVENT_COUNT": 0, "DURATION_RAW": 0.0, "USERS": 0.0}
    return {
        "UITI": _round(_numeric_series(frame, ["UITI", "uiti_total"]).sum()),
        "UITI_VANO": _round(_numeric_series(frame, ["UITI_VANO", "uiti_vano_total"]).sum()),
        "EVENT_COUNT": _as_int(_numeric_series(frame, ["event_count", "EVENT_COUNT"]).sum()),
        "DURATION_RAW": _round(_numeric_series(frame, ["DURATION_RAW", "duration_raw_total", "duration_raw"]).sum(), 2),
        "USERS": _round(_numeric_series(frame, ["USERS", "users_affected_total", "users_affected"]).sum(), 2),
    }


def _trend_summary(frame: pd.DataFrame, metric_key: str) -> dict[str, Any]:
    if frame.empty:
        return {"available": False}
    metric_key = normalize_metric_key(metric_key)
    work = normalize_daily_frame(frame)
    metric = pd.to_numeric(work.get(metric_key, 0.0), errors="coerce").fillna(0.0)
    if metric.empty:
        return {"available": False}
    max_index = metric.idxmax()
    first_value = float(metric.iloc[0])
    last_value = float(metric.iloc[-1])
    return {
        "available": True,
        "metric": metric_key,
        "first_value": _round(first_value),
        "last_value": _round(last_value),
        "delta": _round(last_value - first_value),
        "max_date": _date_text(work.loc[max_index, "fecha_dia"]),
        "max_value": _round(metric.loc[max_index]),
        "nonzero_days": int((metric > 0).sum()),
    }


def build_circuit_history_12m_payload(
    *,
    daily_frame: pd.DataFrame,
    start_date: str,
    end_date: str,
    circuit_label: str,
    metric_key: str,
    max_points: int = 5,
    thresholds: CriticalityThresholds | None = None,
    attribution_frame: pd.DataFrame | None = None,
    event_frame: pd.DataFrame | None = None,
    environment_frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or CriticalityThresholds(max_points=max_points)
    raw_quality_flags = compute_data_quality_flags(pd.DataFrame(daily_frame), event_frame=event_frame)
    normalized = normalize_daily_frame(daily_frame, start_date=start_date, end_date=end_date)
    if normalized.empty:
        return {
            "available": False,
            "reason": "empty_history",
            "start_date": start_date,
            "end_date": end_date,
            "circuit_label": circuit_label,
            "metric_key": normalize_metric_key(metric_key),
        }

    feature_frame = compute_time_series_features(normalized)
    reasons_by_date = detect_point_reasons(feature_frame, metric_key=metric_key, thresholds=thresholds)
    points = rank_and_merge_critical_points(feature_frame, reasons_by_date, max_points=max_points)
    points = enrich_critical_points_with_attribution(
        points,
        attribution_frame=attribution_frame,
        event_frame=event_frame,
        environment_frame=environment_frame,
    )
    aggregate_totals = _aggregate_totals(normalized)
    attribution_source = pd.DataFrame() if attribution_frame is None else attribution_frame
    history_total = float(aggregate_totals.get("UITI") or 0.0)

    return {
        "available": True,
        "start_date": start_date,
        "end_date": end_date,
        "circuit_label": circuit_label,
        "metric_key": normalize_metric_key(metric_key),
        "event_count": int(aggregate_totals.get("EVENT_COUNT") or 0),
        "aggregate_totals": aggregate_totals,
        "trend_summary": _trend_summary(normalized, metric_key),
        "daily_indicators": _daily_indicator_rows(normalized),
        "critical_points": points,
        "critical_periods": detect_critical_periods(feature_frame, metric_key=metric_key, thresholds=thresholds),
        "dominant_causes": _attribution_items(attribution_source, ["causa"], daily_total=history_total),
        "dominant_event_families": _attribution_items(
            attribution_source,
            ["event_family", "tipo_equi_ope"],
            daily_total=history_total,
        ),
        "dominant_equipment": _attribution_items(
            attribution_source,
            ["equipo_ope", "tipo_equi_ope", "tipo_elemento", "CODE"],
            daily_total=history_total,
        ),
        "dominant_circuits": _attribution_items(attribution_source, ["circuito", "cto_equi_ope", "FPARENT"], daily_total=history_total),
        "external_signals": _external_signals(pd.DataFrame() if environment_frame is None else environment_frame),
        "data_quality_flags": _user_facing_flags(
            sorted(set(raw_quality_flags + compute_data_quality_flags(normalized, event_frame=event_frame)))
        ),
    }


def build_timeseries_context_package(payload: dict[str, Any]) -> dict[str, Any]:
    from chec_dashboard.services.timeseries_interpretability.context_builder import (
        build_timeseries_context_package_v2,
    )

    return build_timeseries_context_package_v2(payload)


def build_summary_interpretability_payload(
    *,
    daily_frame: pd.DataFrame,
    start_date: str,
    end_date: str,
    circuit_label: str,
    metric_key: str,
    generated_at: str,
    max_points: int = 5,
    thresholds: CriticalityThresholds | None = None,
    attribution_frame: pd.DataFrame | None = None,
    event_frame: pd.DataFrame | None = None,
    environment_frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or CriticalityThresholds(max_points=max_points)
    thresholds = CriticalityThresholds(
        high_robust_z=thresholds.high_robust_z,
        low_robust_z=thresholds.low_robust_z,
        delta_robust_z=thresholds.delta_robust_z,
        high_percentile=thresholds.high_percentile,
        low_percentile=thresholds.low_percentile,
        top_contributor_pct=thresholds.top_contributor_pct,
        sustained_percentile=thresholds.sustained_percentile,
        sustained_min_days=thresholds.sustained_min_days,
        max_points=max_points,
    )
    raw_quality_flags = compute_data_quality_flags(pd.DataFrame(daily_frame), event_frame=event_frame)
    normalized = normalize_daily_frame(daily_frame, start_date=start_date, end_date=end_date)
    feature_frame = compute_time_series_features(normalized)
    global_flags = sorted(
        set(raw_quality_flags + compute_data_quality_flags(normalized, event_frame=event_frame))
    )
    visible_flags = _user_facing_flags(global_flags)
    metric_key = normalize_metric_key(metric_key)
    reasons_by_date = detect_point_reasons(feature_frame, metric_key=metric_key, thresholds=thresholds)
    points = rank_and_merge_critical_points(feature_frame, reasons_by_date, max_points=max_points)
    points = enrich_critical_points_with_attribution(
        points,
        attribution_frame=attribution_frame,
        event_frame=event_frame,
        environment_frame=environment_frame,
    )
    if visible_flags:
        for point in points:
            merged = sorted(set((point.get("data_quality_flags") or []) + visible_flags))
            point["data_quality_flags"] = merged
            if any(flag in merged for flag in ("empty_time_series", "all_zero_window", "missing_event_attribution")):
                point["confidence"] = "low"

    periods = detect_critical_periods(feature_frame, metric_key=metric_key, thresholds=thresholds)
    if points:
        status_text = f"Se detectaron {len(points)} eventos de interes para el periodo analizado."
    elif {"empty_time_series", "all_zero_window"} & set(global_flags):
        status_text = (
            "Para el periodo seleccionado no hay eventos con valores disponibles del indicador "
            "para construir el analisis temporal."
        )
    else:
        status_text = "No se detectaron puntos criticos bajo los umbrales actuales."
    if visible_flags:
        status_text = f"{status_text} Observaciones tecnicas: {', '.join(visible_flags)}."

    payload = {
        "start_date": start_date,
        "end_date": end_date,
        "circuit_label": circuit_label,
        "metric_key": metric_key,
        "generated_at": generated_at,
        "critical_points": points,
        "critical_periods": periods,
        "insight_text": None,
        "corpus_citations": [],
        "status_text": status_text,
    }
    payload["insight_text"] = deterministic_insight_text(payload)
    return payload
