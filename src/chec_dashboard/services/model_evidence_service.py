from __future__ import annotations

import hashlib
import json
from typing import Any
import uuid

from chec_dashboard.core.config import Settings
from chec_dashboard.services.capability_registry import capability_metadata, unavailable_payload, utc_now
from chec_dashboard.services.inference_service import InferenceServiceError, get_inference_service


def is_model_backend_available(settings: Settings | None) -> bool:
    if settings is None:
        return False
    backend = (settings.model_backend or "").strip().lower()
    if backend == "mock":
        return True
    if backend == "local":
        return True
    if backend == "azure_ml":
        return bool(settings.azure_ml_endpoint and settings.azure_ml_key)
    if backend == "databricks":
        return bool(settings.databricks_host and settings.databricks_token and settings.databricks_model_endpoint)
    return False


def build_model_evidence_package(
    settings: Settings | None = None,
    *,
    features: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    if settings is None:
        return unavailable_payload(
            capability_id="model_prediction",
            reason="No hay configuracion disponible para seleccionar backend predictivo.",
            missing_requirements=["Settings"],
            next_steps=["Proveer Settings al servicio de evidencia de modelo."],
            trace_id=trace_id,
        )
    if not features:
        return unavailable_payload(
            capability_id="model_prediction",
            reason="La etapa predictiva requiere un vector de caracteristicas explicito y aprobado.",
            missing_requirements=["baseline feature vector builder", "explicit safe features payload"],
            next_steps=[
                "Definir el constructor de vector base para el contexto seleccionado.",
                "Probar el backend con un payload de caracteristicas permitido.",
            ],
            trace_id=trace_id,
        )
    if not is_model_backend_available(settings):
        return unavailable_payload(
            capability_id="model_prediction",
            reason="El backend predictivo no esta configurado para esta instalacion.",
            missing_requirements=["MODEL_BACKEND configurado", "credenciales o endpoint requeridos por el backend"],
            next_steps=["Configurar un backend predictivo soportado.", "Agregar pruebas con backend mock o local."],
            trace_id=trace_id,
            status="not_configured",
        )

    safe_request_id = request_id or f"model-{uuid.uuid4().hex}"
    try:
        result = get_inference_service(settings).predict(
            features=features,
            context=context or {},
            request_id=safe_request_id,
        )
    except InferenceServiceError as exc:
        return {
            **unavailable_payload(
                capability_id="model_prediction",
                reason=f"El backend predictivo fallo de forma segura: {exc.__class__.__name__}.",
                missing_requirements=["backend predictivo operativo"],
                next_steps=["Revisar configuracion del backend y agregar prueba con mock controlado."],
                trace_id=trace_id,
                status="error",
            ),
            "backend_error": str(exc),
        }

    raw_subset = _safe_raw_response_subset(result.raw_response)
    has_masks = any(key in raw_subset for key in ("feature_importance", "feature_importances", "masks", "relevance", "attributions"))
    warnings = [] if has_masks else ["El backend no entrego mascaras ni relevancia de variables."]
    return {
        "status": "available",
        "capability_id": "model_prediction",
        "schema_version": "0.1.0",
        "generated_at": utc_now(),
        "request_id": result.request_id,
        "backend": result.backend,
        "model_version": result.model_version,
        "model_endpoint_name": settings.databricks_model_endpoint if result.backend == "databricks" else None,
        "prediction_values": {
            "prediction": result.prediction,
            "label": result.label,
        },
        "raw_response_subset": raw_subset,
        "input_hash": _input_hash(features),
        "evidence": [
            {
                "evidence_level": "model_signal",
                "description": "Prediccion generada por backend configurado a partir de un vector explicito.",
            }
        ],
        "warnings": warnings,
        "trace_id": trace_id,
        "traceability": {
            **capability_metadata("model_prediction", status="available"),
            "input_hash": _input_hash(features),
            "safe_to_present": True,
        },
    }


def _input_hash(features: dict[str, Any]) -> str:
    text = json.dumps(features, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _safe_raw_response_subset(raw_response: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "model_name",
        "model_version",
        "prediction",
        "predictions",
        "scores",
        "label",
        "feature_importance",
        "feature_importances",
        "masks",
        "attention_masks",
        "relevance",
        "attributions",
    }
    return {
        key: value
        for key, value in (raw_response or {}).items()
        if key in allowed_keys and key.lower() not in {"token", "api_key", "secret", "features"}
    }
