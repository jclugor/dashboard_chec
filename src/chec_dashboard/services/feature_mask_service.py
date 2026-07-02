from __future__ import annotations

from typing import Any

from chec_dashboard.services.capability_registry import capability_metadata, unavailable_payload, utc_now


MASK_KEYS = ("feature_importance", "feature_importances", "masks", "attention_masks", "relevance", "attributions")


def extract_feature_masks(raw_model_response: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(raw_model_response, dict):
        return []
    for key in MASK_KEYS:
        if key not in raw_model_response:
            continue
        masks = _normalize_masks(raw_model_response.get(key), source=key)
        if masks:
            return masks
    return []


def build_feature_mask_package(
    raw_model_response: dict[str, Any] | None = None,
    *,
    trace_id: str | None = None,
) -> dict[str, Any]:
    masks = extract_feature_masks(raw_model_response)
    if not masks:
        return unavailable_payload(
            capability_id="feature_masks",
            reason="La respuesta del modelo no incluyo mascaras, relevancia ni atribuciones de variables.",
            missing_requirements=["feature_importance, masks, relevance o attributions en la respuesta del modelo"],
            next_steps=["Solicitar al backend predictivo que devuelva atribuciones si el modelo las soporta."],
            trace_id=trace_id,
            status="not_provided",
        )
    return {
        "status": "available",
        "capability_id": "feature_masks",
        "schema_version": "0.1.0",
        "generated_at": utc_now(),
        "feature_masks": masks,
        "evidence": [
            {
                "evidence_level": "model_signal",
                "description": "Mascaras o relevancias provistas por la respuesta del modelo.",
            }
        ],
        "warnings": ["Las mascaras son senales estadisticas del modelo, no prueba causal."],
        "trace_id": trace_id,
        "traceability": capability_metadata("feature_masks", status="available"),
    }


def _normalize_masks(value: Any, *, source: str) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        masks: list[dict[str, Any]] = []
        for feature, payload in value.items():
            normalized = _mask_item(feature_name=str(feature), payload=payload, source=source)
            if normalized is not None:
                masks.append(normalized)
        return masks
    if isinstance(value, list):
        masks: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            if isinstance(item, dict):
                feature_name = str(
                    item.get("feature_name")
                    or item.get("feature")
                    or item.get("name")
                    or item.get("variable")
                    or f"feature_{index}"
                )
                normalized = _mask_item(feature_name=feature_name, payload=item, source=source)
            else:
                normalized = _mask_item(feature_name=f"feature_{index}", payload=item, source=source)
            if normalized is not None:
                masks.append(normalized)
        return masks
    return []


def _mask_item(feature_name: str, payload: Any, *, source: str) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        score = _numeric(payload.get("relevance_score") or payload.get("score") or payload.get("importance") or payload.get("value"))
        feature_value = payload.get("feature_value") or payload.get("raw_value")
        mode = payload.get("mode") or payload.get("group") or "model_signal"
        direction = payload.get("direction")
    else:
        score = _numeric(payload)
        feature_value = None
        mode = "model_signal"
        direction = None
    if score is None:
        return None
    bounded_score = max(-1.0, min(float(score), 1.0)) if -1.0 <= float(score) <= 1.0 else float(score)
    return {
        "feature_name": feature_name,
        "feature_value": feature_value,
        "relevance_score": bounded_score,
        "mode": str(mode),
        "direction": str(direction) if direction not in (None, "") else None,
        "source": source,
        "evidence_level": "model_signal",
    }


def _numeric(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
