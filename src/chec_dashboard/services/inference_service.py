from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import httpx

from chec_dashboard.core.config import Settings
from chec_dashboard.core.logging import get_logger
from chec_dashboard.services.model_loader import load_local_model


class InferenceServiceError(RuntimeError):
    pass


class InferenceBackendRequestError(InferenceServiceError):
    pass


class InferenceTimeoutError(InferenceBackendRequestError):
    pass


class InferenceResponseFormatError(InferenceBackendRequestError):
    pass


class InferenceConfigurationError(ValueError):
    pass


class UnsupportedModelBackendError(InferenceConfigurationError):
    pass


@dataclass(frozen=True)
class InferenceResult:
    request_id: str
    backend: str
    prediction: float
    label: str
    model_version: str
    raw_response: dict[str, Any]


class InferenceService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = get_logger(__name__, settings.log_level)

    def predict(
        self,
        features: dict[str, Any],
        context: dict[str, Any] | None = None,
        *,
        request_id: str,
    ) -> InferenceResult:
        backend = self.settings.model_backend.lower()
        context = context or {}

        if backend == "mock":
            return self._predict_mock(features, context, request_id=request_id)
        if backend == "local":
            return self._predict_local(features, context, request_id=request_id)
        if backend == "azure_ml":
            return self._predict_azure_ml(features, context, request_id=request_id)
        if backend == "databricks":
            return self._predict_databricks(features, context, request_id=request_id)

        raise UnsupportedModelBackendError(
            f"Unsupported MODEL_BACKEND='{self.settings.model_backend}'. "
            "Supported values: mock, local, azure_ml, databricks"
        )

    def _predict_mock(
        self,
        features: dict[str, Any],
        context: dict[str, Any],
        *,
        request_id: str,
    ) -> InferenceResult:
        numeric_values: list[float] = []
        for value in features.values():
            if isinstance(value, bool):
                numeric_values.append(float(int(value)))
            elif isinstance(value, (int, float)):
                numeric_values.append(float(value))

        score = 0.5
        if numeric_values:
            score = max(0.0, min(1.0, sum(numeric_values) / (len(numeric_values) * 100.0)))

        label = "high_risk" if score >= 0.5 else "low_risk"
        return InferenceResult(
            request_id=request_id,
            backend="mock",
            prediction=score,
            label=label,
            model_version="mock-v1",
            raw_response={"features": features, "context": context},
        )

    def _predict_local(
        self,
        features: dict[str, Any],
        context: dict[str, Any],
        *,
        request_id: str,
    ) -> InferenceResult:
        model = load_local_model()
        score = float(model.predict(features))
        label = "high_risk" if score >= 0.5 else "low_risk"
        return InferenceResult(
            request_id=request_id,
            backend="local",
            prediction=score,
            label=label,
            model_version=model.model_version,
            raw_response={"model_name": model.model_name, "context": context},
        )

    def _predict_azure_ml(
        self,
        features: dict[str, Any],
        context: dict[str, Any],
        *,
        request_id: str,
    ) -> InferenceResult:
        endpoint = self.settings.azure_ml_endpoint
        key = self.settings.azure_ml_key
        if not endpoint or not key:
            raise InferenceConfigurationError(
                "AZURE_ML_ENDPOINT and AZURE_ML_KEY are required for azure_ml backend"
            )

        payload = {"features": features, "context": context}
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Request-ID": request_id,
        }
        response_json = self._post_json(
            backend="azure_ml",
            url=endpoint,
            payload=payload,
            headers=headers,
            request_id=request_id,
        )
        score = self._extract_prediction(response_json)
        label = "high_risk" if score >= 0.5 else "low_risk"

        return InferenceResult(
            request_id=request_id,
            backend="azure_ml",
            prediction=score,
            label=label,
            model_version=str(response_json.get("model_version", "azure-unknown")),
            raw_response=response_json,
        )

    def _predict_databricks(
        self,
        features: dict[str, Any],
        context: dict[str, Any],
        *,
        request_id: str,
    ) -> InferenceResult:
        host = self.settings.databricks_host
        token = self.settings.databricks_token
        endpoint = self.settings.databricks_model_endpoint
        if not host or not token or not endpoint:
            raise InferenceConfigurationError(
                "DATABRICKS_HOST, DATABRICKS_TOKEN and DATABRICKS_MODEL_ENDPOINT are required "
                "for databricks backend"
            )

        url = endpoint if endpoint.startswith("http") else f"{host.rstrip('/')}/{endpoint.lstrip('/')}"
        payload = {"features": features, "context": context}
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Request-ID": request_id,
        }
        response_json = self._post_json(
            backend="databricks",
            url=url,
            payload=payload,
            headers=headers,
            request_id=request_id,
        )
        score = self._extract_prediction(response_json)
        label = "high_risk" if score >= 0.5 else "low_risk"

        return InferenceResult(
            request_id=request_id,
            backend="databricks",
            prediction=score,
            label=label,
            model_version=str(response_json.get("model_version", "databricks-unknown")),
            raw_response=response_json,
        )

    def _post_json(
        self,
        *,
        backend: str,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        request_id: str,
    ) -> dict[str, Any]:
        timeout = max(self.settings.request_timeout_seconds, 1)
        retries = max(self.settings.inference_http_retries, 0)
        backoff = max(self.settings.inference_retry_backoff_ms, 0) / 1000.0

        attempt = 0
        last_error: Exception | None = None
        while attempt <= retries:
            start = time.perf_counter()
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    data = response.json()

                latency_ms = (time.perf_counter() - start) * 1000.0
                self.logger.info(
                    "Inference backend call succeeded",
                    extra={
                        "request_id": request_id,
                        "backend": backend,
                        "attempt": attempt + 1,
                        "latency_ms": round(latency_ms, 2),
                    },
                )

                if not isinstance(data, dict):
                    raise InferenceResponseFormatError(
                        "Inference backend response must be a JSON object"
                    )
                return data
            except httpx.TimeoutException as exc:
                last_error = exc
                latency_ms = (time.perf_counter() - start) * 1000.0
                self.logger.warning(
                    "Inference backend timeout",
                    extra={
                        "request_id": request_id,
                        "backend": backend,
                        "attempt": attempt + 1,
                        "latency_ms": round(latency_ms, 2),
                    },
                )
            except httpx.HTTPStatusError as exc:
                last_error = exc
                latency_ms = (time.perf_counter() - start) * 1000.0
                self.logger.warning(
                    "Inference backend HTTP error",
                    extra={
                        "request_id": request_id,
                        "backend": backend,
                        "attempt": attempt + 1,
                        "status_code": exc.response.status_code,
                        "latency_ms": round(latency_ms, 2),
                    },
                )
            except httpx.RequestError as exc:
                last_error = exc
                latency_ms = (time.perf_counter() - start) * 1000.0
                self.logger.warning(
                    "Inference backend request error",
                    extra={
                        "request_id": request_id,
                        "backend": backend,
                        "attempt": attempt + 1,
                        "latency_ms": round(latency_ms, 2),
                    },
                )

            if attempt < retries and backoff > 0:
                time.sleep(backoff)
            attempt += 1

        if isinstance(last_error, httpx.TimeoutException):
            raise InferenceTimeoutError(
                f"Inference backend timeout after {retries + 1} attempts"
            ) from last_error

        raise InferenceBackendRequestError(
            f"Inference backend request failed after {retries + 1} attempts"
        ) from last_error

    @staticmethod
    def _extract_prediction(payload: dict[str, Any]) -> float:
        prediction = payload.get("prediction")
        if isinstance(prediction, (float, int)):
            return float(prediction)

        predictions = payload.get("predictions")
        if isinstance(predictions, list) and predictions:
            first = predictions[0]
            if isinstance(first, (float, int)):
                return float(first)
            if isinstance(first, dict):
                value = first.get("prediction")
                if isinstance(value, (float, int)):
                    return float(value)

        scores = payload.get("scores")
        if isinstance(scores, list) and scores and isinstance(scores[0], (float, int)):
            return float(scores[0])

        raise InferenceResponseFormatError("Unable to parse prediction score from backend response")



def get_inference_service(settings: Settings) -> InferenceService:
    return InferenceService(settings)
