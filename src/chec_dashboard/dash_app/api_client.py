from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import httpx

from chec_dashboard.config import settings
from chec_dashboard.services.data_service import (
    get_dashboard_metadata,
    get_map_filter_metadata,
    get_map_metadata,
    get_map_payload,
    get_probability_columns_metadata,
    get_probability_filter_options_metadata,
    get_probability_metadata,
    get_probability_payload,
    get_summary_metadata,
    get_summary_payload,
)
from chec_dashboard.services.chatbot_service import (
    assess_chatbot_context,
    get_chatbot_context_options,
    get_chatbot_status,
)


TRANSIENT_STARTUP_STATUS_CODES = {502, 503, 504}
TRANSIENT_RESPONSE_STATUS_CODES = {502, 503, 504}


@dataclass(frozen=True)
class StartupStatus:
    status: str
    message: str
    status_code: int | None = None
    payload: dict[str, Any] | None = None

    @property
    def ready(self) -> bool:
        return self.status == "ready"


def _request_json_no_raise(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> tuple[int | None, dict[str, Any] | None, str | None]:
    base_url = settings.api_base_url.rstrip("/")
    url = f"{base_url}{path}"
    timeout = max(settings.request_timeout_seconds, 1)

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method=method, url=url, params=params, json=json_body)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return response.status_code, payload, None
    except httpx.RequestError as exc:
        return None, None, str(exc)


def _use_inproc_transport() -> bool:
    return settings.api_transport == "inproc"


def _inproc_ready_status() -> StartupStatus:
    try:
        get_dashboard_metadata(settings)
    except (FileNotFoundError, ValueError) as exc:
        return StartupStatus("data_unavailable", str(exc))
    except Exception as exc:
        return StartupStatus("warming", str(exc))
    return StartupStatus("ready", "In-process data provider ready.")


def _extract_readiness_message(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "El backend se esta iniciando. Espera unos segundos."

    checks = payload.get("checks")
    if isinstance(checks, dict):
        messages: list[str] = []
        for check in checks.values():
            if isinstance(check, dict) and check.get("ok") is False:
                message = check.get("message")
                if message:
                    messages.append(str(message))
        if messages:
            return " ".join(messages)

    detail = payload.get("detail")
    if detail:
        return str(detail)
    return "El backend se esta iniciando. Espera unos segundos."


def check_api_health() -> StartupStatus:
    if _use_inproc_transport():
        return StartupStatus("ready", "In-process provider healthy.", 200, {"status": "ok"})
    status_code, payload, error = _request_json_no_raise("GET", "/health")
    if status_code == 200:
        return StartupStatus("ready", "API health check ok.", status_code, payload)
    if status_code in TRANSIENT_STARTUP_STATUS_CODES or status_code is None:
        return StartupStatus(
            "warming",
            "El backend se esta iniciando. Espera unos segundos.",
            status_code,
            payload,
        )
    return StartupStatus(
        "error",
        error or f"API health check failed with status {status_code}.",
        status_code,
        payload,
    )


def check_api_ready() -> StartupStatus:
    if _use_inproc_transport():
        return _inproc_ready_status()
    status_code, payload, error = _request_json_no_raise("GET", "/ready")
    if status_code == 200 and payload and payload.get("ready") is True:
        return StartupStatus("ready", "API ready.", status_code, payload)

    if status_code == 503 and payload and isinstance(payload.get("checks"), dict):
        message = _extract_readiness_message(payload)
        checks = payload.get("checks", {})
        data_check = checks.get("data") if isinstance(checks, dict) else None
        if isinstance(data_check, dict) and data_check.get("ok") is False:
            return StartupStatus("data_unavailable", message, status_code, payload)
        return StartupStatus("warming", message, status_code, payload)

    if status_code in TRANSIENT_STARTUP_STATUS_CODES or status_code is None:
        return StartupStatus(
            "warming",
            error or "El backend se esta iniciando. Espera unos segundos.",
            status_code,
            payload,
        )

    return StartupStatus(
        "error",
        error or _extract_readiness_message(payload),
        status_code,
        payload,
    )


def warm_api_metadata() -> StartupStatus:
    if _use_inproc_transport():
        return _inproc_ready_status()
    # Keep cold-start warmup intentionally lightweight for scale-to-zero demos.
    # Calling /data?section=all here loads several pandas datasets at once and
    # can push Azure Container Apps over the memory limit before the UI renders.
    status_code, payload, error = _request_json_no_raise(
        "GET",
        "/data",
        params={"section": "probability"},
    )
    if status_code == 200:
        return StartupStatus("ready", "Lightweight metadata warmup complete.", status_code, payload)
    if status_code in TRANSIENT_STARTUP_STATUS_CODES or status_code is None:
        return StartupStatus(
            "warming",
            error or "Preparando datos iniciales del dashboard.",
            status_code,
            payload,
        )
    return StartupStatus(
        "error",
        error or _extract_readiness_message(payload),
        status_code,
        payload,
    )



def _request_json(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    retries: int = 2,
) -> dict[str, Any]:
    base_url = settings.api_base_url.rstrip("/")
    url = f"{base_url}{path}"
    timeout = max(settings.request_timeout_seconds, 1)

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.request(method=method, url=url, params=params, json=json_body)
            if response.status_code in TRANSIENT_RESPONSE_STATUS_CODES and attempt < retries:
                last_error = RuntimeError(f"Transient API status {response.status_code}")
                time.sleep(0.5 * (attempt + 1))
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("API response must be a JSON object")
            return payload
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in TRANSIENT_RESPONSE_STATUS_CODES and attempt < retries:
                last_error = exc
                time.sleep(0.5 * (attempt + 1))
                continue
            detail = None
            try:
                detail_payload = exc.response.json()
                if isinstance(detail_payload, dict):
                    detail = detail_payload.get("detail")
            except Exception:
                detail = None
            message = detail or f"API request failed with status {exc.response.status_code}"
            raise RuntimeError(message) from exc
        except (httpx.RequestError, ValueError, RuntimeError) as exc:
            last_error = exc

    raise RuntimeError(f"API request failed: {last_error}")



def fetch_map_options() -> dict[str, Any]:
    if _use_inproc_transport():
        return get_map_metadata(settings)
    payload = _request_json("GET", "/data", params={"section": "map"})
    return payload.get("map", {})


def fetch_map_circuit_options(selected_period: str, selected_municipio: str) -> dict[str, Any]:
    if _use_inproc_transport():
        return get_map_filter_metadata(
            settings=settings,
            action="circuits",
            selected_period=selected_period,
            selected_municipio=selected_municipio,
        )
    payload = _request_json(
        "POST",
        "/data",
        json_body={
            "mode": "map_metadata",
            "map_metadata": {
                "action": "circuits",
                "selected_period": selected_period,
                "selected_municipio": selected_municipio,
            },
        },
    )
    return payload.get("map_metadata", {})


def fetch_summary_options() -> dict[str, Any]:
    if _use_inproc_transport():
        return get_summary_metadata(settings)
    payload = _request_json("GET", "/data", params={"section": "summary"})
    return payload.get("summary", {})



def fetch_probability_options() -> dict[str, Any]:
    if _use_inproc_transport():
        return get_probability_metadata(settings)
    payload = _request_json("GET", "/data", params={"section": "probability"})
    return payload.get("probability", {})



def fetch_probability_metadata(
    action: str,
    *,
    criteria: str | None = None,
    selected_column: str | None = None,
    previous_filters: list[list[Any]] | None = None,
) -> dict[str, Any]:
    if _use_inproc_transport():
        if action == "criteria":
            return get_probability_metadata(settings)
        if action == "columns":
            return get_probability_columns_metadata(settings, criteria=criteria or "")
        if action == "filter_options":
            return get_probability_filter_options_metadata(
                settings=settings,
                criteria=criteria or "",
                selected_column=selected_column or "",
                previous_filters=previous_filters or [],
            )
        raise RuntimeError(f"Unsupported probability metadata action: {action}")
    payload = _request_json(
        "POST",
        "/data",
        json_body={
            "mode": "probability_metadata",
            "probability_metadata": {
                "action": action,
                "criteria": criteria,
                "selected_column": selected_column,
                "previous_filters": previous_filters or [],
            },
        },
    )
    return payload.get("probability_metadata", {})



def fetch_map_render(
    selected_period: str,
    selected_municipio: str,
    day: int,
    *,
    selected_circuit: str | None = None,
    selected_circuits: list[str] | None = None,
    selected_output: str | None = None,
) -> dict[str, Any]:
    if _use_inproc_transport():
        return get_map_payload(
            settings=settings,
            selected_period=selected_period,
            selected_municipio=selected_municipio,
            selected_circuit=selected_circuit,
            selected_circuits=selected_circuits,
            selected_output=selected_output,
            day=day,
        )
    payload = _request_json(
        "POST",
        "/data",
        json_body={
            "mode": "map",
            "map": {
                "selected_period": selected_period,
                "selected_municipio": selected_municipio,
                "selected_circuit": selected_circuit,
                "selected_circuits": selected_circuits,
                "selected_output": selected_output,
                "day": day,
            },
        },
    )
    return payload.get("map", {})



def fetch_summary_data(
    start_date_raw: str | None,
    end_date_raw: str | None,
    circuito: str | None,
    metric_mode: str | None,
) -> dict[str, Any]:
    if _use_inproc_transport():
        return get_summary_payload(
            settings=settings,
            start_date_raw=start_date_raw,
            end_date_raw=end_date_raw,
            circuito=circuito,
            metric_mode=metric_mode or "BOTH",
        )
    payload = _request_json(
        "POST",
        "/data",
        json_body={
            "mode": "summary",
            "summary": {
                "start_date": start_date_raw,
                "end_date": end_date_raw,
                "circuito": circuito,
                "metric_mode": metric_mode or "BOTH",
            },
        },
    )
    return payload.get("summary", {})



def fetch_probability_data(
    criteria: str,
    target_column: str,
    filters: list[list[Any]],
) -> dict[str, Any]:
    if _use_inproc_transport():
        return get_probability_payload(
            settings=settings,
            criteria=criteria,
            target_column=target_column,
            filters=filters,
        )
    payload = _request_json(
        "POST",
        "/data",
        json_body={
            "mode": "probability",
            "probability": {
                "criteria": criteria,
                "target_column": target_column,
                "filters": filters,
            },
        },
    )
    return payload.get("probability", {})


def fetch_chatbot_status() -> dict[str, Any]:
    if _use_inproc_transport():
        return get_chatbot_status(settings)
    return _request_json("GET", "/chatbot/status")


def fetch_chatbot_context_options(
    *,
    context_kind: str,
    selected_period: str,
    selected_municipio: str,
    selected_circuits: list[str] | None = None,
    search: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    if _use_inproc_transport():
        return get_chatbot_context_options(
            settings=settings,
            context_kind=context_kind,
            selected_period=selected_period,
            selected_municipio=selected_municipio,
            selected_circuits=selected_circuits,
            search=search,
            limit=limit,
        )
    return _request_json(
        "POST",
        "/chatbot/context-options",
        json_body={
            "context_kind": context_kind,
            "selected_period": selected_period,
            "selected_municipio": selected_municipio,
            "selected_circuits": selected_circuits,
            "search": search,
            "limit": limit,
        },
    )


def fetch_chatbot_assessment(
    *,
    selected_context: dict[str, Any],
    question: str | None = None,
    briefing_type: str = "reliability",
    question_id: str | None = None,
) -> dict[str, Any]:
    if _use_inproc_transport():
        return assess_chatbot_context(
            settings=settings,
            selected_context=selected_context,
            question=question,
            briefing_type=briefing_type,
            question_id=question_id,
        )
    return _request_json(
        "POST",
        "/chatbot/assess",
        json_body={
            "selected_context": selected_context,
            "question": question,
            "briefing_type": briefing_type,
            "question_id": question_id,
        },
    )
