from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from chec_dashboard.core.config import Settings
from chec_dashboard.core.logging import get_logger
from chec_dashboard.services.databricks_sql import DatabricksSQLWarehouseClient, sql_literal, sql_table_name


logger = get_logger(__name__)

_PROMPT_CACHE: dict[tuple[str, str, str], "PromptRuntimeMetadata"] = {}
_PROMPT_TEMPLATE_CACHE: dict[tuple[str, str, str], str | None] = {}


@dataclass(frozen=True)
class PromptRuntimeMetadata:
    prompt_name: str
    prompt_alias: str
    prompt_version: str
    prompt_hash: str
    prompt_source: str
    prompt_registry_error: str | None = None


def observability_enabled(settings: Settings) -> bool:
    return bool(settings.chatbot_observability_enabled)


def observability_status(settings: Settings) -> dict[str, Any]:
    prompt_metadata = resolve_prompt_metadata(settings)
    latest_report = latest_release_report(settings)
    enabled = observability_enabled(settings)
    return {
        "observability_enabled": enabled,
        "observability_configured": enabled,
        "mlflow_tracking_uri": settings.mlflow_tracking_uri,
        "mlflow_experiment_name": settings.mlflow_experiment_name,
        "mlflow_prompt_name": prompt_metadata.prompt_name,
        "mlflow_prompt_alias": prompt_metadata.prompt_alias,
        "mlflow_prompt_version": prompt_metadata.prompt_version,
        "mlflow_prompt_hash": prompt_metadata.prompt_hash,
        "mlflow_prompt_source": prompt_metadata.prompt_source,
        "mlflow_prompt_registry_error": prompt_metadata.prompt_registry_error,
        "chatbot_telemetry_schema": settings.chatbot_telemetry_schema,
        "chatbot_eval_report_only": settings.chatbot_eval_report_only,
        "chatbot_eval_llm_judges_enabled": settings.chatbot_eval_llm_judges_enabled,
        "chatbot_eval_enforce": settings.chatbot_eval_enforce,
        "last_evaluation_summary": latest_report,
    }


def resolve_prompt_metadata(settings: Settings, fallback_template: str | None = None) -> PromptRuntimeMetadata:
    cache_key = (settings.mlflow_prompt_name, settings.mlflow_prompt_alias, settings.mlflow_tracking_uri)
    if cache_key in _PROMPT_CACHE:
        cached = _PROMPT_CACHE[cache_key]
        if cached.prompt_source == "mlflow" or fallback_template is None:
            return cached
    template = load_registered_prompt_template(settings)
    if template:
        metadata = _prompt_metadata_from_template(settings, template, source="mlflow")
        _PROMPT_CACHE[cache_key] = metadata
        return metadata
    metadata = _prompt_metadata_from_template(settings, fallback_template or "", source="local")
    _PROMPT_CACHE[cache_key] = metadata
    return metadata


def load_registered_prompt_template(settings: Settings) -> str | None:
    if not observability_enabled(settings):
        return None
    cache_key = (settings.mlflow_prompt_name, settings.mlflow_prompt_alias, settings.mlflow_tracking_uri)
    if cache_key in _PROMPT_TEMPLATE_CACHE:
        return _PROMPT_TEMPLATE_CACHE[cache_key]
    try:
        import mlflow

        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        prompt = mlflow.genai.load_prompt(f"prompts:/{settings.mlflow_prompt_name}@{settings.mlflow_prompt_alias}")
        template = _prompt_template(prompt)
        _PROMPT_TEMPLATE_CACHE[cache_key] = template
        return template
    except Exception as exc:  # pragma: no cover - depends on Databricks/MLflow runtime
        logger.warning("MLflow Prompt Registry fallback for %s: %s", settings.mlflow_prompt_name, exc)
        _PROMPT_TEMPLATE_CACHE[cache_key] = None
        return None


def record_turn_observability(settings: Settings, trace_payload: dict[str, Any]) -> dict[str, Any]:
    if not observability_enabled(settings):
        return {
            "mlflow_trace_id": trace_payload.get("trace_id"),
            "mlflow_run_id": None,
            "observability_status": "disabled",
            "observability_error": None,
        }
    result = {
        "mlflow_trace_id": trace_payload.get("trace_id"),
        "mlflow_run_id": None,
        "observability_status": "logged",
        "observability_error": None,
    }
    try:
        result.update(_log_mlflow_turn(settings, trace_payload))
    except Exception as exc:  # pragma: no cover - depends on Databricks/MLflow runtime
        result["observability_status"] = "mlflow_error"
        result["observability_error"] = str(exc)
        logger.warning("MLflow trace logging failed for %s: %s", trace_payload.get("trace_id"), exc)
    try:
        append_turn_trace(settings, {**trace_payload, **result})
    except Exception as exc:  # pragma: no cover - depends on Databricks SQL runtime
        result["observability_status"] = (
            "telemetry_error" if result["observability_status"] == "logged" else result["observability_status"]
        )
        result["observability_error"] = str(exc)
        logger.warning("Telemetry append failed for %s: %s", trace_payload.get("trace_id"), exc)
    return result


def append_turn_trace(settings: Settings, trace_payload: dict[str, Any]) -> None:
    if settings.chatbot_conversation_backend != "databricks_sql":
        return
    client = DatabricksSQLWarehouseClient(settings)
    table_name = sql_table_name(settings.databricks_catalog_name, settings.chatbot_telemetry_schema, "agent_turn_traces")
    client.fetch_dataframe(
        f"""
INSERT INTO {table_name} (
  trace_id, conversation_id, turn_id, created_at, mode, briefing_type, ready,
  status_text, skill_id, skill_hash, context_snapshot_hash, prompt_name,
  prompt_alias, prompt_version, prompt_hash, llm_provider, llm_tier, model_endpoint_name,
  retriever_backend, ai_search_index_name, latency_ms, citation_count,
  retrieved_chunk_ids_json, tool_calls_json, validation_json, telemetry_json
) VALUES (
  {sql_literal(trace_payload.get("trace_id"))},
  {sql_literal(trace_payload.get("conversation_id"))},
  {sql_literal(trace_payload.get("turn_id"))},
  current_timestamp(),
  {sql_literal(trace_payload.get("mode"))},
  {sql_literal(trace_payload.get("briefing_type"))},
  {sql_literal(bool(trace_payload.get("ready")))},
  {sql_literal(trace_payload.get("status_text"))},
  {sql_literal(trace_payload.get("skill_id"))},
  {sql_literal(trace_payload.get("skill_hash"))},
  {sql_literal(trace_payload.get("context_snapshot_hash"))},
  {sql_literal(trace_payload.get("prompt_name"))},
  {sql_literal(trace_payload.get("prompt_alias"))},
  {sql_literal(trace_payload.get("prompt_version"))},
  {sql_literal(trace_payload.get("prompt_hash"))},
  {sql_literal(trace_payload.get("llm_provider"))},
  {sql_literal(trace_payload.get("llm_tier"))},
  {sql_literal(trace_payload.get("model_endpoint_name"))},
  {sql_literal(trace_payload.get("retriever_backend"))},
  {sql_literal(trace_payload.get("ai_search_index_name"))},
  {sql_literal(int(trace_payload.get("latency_ms") or 0))},
  {sql_literal(int(trace_payload.get("citation_count") or 0))},
  {sql_literal(_json_dumps(trace_payload.get("retrieved_chunk_ids") or []))},
  {sql_literal(_json_dumps(trace_payload.get("agent_tool_calls") or []))},
  {sql_literal(_json_dumps(trace_payload.get("validation") or {}))},
  {sql_literal(_json_dumps(trace_payload))}
)
""".strip()
    )


def record_feedback_observability(settings: Settings, feedback_payload: dict[str, Any]) -> None:
    if not observability_enabled(settings) or settings.chatbot_conversation_backend != "databricks_sql":
        return
    try:
        client = DatabricksSQLWarehouseClient(settings)
        table_name = sql_table_name(
            settings.databricks_catalog_name,
            settings.chatbot_telemetry_schema,
            "agent_feedback_events",
        )
        client.fetch_dataframe(
            f"""
INSERT INTO {table_name} (
  feedback_id, conversation_id, turn_id, rating, comment, created_at, feedback_json
) VALUES (
  {sql_literal(feedback_payload.get("feedback_id"))},
  {sql_literal(feedback_payload.get("conversation_id"))},
  {sql_literal(feedback_payload.get("turn_id"))},
  {sql_literal(feedback_payload.get("rating"))},
  {sql_literal(feedback_payload.get("comment"))},
  current_timestamp(),
  {sql_literal(_json_dumps(feedback_payload))}
)
""".strip()
        )
    except Exception as exc:  # pragma: no cover - depends on Databricks SQL runtime
        logger.warning("Feedback telemetry append failed for %s: %s", feedback_payload.get("feedback_id"), exc)


def latest_release_report(settings: Settings) -> dict[str, Any] | None:
    if not observability_enabled(settings) or settings.chatbot_conversation_backend != "databricks_sql":
        return None
    try:
        client = DatabricksSQLWarehouseClient(settings)
        table_name = sql_table_name(
            settings.databricks_catalog_name,
            settings.chatbot_telemetry_schema,
            "agent_release_reports",
        )
        frame = client.fetch_dataframe(
            f"""
SELECT report_id, created_at, release_status, report_only, metrics_json, report_json
FROM {table_name}
ORDER BY created_at DESC
LIMIT 1
""".strip()
        )
        if frame.empty:
            return None
        row = frame.iloc[0]
        return {
            "report_id": row.get("report_id"),
            "created_at": str(row.get("created_at") or ""),
            "release_status": row.get("release_status"),
            "report_only": bool(row.get("report_only")),
            "metrics": _json_loads(row.get("metrics_json"), {}),
        }
    except Exception as exc:  # pragma: no cover - status must remain non-fatal
        logger.warning("Latest release report lookup failed: %s", exc)
        return None


def context_hash(payload: dict[str, Any]) -> str:
    return _hash_text(_json_dumps(payload))


def prompt_hash(template: str) -> str:
    return _hash_text(template or "")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _log_mlflow_turn(settings: Settings, trace_payload: dict[str, Any]) -> dict[str, Any]:
    import mlflow

    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(settings.mlflow_experiment_name)
    with mlflow.start_run(run_name=str(trace_payload.get("trace_id") or "chatbot-turn"), nested=True) as run:
        params = {
            "conversation_id": trace_payload.get("conversation_id"),
            "turn_id": trace_payload.get("turn_id"),
            "skill_id": trace_payload.get("skill_id"),
            "skill_hash": trace_payload.get("skill_hash"),
            "prompt_name": trace_payload.get("prompt_name"),
            "prompt_alias": trace_payload.get("prompt_alias"),
            "prompt_version": trace_payload.get("prompt_version"),
            "prompt_hash": trace_payload.get("prompt_hash"),
            "llm_provider": trace_payload.get("llm_provider"),
            "llm_tier": trace_payload.get("llm_tier"),
            "model_endpoint_name": trace_payload.get("model_endpoint_name"),
            "retriever_backend": trace_payload.get("retriever_backend"),
            "ai_search_index_name": trace_payload.get("ai_search_index_name"),
        }
        mlflow.log_params({key: str(value)[:250] for key, value in params.items() if value is not None})
        mlflow.log_metrics(
            {
                "latency_ms": float(trace_payload.get("latency_ms") or 0),
                "citation_count": float(trace_payload.get("citation_count") or 0),
                "tool_call_count": float(len(trace_payload.get("agent_tool_calls") or [])),
                "ready": 1.0 if trace_payload.get("ready") else 0.0,
                "citation_valid": 1.0
                if (trace_payload.get("validation") or {}).get("citation_validation", {}).get("valid")
                else 0.0,
                "compliance_valid": 1.0
                if (trace_payload.get("validation") or {}).get("compliance_validation", {}).get("valid")
                else 0.0,
            }
        )
        mlflow.log_dict(trace_payload, "chatbot_turn_trace.json")
        return {"mlflow_run_id": run.info.run_id, "mlflow_trace_id": trace_payload.get("trace_id")}


def _prompt_metadata_from_template(settings: Settings, template: str, *, source: str) -> PromptRuntimeMetadata:
    version = "local"
    error = None
    if source == "mlflow":
        version = _prompt_version(settings) or settings.mlflow_prompt_alias
    elif observability_enabled(settings):
        error = "Prompt Registry unavailable; using local prompt template."
    return PromptRuntimeMetadata(
        prompt_name=settings.mlflow_prompt_name,
        prompt_alias=settings.mlflow_prompt_alias,
        prompt_version=version,
        prompt_hash=prompt_hash(template),
        prompt_source=source,
        prompt_registry_error=error,
    )


def _prompt_template(prompt: Any) -> str | None:
    template = getattr(prompt, "template", None)
    if template is None and isinstance(prompt, dict):
        template = prompt.get("template")
    if isinstance(template, list):
        return _json_dumps(template)
    if template:
        return str(template)
    return None


def _prompt_version(settings: Settings) -> str | None:
    try:
        import mlflow

        prompt = mlflow.genai.load_prompt(f"prompts:/{settings.mlflow_prompt_name}@{settings.mlflow_prompt_alias}")
        version = getattr(prompt, "version", None)
        return str(version) if version is not None else None
    except Exception:
        return None


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value in {None, ""}:
        return default
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return default


def _hash_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:16]
