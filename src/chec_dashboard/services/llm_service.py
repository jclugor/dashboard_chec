from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any

import httpx

from chec_dashboard.core.config import Settings
from chec_dashboard.core.logging import get_logger
from chec_dashboard.services.retrieval_service import databricks_api_auth_headers, databricks_host


SUPPORTED_LLM_PROVIDERS = {
    "mock",
    "gemini",
    "databricks_model_serving",
    "azure_openai",
    "openai",
}
LLM_TIERS = {"cheap", "medium", "best"}
DEFAULT_DATABRICKS_SYSTEM_MESSAGE = (
    "Eres un asistente técnico para análisis de confiabilidad eléctrica de CHEC. "
    "Responde en español, usa las citas disponibles y evita conclusiones legales definitivas."
)
STRUCTURED_DATABRICKS_SYSTEM_MESSAGE = (
    DEFAULT_DATABRICKS_SYSTEM_MESSAGE
    + " Para esta solicitud, devuelve exclusivamente un objeto JSON válido. "
    "No incluyas Markdown, explicaciones, etiquetas, ni texto antes o después del JSON."
)
STRUCTURED_JSON_SUFFIX = (
    "\n\nRESTRICCION ESTRICTA DE SALIDA:\n"
    "- Devuelve solo un objeto JSON valido.\n"
    "- El primer caracter de la respuesta debe ser { y el ultimo debe ser }.\n"
    "- No uses Markdown, bloques ```json, comentarios, ni texto explicativo.\n"
    "- Todos los campos tipo arreglo deben ser arreglos JSON aunque tengan un solo elemento.\n"
    "- Maximo 2 point_narratives, maximo 2 evidence_matrix y maximo 2 strings por arreglo.\n"
    "- Cada string debe ser corto, idealmente menos de 160 caracteres.\n"
)
STRUCTURED_JSON_REPAIR_SUFFIX = (
    "\n\nREINTENTO COMPACTO OBLIGATORIO:\n"
    "- Devuelve solo un objeto JSON valido y cerrado.\n"
    "- Maximo 1 point_narratives y maximo 1 evidence_matrix.\n"
    "- Maximo 1 string por arreglo, excepto missing_evidence que puede tener 2.\n"
    "- Cada string debe ser muy corto, menos de 140 caracteres.\n"
    "- No copies una respuesta truncada; resume solo la evidencia mas importante.\n"
)
STRUCTURED_REPAIR_MAX_CHARS = 6000


@dataclass(frozen=True)
class DatabricksModelServingResult:
    text: str
    usage: dict[str, Any]
    raw_response: dict[str, Any]


class DatabricksModelServingError(RuntimeError):
    pass


class DatabricksModelServingConfigurationError(DatabricksModelServingError):
    pass


class DatabricksModelServingRequestError(DatabricksModelServingError):
    pass


class DatabricksModelServingResponseError(DatabricksModelServingError):
    pass


def llm_provider(settings: Settings) -> str:
    provider = (settings.llm_provider or "mock").strip().lower()
    if provider not in SUPPORTED_LLM_PROVIDERS:
        return provider
    return provider


def normalize_llm_tier(settings: Settings, tier: str | None = None) -> str:
    candidate = (tier or settings.llm_default_tier or "medium").strip().lower()
    if candidate not in LLM_TIERS:
        candidate = "medium"
    if candidate == "best" and (not settings.llm_allow_best_tier or settings.llm_max_expensive_calls_per_request < 1):
        return "medium"
    return candidate


def select_llm_tier(settings: Settings, *, prompt: str | None = None, requested_tier: str | None = None) -> str:
    if not settings.llm_routing_enabled:
        return normalize_llm_tier(settings, requested_tier or settings.llm_default_tier)
    if requested_tier:
        return normalize_llm_tier(settings, requested_tier)
    prompt_length = len(prompt or "")
    if settings.llm_route_simple_to_cheap and prompt_length < 2500 and settings.llm_cheap_endpoint_name:
        return "cheap"
    return normalize_llm_tier(settings, settings.llm_default_tier)


def llm_endpoint_name(settings: Settings, tier: str | None = None) -> str | None:
    selected_tier = normalize_llm_tier(settings, tier)
    if settings.llm_routing_enabled:
        tier_endpoint = {
            "cheap": settings.llm_cheap_endpoint_name,
            "medium": settings.llm_medium_endpoint_name,
            "best": settings.llm_best_endpoint_name,
        }.get(selected_tier)
        if tier_endpoint:
            return tier_endpoint
    return settings.llm_endpoint_name or settings.databricks_model_endpoint


def llm_endpoint_configured(settings: Settings) -> bool:
    provider = llm_provider(settings)
    if provider == "databricks_model_serving":
        return bool(llm_endpoint_name(settings))
    return True


def llm_configured(settings: Settings) -> bool:
    provider = llm_provider(settings)
    if provider == "mock":
        return True
    if provider == "gemini":
        return bool(settings.gemini_api_key)
    if provider == "databricks_model_serving":
        return bool(llm_endpoint_name(settings))
    return False


def llm_configuration_message(settings: Settings) -> str:
    provider = llm_provider(settings)
    if provider == "mock":
        return "Proveedor LLM mock listo para respuestas determinísticas de desarrollo."
    if provider == "gemini" and not settings.gemini_api_key:
        return "El proveedor LLM 'gemini' no está configurado. Define GEMINI_API_KEY o usa LLM_PROVIDER=mock."
    if provider == "databricks_model_serving" and not llm_endpoint_name(settings):
        return "Databricks Model Serving no está configurado. Define LLM_ENDPOINT_NAME."
    if provider == "databricks_model_serving":
        return "Databricks Model Serving listo para generar respuestas gobernadas."
    if provider in {"azure_openai", "openai"}:
        return f"El proveedor LLM '{provider}' está reservado para una integración posterior."
    return f"Proveedor LLM no soportado: {provider}."


def _context_descriptor(context_package: dict[str, Any]) -> str:
    identity = context_package.get("selected_context") or {}
    for key in ("equipo_ope", "CODE", "display_label", "cto_equi_ope", "circuito", "FPARENT"):
        value = identity.get(key)
        if value:
            return str(value)
    if context_package.get("context_kind") == "view":
        return str(identity.get("scope_label") or "vista filtrada")
    return "contexto seleccionado"


def _mock_answer(
    *,
    context_package: dict[str, Any],
    question: str | None,
    citations: list[dict[str, Any]],
    skill_resolution: Any | None = None,
) -> str:
    analysis_name = str(context_package.get("nombre_analisis") or "Confiabilidad")
    descriptor = _context_descriptor(context_package)
    metrics = context_package.get("metrics") or {}
    metric_bits = []
    for label, key in (("UITI", "uiti"), ("UITI vano", "uiti_vano"), ("duración fuente", "duration_raw")):
        if key in metrics:
            metric_bits.append(f"{label}: {metrics[key]}")
    metric_text = ", ".join(metric_bits) if metric_bits else "sin métricas numéricas destacadas en el contexto"
    citation_refs = ", ".join(f"[{index}]" for index, _ in enumerate(citations, start=1))
    evidence_text = (
        f"Se recuperaron {len(citations)} fragmentos técnicos relevantes ({citation_refs})."
        if citations
        else "No se recuperaron fragmentos técnicos para citar."
    )
    question_text = (question or "Sin pregunta adicional.").strip()
    sections = _mock_sections(skill_resolution)
    return (
        f"### {analysis_name}\n\n"
        f"**{sections[0]}:** el análisis mock resume el contexto `{descriptor}` con {metric_text}.\n\n"
        f"**{sections[1]}:** {evidence_text} La interpretación se mantiene como posible riesgo "
        "o señal técnica, no como conclusión legal definitiva.\n\n"
        f"**Pregunta atendida:** {question_text}\n\n"
        f"**{sections[2]}:** valida en campo la causa raíz, el estado del activo y la trazabilidad documental "
        "antes de cerrar una recomendación operativa.\n\n"
        f"**{sections[3]}:** prioriza revisión técnica y conserva las citas recuperadas como soporte inicial."
    )


def _mock_sections(skill_resolution: Any | None) -> tuple[str, str, str, str]:
    fallback = ("Estado observado", "Banderas de evidencia", "Datos faltantes", "Recomendación")
    if skill_resolution is None:
        return fallback
    skill = getattr(skill_resolution, "skill", None)
    configured = tuple(getattr(skill, "answer_sections", ()) or ())
    if len(configured) >= 4:
        return configured[0], configured[1], configured[3] if len(configured) > 3 else configured[2], configured[-2]
    return fallback


def _generate_gemini_answer(settings: Settings, prompt: str) -> str:
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover - depends on runtime installation
        raise RuntimeError("La dependencia google-genai no está instalada.") from exc

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY no está configurada.")

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(model=settings.gemini_model, contents=prompt)
    text = getattr(response, "text", None)
    if text:
        return str(text)
    candidates = getattr(response, "candidates", None)
    if candidates:
        return str(candidates[0])
    raise RuntimeError("Gemini no devolvió texto utilizable.")


def _databricks_chat_payload(
    settings: Settings,
    prompt: str,
    *,
    system_message: str | None = None,
    response_format: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "messages": [
            {
                "role": "system",
                "content": system_message or DEFAULT_DATABRICKS_SYSTEM_MESSAGE,
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": settings.llm_max_tokens,
        "temperature": settings.llm_temperature,
    }
    if response_format:
        payload["response_format"] = response_format
    return payload


def _databricks_model_serving_url(settings: Settings, tier: str | None = None) -> str:
    endpoint = llm_endpoint_name(settings, tier=tier)
    if not endpoint:
        raise DatabricksModelServingConfigurationError(
            "Databricks Model Serving no está configurado. Define LLM_ENDPOINT_NAME."
        )
    endpoint = endpoint.strip()
    if endpoint.startswith(("http://", "https://")):
        return endpoint

    host = None
    if settings.databricks_host:
        host = settings.databricks_host.strip().rstrip("/")
        if host and not host.startswith(("http://", "https://")):
            host = f"https://{host}"
    if not host:
        host = databricks_host()
    if not host:
        raise DatabricksModelServingConfigurationError(
            "DATABRICKS_HOST no está configurado para consultar Databricks Model Serving."
        )

    if endpoint.startswith("/serving-endpoints/"):
        return f"{host}{endpoint}"
    return f"{host}/serving-endpoints/{endpoint}/invocations"


def _databricks_model_serving_headers(settings: Settings, trace_id: str | None) -> dict[str, str]:
    headers = None
    if settings.databricks_token:
        headers = {"Authorization": f"Bearer {settings.databricks_token}"}
    if not headers:
        headers = databricks_api_auth_headers()
    if not headers:
        raise DatabricksModelServingConfigurationError(
            "No hay credenciales Databricks para consultar Model Serving."
        )
    headers = {**headers, "Content-Type": "application/json"}
    if trace_id:
        headers["X-Request-ID"] = trace_id
    return headers


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    if hasattr(value, "as_dict"):
        try:
            return value.as_dict().get(name, default)
        except Exception:
            pass
    return getattr(value, name, default)


def _as_response_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "as_dict"):
        data = value.as_dict()
        if isinstance(data, dict):
            return data
    if hasattr(value, "to_dict"):
        data = value.to_dict()
        if isinstance(data, dict):
            return data
    raise DatabricksModelServingResponseError("Databricks Model Serving devolvió una respuesta no JSON.")


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            text = _field(item, "text")
            if text is None:
                text = _field(item, "content")
            if text is not None:
                parts.append(str(text))
        return "\n".join(parts).strip()
    if content is None:
        return ""
    return str(content).strip()


def _parse_databricks_model_serving_response(response: Any) -> DatabricksModelServingResult:
    data = _as_response_dict(response)
    choices = _field(data, "choices") or []
    text = ""
    if choices:
        first_choice = choices[0]
        message = _field(first_choice, "message") or {}
        text = _content_text(_field(message, "content"))
        if not text:
            text = _content_text(_field(first_choice, "text"))
    if not text:
        prediction = _field(data, "prediction") or _field(data, "predictions")
        if isinstance(prediction, list) and prediction:
            prediction = prediction[0]
        text = _content_text(_field(prediction, "content") if isinstance(prediction, dict) else prediction)
    if not text:
        raise DatabricksModelServingResponseError("Databricks Model Serving no devolvió texto utilizable.")
    usage = _field(data, "usage") or {}
    if not isinstance(usage, dict):
        usage = _as_response_dict(usage)
    return DatabricksModelServingResult(text=text, usage=usage, raw_response=data)


def _default_databricks_post_json(
    *,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: int,
) -> dict[str, Any]:
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise DatabricksModelServingResponseError("Databricks Model Serving devolvió una respuesta no JSON.")
    return data


class DatabricksModelServingLLMClient:
    def __init__(
        self,
        settings: Settings,
        *,
        post_json: Any | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        self.settings = settings
        self._post_json = post_json or _default_databricks_post_json
        self._sleep = sleep
        self._logger = get_logger(__name__, settings.log_level)

    def generate(
        self,
        prompt: str,
        *,
        trace_id: str | None = None,
        llm_tier: str | None = None,
        system_message: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> DatabricksModelServingResult:
        selected_tier = select_llm_tier(self.settings, prompt=prompt, requested_tier=llm_tier)
        url = _databricks_model_serving_url(self.settings, tier=selected_tier)
        headers = _databricks_model_serving_headers(self.settings, trace_id)
        payload = _databricks_chat_payload(
            self.settings,
            prompt,
            system_message=system_message,
            response_format=response_format,
        )
        retries = max(self.settings.inference_http_retries, 0)
        timeout = max(self.settings.request_timeout_seconds, 1)
        backoff = max(self.settings.inference_retry_backoff_ms, 0) / 1000.0
        endpoint = llm_endpoint_name(self.settings, tier=selected_tier)

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            start = time.perf_counter()
            try:
                response = self._post_json(url=url, payload=payload, headers=headers, timeout=timeout)
                result = _parse_databricks_model_serving_response(response)
                latency_ms = (time.perf_counter() - start) * 1000.0
                self._logger.info(
                    "Databricks Model Serving call succeeded",
                    extra={
                        "trace_id": trace_id,
                        "llm_provider": "databricks_model_serving",
                        "model_endpoint_name": endpoint,
                        "llm_tier": selected_tier,
                        "attempt": attempt + 1,
                        "latency_ms": round(latency_ms, 2),
                        "prompt_tokens": result.usage.get("prompt_tokens"),
                        "completion_tokens": result.usage.get("completion_tokens"),
                        "total_tokens": result.usage.get("total_tokens"),
                    },
                )
                return result
            except DatabricksModelServingResponseError:
                raise
            except httpx.TimeoutException as exc:
                last_error = exc
                self._log_model_serving_warning("Databricks Model Serving timeout", trace_id, endpoint, attempt, start)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                self._log_model_serving_warning("Databricks Model Serving HTTP error", trace_id, endpoint, attempt, start)
            except httpx.HTTPError as exc:
                last_error = exc
                self._log_model_serving_warning("Databricks Model Serving request error", trace_id, endpoint, attempt, start)
            if attempt < retries and backoff:
                self._sleep(backoff)

        if isinstance(last_error, httpx.TimeoutException):
            raise DatabricksModelServingRequestError(
                "Databricks Model Serving no respondió antes del tiempo límite."
            ) from last_error
        raise DatabricksModelServingRequestError(
            "No fue posible consultar Databricks Model Serving."
        ) from last_error

    def _log_model_serving_warning(
        self,
        message: str,
        trace_id: str | None,
        endpoint: str | None,
        attempt: int,
        start: float,
    ) -> None:
        latency_ms = (time.perf_counter() - start) * 1000.0
        self._logger.warning(
            message,
            extra={
                "trace_id": trace_id,
                "llm_provider": "databricks_model_serving",
                "model_endpoint_name": endpoint,
                "attempt": attempt + 1,
                "latency_ms": round(latency_ms, 2),
            },
        )


def _generate_databricks_model_serving_answer(
    settings: Settings,
    prompt: str,
    *,
    trace_id: str | None = None,
    llm_tier: str | None = None,
    system_message: str | None = None,
    response_format: dict[str, Any] | None = None,
) -> str:
    client = DatabricksModelServingLLMClient(settings)
    return client.generate(
        prompt,
        trace_id=trace_id,
        llm_tier=llm_tier,
        system_message=system_message,
        response_format=response_format,
    ).text


def generate_llm_answer(
    settings: Settings,
    *,
    prompt: str,
    context_package: dict[str, Any],
    question: str | None,
    citations: list[dict[str, Any]],
    skill_resolution: Any | None = None,
    trace_id: str | None = None,
    llm_tier: str | None = None,
) -> str:
    provider = llm_provider(settings)
    if provider == "mock":
        return _mock_answer(
            context_package=context_package,
            question=question,
            citations=citations,
            skill_resolution=skill_resolution,
        )
    if provider == "gemini":
        return _generate_gemini_answer(settings, prompt)
    if provider == "databricks_model_serving":
        return _generate_databricks_model_serving_answer(settings, prompt, trace_id=trace_id, llm_tier=llm_tier)
    raise RuntimeError(llm_configuration_message(settings))


def _extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _structured_prompt(prompt: str, *, schema_name: str, json_schema: dict[str, Any]) -> str:
    _ = json_schema
    return f"{prompt}\n\nEsquema objetivo: {schema_name}.{STRUCTURED_JSON_SUFFIX}"


def _structured_repair_prompt(
    *,
    schema_name: str,
    json_schema: dict[str, Any],
    previous_answer: str,
    original_prompt: str | None = None,
) -> str:
    _ = json_schema
    prompt_prefix = f"{original_prompt}\n\n" if original_prompt else ""
    return (
        f"{prompt_prefix}"
        f"La respuesta anterior para `{schema_name}` no fue un objeto JSON valido o completo.\n"
        "Reintenta desde el paquete estructurado original con una salida mucho mas corta.\n"
        "Si falta evidencia para un campo, usa arreglos vacios o textos breves de limitacion; no inventes datos.\n"
        f"{STRUCTURED_JSON_REPAIR_SUFFIX}\n"
        "RESPUESTA_ANTERIOR:\n"
        f"{previous_answer[:1200]}"
    )


def _generate_structured_databricks_answer(
    settings: Settings,
    *,
    prompt: str,
    trace_id: str | None,
    llm_tier: str | None,
) -> str | None:
    logger = get_logger(__name__, settings.log_level)
    try:
        return _generate_databricks_model_serving_answer(
            settings,
            prompt,
            trace_id=trace_id,
            llm_tier=llm_tier,
            system_message=STRUCTURED_DATABRICKS_SYSTEM_MESSAGE,
            response_format={"type": "json_object"},
        )
    except (DatabricksModelServingRequestError, DatabricksModelServingResponseError) as exc:
        logger.warning(
            "Databricks structured JSON response_format failed; retrying without response_format",
            extra={"trace_id": trace_id, "error": str(exc)},
        )
        return None


def generate_llm_structured_answer(
    settings: Settings,
    *,
    prompt: str,
    schema_name: str,
    json_schema: dict[str, Any],
    context_package: dict[str, Any],
    question: str | None,
    citations: list[dict[str, Any]],
    skill_resolution: Any | None = None,
    trace_id: str | None = None,
    llm_tier: str | None = None,
) -> dict[str, Any] | None:
    """Return a strict JSON object for structured workflows."""
    logger = get_logger(__name__, settings.log_level)
    provider = llm_provider(settings)
    prompt_with_constraints = _structured_prompt(prompt, schema_name=schema_name, json_schema=json_schema)
    previous_answer: str | None = None

    if provider == "databricks_model_serving":
        previous_answer = _generate_structured_databricks_answer(
            settings,
            prompt=prompt_with_constraints,
            trace_id=trace_id,
            llm_tier=llm_tier,
        )
        if previous_answer:
            parsed = _extract_json_object(previous_answer)
            if parsed is not None:
                return parsed
            logger.warning(
                "Structured Databricks response was not valid JSON",
                extra={"trace_id": trace_id, "schema_name": schema_name, "response_chars": len(previous_answer)},
            )

    if previous_answer is None:
        previous_answer = generate_llm_answer(
            settings,
            prompt=prompt_with_constraints,
            context_package=context_package,
            question=question,
            citations=citations,
            skill_resolution=skill_resolution,
            trace_id=trace_id,
            llm_tier=llm_tier,
        )
        parsed = _extract_json_object(previous_answer)
        if parsed is not None:
            return parsed

    if provider == "mock":
        return None

    repair_prompt = _structured_repair_prompt(
        schema_name=schema_name,
        json_schema=json_schema,
        previous_answer=previous_answer,
        original_prompt=prompt,
    )
    if provider == "databricks_model_serving":
        repair_answer = _generate_databricks_model_serving_answer(
            settings,
            repair_prompt,
            trace_id=trace_id,
            llm_tier=llm_tier,
            system_message=STRUCTURED_DATABRICKS_SYSTEM_MESSAGE,
        )
    else:
        repair_answer = generate_llm_answer(
            settings,
            prompt=repair_prompt,
            context_package=context_package,
            question=question,
            citations=citations,
            skill_resolution=skill_resolution,
            trace_id=trace_id,
            llm_tier=llm_tier,
        )
    parsed = _extract_json_object(repair_answer)
    if parsed is None:
        logger.warning(
            "Structured LLM repair response was not valid JSON",
            extra={"trace_id": trace_id, "schema_name": schema_name, "response_chars": len(repair_answer)},
        )
    return parsed
