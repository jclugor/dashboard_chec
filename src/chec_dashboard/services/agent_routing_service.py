from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any

from chec_dashboard.core.config import Settings
from chec_dashboard.services.agent_context_service import (
    json_clean,
    normalize_text,
    get_asset_context_tool,
    get_circuit_history_tool,
    get_compliance_context_tool,
    get_dashboard_context_tool,
    get_event_context_tool,
    get_reliability_summary_tool,
)
from chec_dashboard.services.retrieval_service import (
    retriever_backend,
    retrieve_chatbot_chunks,
)
from chec_dashboard.services.skill_service import SkillResolution
from chec_dashboard.services.timeseries_interpretability.context_tool import (
    get_timeseries_interpretability_context_tool,
)


RUNTIME_AGENT_TOOLS = {
    "get_dashboard_context",
    "get_reliability_summary",
    "get_compliance_context",
    "get_event_context",
    "get_asset_context",
    "get_circuit_history",
    "get_timeseries_interpretability_context",
    "search_technical_documents",
    "search_regulatory_documents",
}

DOCUMENT_SEARCH_TOOLS = {"search_technical_documents", "search_regulatory_documents"}
STRUCTURED_CONTEXT_TOOLS = RUNTIME_AGENT_TOOLS - DOCUMENT_SEARCH_TOOLS

_REGULATORY_TERMS = {
    "creg",
    "retie",
    "regulatorio",
    "regulatoria",
    "regulacion",
    "regulación",
    "norma",
    "normativo",
    "normativa",
    "requisito",
    "cumplimiento",
    "calidad",
    "uiti",
    "impacto",
}
_TECHNICAL_DOC_TERMS = {
    "documento",
    "evidencia",
    "cita",
    "citar",
    "manual",
    "indicador",
    "indicadores",
    "tecnico",
    "técnico",
    "mantenimiento",
    "inspeccion",
    "inspección",
    "condiciones",
    "viento",
    "red",
    "revision",
    "revisión",
    "campo",
    "activo",
}
_DASHBOARD_TERMS = {
    "dashboard",
    "vista",
    "kpi",
    "indicador",
    "indicadores",
    "municipio",
    "periodo",
    "período",
    "concentracion",
    "concentración",
    "valores",
}
_RELIABILITY_TERMS = {
    "confiabilidad",
    "uiti",
    "impacto",
    "recurrencia",
    "recurrente",
    "historico",
    "histórico",
    "circuitos",
}
_COMPLIANCE_TERMS = {
    "cumplimiento",
    "regulatorio",
    "regulatoria",
    "norma",
    "requisito",
    "riesgo",
    "creg",
    "retie",
}
_EVENT_TERMS = {
    "evento",
    "falla",
    "causa",
    "duracion",
    "duración",
    "interrupcion",
    "interrupción",
}
_ASSET_TERMS = {
    "activo",
    "equipo",
    "transformador",
    "apoyo",
    "seccionador",
    "linea",
    "línea",
    "revisar",
    "revision",
    "revisión",
}
_CIRCUIT_HISTORY_TERMS = {
    "historial",
    "historico",
    "histórico",
    "recurrencia",
    "recurrente",
    "circuito",
}
_TIMESERIES_TERMS = {
    "evolucion",
    "evolución",
    "serie",
    "tendencia",
    "pico",
    "picos",
    "anomalia",
    "anomalía",
    "critico",
    "crítico",
    "criticos",
    "críticos",
    "uiti",
    "impacto",
}


@dataclass(frozen=True)
class AgentToolCandidate:
    tool_name: str
    reason: str


@dataclass
class AgentRouteExecution:
    context_package: dict[str, Any]
    chunks: list[dict[str, Any]] = field(default_factory=list)
    agent_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    agent_skipped_tools: list[dict[str, Any]] = field(default_factory=list)
    agent_route_summary: dict[str, Any] = field(default_factory=dict)

    @property
    def documents_requested(self) -> bool:
        return bool(self.agent_route_summary.get("documents_requested"))

    @property
    def documents_executed(self) -> bool:
        return any(call.get("tool_name") in DOCUMENT_SEARCH_TOOLS for call in self.agent_tool_calls)


def execute_agent_route(
    settings: Settings,
    *,
    selected_context: dict[str, Any],
    context_package: dict[str, Any],
    question: str | None,
    briefing_type: str,
    question_id: str | None,
    skill_resolution: SkillResolution,
    conversation_history: list[dict[str, Any]] | None = None,
) -> AgentRouteExecution:
    candidates = _dedupe_candidates(
        route_agent_tools(
            selected_context=selected_context,
            context_package=context_package,
            question=question,
            briefing_type=briefing_type,
            question_id=question_id,
            conversation_history=conversation_history,
        )
    )
    allowed_tools = set(skill_resolution.skill.allowed_tools or [])
    context_with_evidence = dict(context_package)
    executed_calls: list[dict[str, Any]] = []
    skipped_tools: list[dict[str, Any]] = []
    tool_evidence: list[dict[str, Any]] = []
    document_candidates: list[AgentToolCandidate] = []

    for candidate in candidates:
        if candidate.tool_name not in RUNTIME_AGENT_TOOLS:
            skipped_tools.append(
                _skipped_tool(candidate.tool_name, "unsupported_tool", candidate.reason)
            )
            continue
        if candidate.tool_name not in allowed_tools:
            skipped_tools.append(
                _skipped_tool(candidate.tool_name, "blocked_by_skill_policy", candidate.reason)
            )
            continue
        if candidate.tool_name in DOCUMENT_SEARCH_TOOLS:
            document_candidates.append(candidate)
            continue

        payload, skip_reason = _execute_structured_tool(
            settings,
            tool_name=candidate.tool_name,
            selected_context=selected_context,
            context_package=context_package,
        )
        if skip_reason:
            skipped_tools.append(_skipped_tool(candidate.tool_name, skip_reason, candidate.reason))
            continue
        if not payload:
            skipped_tools.append(_skipped_tool(candidate.tool_name, "empty_tool_payload", candidate.reason))
            continue
        evidence = _bounded_tool_evidence(payload)
        tool_evidence.append(evidence)
        executed_calls.append(_tool_call_trace(candidate.tool_name, candidate.reason, evidence))

    if tool_evidence:
        context_with_evidence["agent_tool_evidence"] = tool_evidence

    chunks: list[dict[str, Any]] = []
    document_tool = document_candidates[0] if document_candidates else None
    if document_tool is not None:
        chunks = retrieve_chatbot_chunks(
            settings,
            selected_context=context_with_evidence,
            question=question,
            skill_resolution=skill_resolution,
        )
        executed_calls.append(
            _document_tool_trace(
                document_tool.tool_name,
                document_tool.reason,
                chunks=chunks,
                settings=settings,
            )
        )

    route_summary = _route_summary(
        candidates=candidates,
        executed_calls=executed_calls,
        skipped_tools=skipped_tools,
        documents_requested=any(candidate.tool_name in DOCUMENT_SEARCH_TOOLS for candidate in candidates),
    )
    context_with_evidence["agent_route_summary"] = route_summary
    return AgentRouteExecution(
        context_package=context_with_evidence,
        chunks=chunks,
        agent_tool_calls=executed_calls,
        agent_skipped_tools=skipped_tools,
        agent_route_summary=route_summary,
    )


def route_agent_tools(
    *,
    selected_context: dict[str, Any],
    context_package: dict[str, Any],
    question: str | None,
    briefing_type: str,
    question_id: str | None,
    conversation_history: list[dict[str, Any]] | None = None,
) -> list[AgentToolCandidate]:
    text = _routing_text(
        selected_context=selected_context,
        context_package=context_package,
        question=question,
        briefing_type=briefing_type,
        question_id=question_id,
        conversation_history=conversation_history,
    )
    context_kind = str(
        selected_context.get("kind")
        or selected_context.get("context_kind")
        or context_package.get("context_kind")
        or ""
    ).lower()
    candidates: list[AgentToolCandidate] = []
    if _direct_answer_question(question):
        return candidates

    if context_kind == "view" or _contains_any(text, _DASHBOARD_TERMS):
        candidates.append(AgentToolCandidate("get_dashboard_context", "La pregunta usa KPIs o vista de dashboard."))
    if briefing_type == "reliability" and _contains_any(text, _RELIABILITY_TERMS):
        candidates.append(AgentToolCandidate("get_reliability_summary", "La pregunta pide indicadores de confiabilidad."))
    if briefing_type == "compliance" or _contains_any(text, _COMPLIANCE_TERMS):
        candidates.append(AgentToolCandidate("get_compliance_context", "La pregunta requiere contexto de cumplimiento."))
    if context_kind == "event" or _contains_any(text, _EVENT_TERMS):
        candidates.append(AgentToolCandidate("get_event_context", "La pregunta se refiere a un evento o falla."))
    if context_kind == "asset" or _contains_any(text, _ASSET_TERMS):
        candidates.append(AgentToolCandidate("get_asset_context", "La pregunta se refiere a un activo o revision de campo."))
    if _contains_any(text, _CIRCUIT_HISTORY_TERMS) and _selected_circuit(selected_context, context_package, question):
        candidates.append(AgentToolCandidate("get_circuit_history", "La pregunta pide historial o recurrencia del circuito."))
    if context_kind == "timeseries_criticality" or _contains_any(text, _TIMESERIES_TERMS):
        candidates.append(
            AgentToolCandidate(
                "get_timeseries_interpretability_context",
                "La pregunta pide explicar la evolucion temporal del impacto UITI o un punto critico.",
            )
        )

    if _contains_any(text, _REGULATORY_TERMS):
        candidates.append(
            AgentToolCandidate("search_regulatory_documents", "La pregunta necesita evidencia normativa o regulatoria.")
        )
    elif _contains_any(text, _TECHNICAL_DOC_TERMS):
        candidates.append(
            AgentToolCandidate("search_technical_documents", "La pregunta necesita evidencia tecnica del corpus.")
        )

    return candidates


def _dedupe_candidates(candidates: list[AgentToolCandidate]) -> list[AgentToolCandidate]:
    seen: set[str] = set()
    unique: list[AgentToolCandidate] = []
    for candidate in candidates:
        if candidate.tool_name in seen:
            continue
        seen.add(candidate.tool_name)
        unique.append(candidate)
    return unique


def _routing_text(
    *,
    selected_context: dict[str, Any],
    context_package: dict[str, Any],
    question: str | None,
    briefing_type: str,
    question_id: str | None,
    conversation_history: list[dict[str, Any]] | None,
) -> str:
    history_text = " ".join(
        str(message.get("content") or "")[:500]
        for message in (conversation_history or [])[-4:]
        if isinstance(message, dict)
    )
    payload = {
        "question": question,
        "briefing_type": briefing_type,
        "question_id": question_id,
        "selected_context": selected_context,
        "context_identity": context_package.get("selected_context"),
        "history": history_text,
    }
    return normalize_text(json.dumps(payload, ensure_ascii=False, default=str))


def _contains_any(text: str, terms: set[str]) -> bool:
    normalized_terms = {normalize_text(term) for term in terms}
    tokens = set(text.split())
    return bool(tokens & normalized_terms)


def _direct_answer_question(question: str | None) -> bool:
    tokens = set(normalize_text(question or "").split())
    if not tokens:
        return False
    direct_tokens = {
        "ok",
        "gracias",
        "listo",
        "continua",
        "continue",
        "resume",
        "resumen",
        "anterior",
        "eso",
    }
    return tokens <= direct_tokens


def _execute_structured_tool(
    settings: Settings,
    *,
    tool_name: str,
    selected_context: dict[str, Any],
    context_package: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    try:
        if tool_name in {"get_dashboard_context", "get_reliability_summary", "get_compliance_context"}:
            scope = _dashboard_scope(selected_context, context_package)
            if not scope:
                return {}, "missing_dashboard_scope"
            if tool_name == "get_dashboard_context":
                return get_dashboard_context_tool(settings, **scope), None
            if tool_name == "get_reliability_summary":
                return get_reliability_summary_tool(settings, **scope), None
            return get_compliance_context_tool(settings, **scope), None
        if tool_name == "get_event_context":
            event_id = _context_value(selected_context, context_package, "event_id")
            if not event_id:
                event_id = _context_value(selected_context, context_package, "context_id")
            if not event_id:
                return {}, "missing_event_id"
            return get_event_context_tool(
                settings,
                event_id=str(event_id),
                fallback_context=selected_context,
            ), None
        if tool_name == "get_asset_context":
            asset_id = _context_value(selected_context, context_package, "asset_id")
            if not asset_id:
                asset_id = _context_value(selected_context, context_package, "CODE", "equipo_ope", "context_id")
            if not asset_id:
                return {}, "missing_asset_id"
            return get_asset_context_tool(
                settings,
                asset_id=str(asset_id),
                fallback_context=selected_context,
            ), None
        if tool_name == "get_circuit_history":
            circuit = _selected_circuit(selected_context, context_package, None)
            if not circuit:
                return {}, "missing_circuit"
            start_date, end_date = _selected_date_bounds(selected_context, context_package)
            return get_circuit_history_tool(
                settings,
                circuit=circuit,
                start_date=start_date,
                end_date=end_date,
            ), None
        if tool_name == "get_timeseries_interpretability_context":
            selected_date = _context_value(selected_context, context_package, "selected_date", "fecha_dia")
            return get_timeseries_interpretability_context_tool(
                settings,
                selected_context=selected_context,
                context_package=context_package,
                selected_date=str(selected_date) if selected_date else None,
            ), None
    except Exception:
        return {}, "tool_execution_error"
    return {}, "unsupported_tool"


def _dashboard_scope(
    selected_context: dict[str, Any],
    context_package: dict[str, Any],
) -> dict[str, Any] | None:
    selected_period = _context_value(selected_context, context_package, "selected_period", "map_period", "period")
    selected_municipio = _context_value(selected_context, context_package, "selected_municipio", "MUN", "municipio")
    if not selected_period or not selected_municipio:
        return None
    selected_circuits = _selected_circuits(selected_context, context_package)
    return {
        "selected_period": str(selected_period),
        "selected_municipio": str(selected_municipio),
        "selected_circuits": selected_circuits,
    }


def _selected_circuits(
    selected_context: dict[str, Any],
    context_package: dict[str, Any],
) -> list[str] | None:
    raw = _context_value(selected_context, context_package, "selected_circuits")
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    if isinstance(raw, str) and raw.strip():
        if raw.strip().lower() in {"todos", "todos los circuitos"}:
            return None
        return [part.strip() for part in raw.split(",") if part.strip()]
    circuit = _selected_circuit(selected_context, context_package, None)
    return [circuit] if circuit else None


def _selected_circuit(
    selected_context: dict[str, Any],
    context_package: dict[str, Any],
    question: str | None,
) -> str | None:
    if question:
        match = re.search(r"\b[A-Z]{2,6}-\d+\b", question.upper())
        if match:
            return match.group(0)
    for key in ("cto_equi_ope", "circuito", "FPARENT", "circuit", "scope_label"):
        value = _context_value(selected_context, context_package, key)
        if isinstance(value, str) and value.strip() and value.strip().lower() not in {"todos", "todos los circuitos"}:
            first = value.split(",")[0].strip()
            if first:
                return first
    return None


def _selected_date_bounds(
    selected_context: dict[str, Any],
    context_package: dict[str, Any],
) -> tuple[str, str]:
    bounds = _context_value(selected_context, context_package, "date_bounds")
    if isinstance(bounds, dict):
        start = bounds.get("start")
        end = bounds.get("end")
        if start and end:
            return str(start)[:10], str(end)[:10]
    start = _context_value(selected_context, context_package, "inicio", "inicio_ts", "map_date")
    end = _context_value(selected_context, context_package, "fin", "fin_ts", "map_date")
    if start and end:
        return str(start)[:10], str(end)[:10]
    selected_period = _context_value(selected_context, context_package, "selected_period", "map_period", "period")
    if isinstance(selected_period, str) and re.match(r"^\d{4}-\d{2}$", selected_period):
        year, month = (int(part) for part in selected_period.split("-"))
        last_day = monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"
    return "1900-01-01", "2999-12-31"


def _context_value(
    selected_context: dict[str, Any],
    context_package: dict[str, Any],
    *keys: str,
) -> Any:
    sources = [
        selected_context,
        context_package.get("selected_context") if isinstance(context_package.get("selected_context"), dict) else {},
        context_package.get("structured_context_tool") if isinstance(context_package.get("structured_context_tool"), dict) else {},
        context_package,
    ]
    for key in keys:
        for source in sources:
            value = source.get(key) if isinstance(source, dict) else None
            if value not in (None, ""):
                return value
    return None


def _bounded_tool_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    evidence = {
        "tool_name": payload.get("tool_name"),
        "source_function": payload.get("source_function"),
        "source_view": payload.get("source_view"),
        "parameters": payload.get("parameters") or {},
        "summary": payload.get("summary") or {},
        "records": (payload.get("records") or [])[:8],
        "metrics": payload.get("metrics") or {},
        "traceability": payload.get("traceability") or {},
        "context_id": payload.get("context_id"),
        "context_hash": payload.get("context_hash"),
    }
    return _truncate_strings(json_clean(evidence))


def _truncate_strings(value: Any, *, limit: int = 1200) -> Any:
    if isinstance(value, dict):
        return {str(key): _truncate_strings(item, limit=limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate_strings(item, limit=limit) for item in value[:20]]
    if isinstance(value, str):
        return value[:limit]
    return value


def _tool_call_trace(tool_name: str, reason: str, evidence: dict[str, Any]) -> dict[str, Any]:
    records = evidence.get("records") if isinstance(evidence.get("records"), list) else []
    metrics = evidence.get("metrics") if isinstance(evidence.get("metrics"), dict) else {}
    traceability = evidence.get("traceability") if isinstance(evidence.get("traceability"), dict) else {}
    return {
        "tool_name": tool_name,
        "status": "executed",
        "reason": reason,
        "evidence_count": len(records),
        "context_id": evidence.get("context_id"),
        "context_hash": evidence.get("context_hash"),
        "source_function": evidence.get("source_function"),
        "source_view": evidence.get("source_view"),
        "read_only": traceability.get("read_only", True),
        "metric_keys": sorted(str(key) for key in metrics.keys())[:12],
    }


def _document_tool_trace(
    tool_name: str,
    reason: str,
    *,
    chunks: list[dict[str, Any]],
    settings: Settings,
) -> dict[str, Any]:
    chunk_ids = [str(chunk.get("chunk_id")) for chunk in chunks if chunk.get("chunk_id")]
    digest = hashlib.sha256("|".join(chunk_ids).encode("utf-8")).hexdigest()[:16] if chunk_ids else None
    source_view = (
        settings.ai_search_index_name
        if retriever_backend(settings) == "databricks_ai_search"
        else str(settings.chatbot_corpus_dir / "chunks.jsonl")
    )
    return {
        "tool_name": tool_name,
        "status": "executed",
        "reason": reason,
        "evidence_count": len(chunks),
        "context_id": f"retrieval-{digest}" if digest else None,
        "context_hash": digest,
        "source_function": "configured_retriever",
        "source_view": source_view,
        "read_only": True,
        "retriever_backend": retriever_backend(settings),
    }


def _skipped_tool(tool_name: str, status: str, reason: str) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "status": "skipped",
        "skip_reason": status,
        "reason": reason,
    }


def _route_summary(
    *,
    candidates: list[AgentToolCandidate],
    executed_calls: list[dict[str, Any]],
    skipped_tools: list[dict[str, Any]],
    documents_requested: bool,
) -> dict[str, Any]:
    executed_tool_names = [str(call.get("tool_name")) for call in executed_calls if call.get("tool_name")]
    skipped_tool_names = [str(tool.get("tool_name")) for tool in skipped_tools if tool.get("tool_name")]
    requested_tool_names = [candidate.tool_name for candidate in candidates]
    if not requested_tool_names:
        route_mode = "direct_answer"
        route_reason = "La pregunta se puede responder con contexto existente e historial reciente."
    elif documents_requested and executed_tool_names:
        route_mode = "tool_augmented_retrieval"
        route_reason = "Se combinaron herramientas gobernadas y recuperacion documental."
    elif executed_tool_names:
        route_mode = "tool_augmented_context"
        route_reason = "Se agrego contexto estructurado gobernado antes de generar."
    else:
        route_mode = "policy_limited"
        route_reason = "Las herramientas propuestas no se ejecutaron por politica o parametros faltantes."
    return {
        "route_mode": route_mode,
        "route_reason": route_reason,
        "requested_tools": requested_tool_names,
        "executed_tools": executed_tool_names,
        "skipped_tools": skipped_tool_names,
        "documents_requested": documents_requested,
        "direct_answer": route_mode == "direct_answer",
        "read_only": True,
    }


_route_agent_tools = route_agent_tools
_execute_agent_route = execute_agent_route
