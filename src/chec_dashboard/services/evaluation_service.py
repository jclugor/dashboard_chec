from __future__ import annotations

from statistics import quantiles
from typing import Any


def score_turn_trace(trace: dict[str, Any]) -> dict[str, Any]:
    citations = trace.get("citations") or []
    retrieved_chunk_ids = trace.get("retrieved_chunk_ids") or []
    validation = trace.get("validation") or {}
    answer_validation = validation.get("answer_validation") or trace.get("answer_validation") or {}
    citation_validation = validation.get("citation_validation") or trace.get("citation_validation") or {}
    compliance_validation = validation.get("compliance_validation") or trace.get("compliance_validation") or {}
    structured = trace.get("structured_answer") or {}
    expected_sections = 9
    section_count = len([value for value in structured.values() if value]) if structured else int(
        answer_validation.get("section_count") or 0
    )
    top3_ids = {str(chunk_id) for chunk_id in retrieved_chunk_ids[:3]}
    cited_ids = {str(citation.get("id")) for citation in citations[:3] if citation.get("id")}
    precision_at_3 = (len(top3_ids & cited_ids) / min(len(top3_ids), 3)) if top3_ids else (1.0 if not citations else 0.0)
    return {
        "retrieval_precision_at_3": round(precision_at_3, 4),
        "citation_validity": 1.0 if citation_validation.get("valid", True) else 0.0,
        "answer_completeness": round(min(section_count, expected_sections) / expected_sections, 4),
        "compliance_overclaim_rate": 0.0 if compliance_validation.get("valid", True) else 1.0,
        "latency_ms": float(trace.get("latency_ms") or 0),
        "failure": 0.0 if trace.get("ready", True) else 1.0,
        "cost_per_answer": float(trace.get("cost_per_answer") or 0),
    }


def build_release_report(traces: list[dict[str, Any]], *, report_only: bool = True) -> dict[str, Any]:
    scores = [score_turn_trace(trace) for trace in traces]
    metrics = _aggregate_scores(scores)
    controls_passed = (
        metrics.get("citation_validity", 1.0) >= 1.0
        and metrics.get("compliance_overclaim_rate", 0.0) <= 0.0
    )
    release_status = "passed" if controls_passed else "review_required"
    return {
        "release_status": release_status,
        "report_only": report_only,
        "trace_count": len(traces),
        "metrics": metrics,
        "controls_passed": controls_passed,
        "llm_judges_enabled": False,
        "sme_review_coverage": "draft_examples_need_sme_review",
    }


def _aggregate_scores(scores: list[dict[str, Any]]) -> dict[str, float]:
    if not scores:
        return {
            "retrieval_precision_at_3": 0.0,
            "citation_validity": 0.0,
            "answer_completeness": 0.0,
            "compliance_overclaim_rate": 0.0,
            "latency_p95": 0.0,
            "failure_rate": 0.0,
            "cost_per_answer": 0.0,
        }
    return {
        "retrieval_precision_at_3": _mean(scores, "retrieval_precision_at_3"),
        "citation_validity": _mean(scores, "citation_validity"),
        "answer_completeness": _mean(scores, "answer_completeness"),
        "compliance_overclaim_rate": _mean(scores, "compliance_overclaim_rate"),
        "latency_p95": _p95([score["latency_ms"] for score in scores]),
        "failure_rate": _mean(scores, "failure"),
        "cost_per_answer": _mean(scores, "cost_per_answer"),
    }


def _mean(scores: list[dict[str, Any]], key: str) -> float:
    return round(sum(float(score.get(key) or 0) for score in scores) / len(scores), 4)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(float(values[0]), 4)
    return round(float(quantiles(values, n=20, method="inclusive")[18]), 4)


_score_turn_trace = score_turn_trace
_build_release_report = build_release_report
