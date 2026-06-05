# Upgrade Plan: SAIDI/SAIFI Time-Evolution Interpretability

**Project:** CHEC Dashboard  
**Feature area:** Summary tab, SAIDI/SAIFI time-evolution interpretability  
**Plan version:** 1.0  
**Prepared on:** 2026-06-05  
**Primary goal:** Upgrade the current implementation from “deterministic detection + plain LLM text” to an auditable, structured, evidence-backed interpretability workflow.

---

## 1. Executive Summary

The current implementation correctly follows the most important principle from the original plan:

> Detect criticality with transparent deterministic rules, then ask the LLM to explain only those computed facts using structured data and retrieved evidence.

The project already has useful foundations:

- deterministic time-series feature generation in `time_series_interpretability_service.py`,
- point-level and period-level criticality detection,
- event attribution hydration,
- Databricks candidate-date queries,
- chart markers in the summary page,
- an optional LLM explanation path,
- skill-based governance for the existing chatbot flows.

However, the current output and orchestration still feel plain because the LLM layer is attached as a generic text generator. The current function `attach_interpretability_agent_text()` resolves the generic reliability skill, retrieves chunks using a broad question, builds the generic chatbot prompt, and returns one free-form `insight_text` string.

This upgrade should convert the feature into a first-class, structured workflow:

```text
SAIDI/SAIFI daily series
  -> deterministic feature generation
  -> deterministic criticality detection
  -> event and environment attribution
  -> compact interpretability context package
  -> deterministic retrieval-query builder
  -> dedicated skill + dedicated prompt
  -> structured LLM narrative
  -> validation gate
  -> deterministic fallback
  -> rich UI renderer
  -> trace/evaluation logging
```

The recommended end state is **not** a more autonomous agent. It is an explicit, auditable workflow with a narrow LLM role: produce a Spanish narrative from already-computed points, evidence, and documents.

---

## 2. External Architecture References

These references support the design choices in this plan.

| Topic | Source | Why it matters for this upgrade |
|---|---|---|
| Workflow vs agent design | Anthropic, “Building Effective Agents” — https://www.anthropic.com/engineering/building-effective-agents | Recommends simple workflows when steps are predictable; evaluator/optimizer patterns are useful when criteria are clear. |
| Low-level agent orchestration | LangGraph overview — https://docs.langchain.com/oss/python/langgraph/overview | Useful later if this grows into durable, stateful, human-in-the-loop workflows; not required for the first upgrade. |
| Tool/function calling | OpenAI Function Calling docs — https://developers.openai.com/api/docs/guides/function-calling | Supports explicit tool contracts and structured access to application data. |
| Structured outputs | OpenAI model guidance — https://developers.openai.com/api/docs/guides/latest-model | Recommends structured outputs when the application needs reliable contracts and UI-driven responses. |
| RAG architecture | Databricks RAG guide — https://docs.databricks.com/aws/en/generative-ai/retrieval-augmented-generation | Defines the retrieval, augmentation, generation flow and source-citation benefit for proprietary/domain data. |
| Agent deployment on Databricks | Databricks agent authoring guide — https://docs.databricks.com/aws/en/generative-ai/agent-framework/author-agent | Useful if the interpretability workflow is later wrapped as a Databricks-compatible agent with tracing and monitoring. |
| GenAI observability/evaluation | Databricks MLflow 3 for GenAI — https://docs.databricks.com/aws/en/mlflow3/genai/ | Supports tracing, custom scorers, human feedback, versioning, and production monitoring. |

---

## 3. Current State Review

### 3.1 Current files involved

The current implementation already touches these files:

```text
docs/saidi_saifi_time_evolution_interpretability_plan.md
src/chec_dashboard/services/time_series_interpretability_service.py
src/chec_dashboard/services/time_series_interpretability_agent.py
src/chec_dashboard/services/databricks_data_service.py
src/chec_dashboard/pages/summary_page.py
src/chec_dashboard/api/schemas/responses.py
src/chec_dashboard/api/routes/data.py
src/chec_dashboard/dash_app/api_client.py
tests/test_time_series_interpretability_service.py
```

The existing agent, prompt, retrieval, and skill system lives in:

```text
src/chec_dashboard/services/agent_context_service.py
src/chec_dashboard/services/agent_orchestrator.py
src/chec_dashboard/services/agent_routing_service.py
src/chec_dashboard/services/prompt_service.py
src/chec_dashboard/services/retrieval_service.py
src/chec_dashboard/services/skill_service.py
src/chec_dashboard/services/llm_service.py
src/chec_dashboard/services/citation_service.py
src/chec_dashboard/services/answer_quality_service.py
src/chec_dashboard/agent_skills/active/
```

### 3.2 What is already good

| Area | Current implementation | Recommendation |
|---|---|---|
| Feature generation | `compute_time_series_features()` computes rolling medians, robust z-scores, deltas, contribution percentages. | Keep; move into a smaller module later. |
| Criticality detection | `detect_point_reasons()` and `detect_critical_periods()` classify critical dates and intervals. | Keep; add tests and clearer calibration docs. |
| Ranking | `rank_and_merge_critical_points()` merges and ranks points. | Keep; expose score components in trace. |
| Attribution | `enrich_critical_points_with_attribution()` attaches causes, event families, equipment, circuits, events, and external signals. | Keep; add missing-evidence flags. |
| Databricks candidate-date flow | `get_summary_interpretability_payload()` first detects candidate dates, then queries attribution/event/environment tables only for those dates. | Keep; this is efficient. |
| UI chart markers | `_apply_interpretability_markers()` annotates the Plotly chart. | Keep; enhance hover and selected-point behavior. |
| Fallback text | `deterministic_insight_text()` ensures the feature still works without the LLM. | Keep; convert to structured fallback narrative. |

### 3.3 Main problems to solve

| Problem | Current symptom | Upgrade direction |
|---|---|---|
| Output is too plain | The backend returns one free-form `insight_text`; the UI renders it as a block. | Return a structured `narrative` object and render it as sections, cards, evidence rows, gaps, and recommendations. |
| LLM orchestration is generic | `attach_interpretability_agent_text()` uses the generic reliability skill and generic chatbot prompt. | Add a dedicated skill, prompt, context package, retrieval query builder, and validator. |
| No dedicated analysis contract | There is no file that tells the LLM how to analyze SAIDI/SAIFI critical points specifically. | Add `time_series_interpretability.yml` and `time_series_interpretability.v1.md`. |
| Retrieval query is too broad | Retrieval receives a large context package and generic question. | Build a compact retrieval query from dominant facts: metric, dates, causes, equipment, circuit, municipality, event family. |
| LLM result is hard to trust | Free-form answer can introduce unsupported claims or skip missing evidence. | Use schema-constrained output and validate against deterministic payload. |
| Traceability is weak | Exceptions are swallowed; fallback has no diagnostic metadata. | Add `interpretability_trace` with mode, fallback, skill, prompt, chunks, validation, latency. |
| Runtime tool integration is incomplete | `get_timeseries_interpretability_context` appears in the context package but is not a first-class runtime tool. | Add it to skill policy and routing for follow-up chatbot questions. |

---

## 4. Target Architecture

### 4.1 Recommended pattern

Use a **deterministic workflow with a narrow LLM narrative step**.

Do not use a fully autonomous multi-agent design for the summary panel. The subtasks are known in advance, and the domain requires auditability. A graph/agent framework can be added later only if the workflow needs durable state, human approval, long-running jobs, or multi-turn follow-up orchestration.

### 4.2 Target flow

```text
Dash Summary UI
  -> POST /data mode="summary_interpretability"
    -> Databricks summary interpretability loader
      -> daily SAIDI/SAIFI query
      -> deterministic detector
      -> candidate critical dates
      -> attribution/event/environment queries
      -> deterministic payload
      -> TimeseriesInterpretabilityOrchestrator
          1. build compact context package
          2. build deterministic retrieval query
          3. resolve dedicated skill
          4. retrieve corpus chunks
          5. build dedicated prompt
          6. generate structured narrative
          7. validate narrative against payload
          8. fallback or repair if needed
          9. attach trace
    -> SummaryInterpretabilityResponse V2
  -> Dash renderer
      -> chart markers
      -> narrative summary cards
      -> critical point cards
      -> evidence matrix
      -> data gaps
      -> recommendations
```

### 4.3 Architecture principle

The LLM must never be the source of truth for:

- which dates are critical,
- which criticality types apply,
- event counts,
- SAIDI/SAIFI values,
- contribution percentages,
- dominant cause/equipment/circuit labels,
- regulatory/compliance conclusions.

The LLM may only:

- summarize the already-computed facts,
- connect points to retrieved documents,
- phrase cautious hypotheses,
- explain missing evidence,
- organize recommended follow-up actions.

---

## 5. Proposed Package Structure

Create a dedicated package so the feature stops living in one large service file.

```text
src/chec_dashboard/services/timeseries_interpretability/
  __init__.py
  contracts.py                  # Pydantic/domain models for narrative, status, trace
  features.py                   # normalize_daily_frame, compute_time_series_features, data quality
  detectors.py                  # detect_point_reasons, detect_critical_periods, ranking
  attribution.py                # enrich_critical_points_with_attribution and helpers
  context_builder.py            # build_timeseries_context_package V2
  retrieval_query.py            # deterministic RAG query builder
  prompts.py                    # load/render dedicated prompt template
  deterministic_narrative.py    # structured fallback narrative
  orchestrator.py               # explicit workflow
  validators.py                 # schema, citation, overclaim, grounding checks
```

Keep this file temporarily as a compatibility facade:

```text
src/chec_dashboard/services/time_series_interpretability_service.py
```

Keep or replace this file as the public LLM bridge:

```text
src/chec_dashboard/services/time_series_interpretability_agent.py
```

Recommended compatibility strategy:

1. Add the new package.
2. Keep existing function names in `time_series_interpretability_service.py` and import the moved implementations.
3. Keep `insight_text` in API responses for one release.
4. Add `narrative`, `status`, and `interpretability_trace` beside existing fields.
5. Update the UI to prefer `narrative` and fallback to `insight_text`.

---

## 6. Backend Data Contracts

### 6.1 New narrative models

Add to:

```text
src/chec_dashboard/services/timeseries_interpretability/contracts.py
```

Recommended models:

```python
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


Confidence = Literal["high", "medium", "low"]
StatusSeverity = Literal["ok", "warning", "error"]
NarrativeSource = Literal["llm", "deterministic", "validated_repair"]


class EvidenceReference(BaseModel):
    citation_index: int | None = None
    title: str | None = None
    source_type: str | None = None
    supports: str


class PointNarrative(BaseModel):
    fecha_dia: str
    rank: int
    headline: str
    confidence: Confidence = "medium"
    why_marked: list[str] = Field(default_factory=list)
    observed_values: list[str] = Field(default_factory=list)
    likely_drivers: list[str] = Field(default_factory=list)
    documentary_support: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)
    citations_used: list[int] = Field(default_factory=list)


class EvidenceMatrixRow(BaseModel):
    fecha_dia: str | None = None
    signal: str
    structured_evidence: str
    documentary_evidence: str | None = None
    confidence: Confidence = "medium"
    citations_used: list[int] = Field(default_factory=list)


class TimeseriesInterpretabilityNarrative(BaseModel):
    source: NarrativeSource = "llm"
    headline: str
    executive_summary: list[str] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)
    point_narratives: list[PointNarrative] = Field(default_factory=list)
    period_narratives: list[str] = Field(default_factory=list)
    evidence_matrix: list[EvidenceMatrixRow] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    citations_used: list[int] = Field(default_factory=list)


class InterpretabilityStatus(BaseModel):
    text: str
    severity: StatusSeverity = "ok"
    data_quality_flags: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: str | None = None


class InterpretabilityTrace(BaseModel):
    mode: str
    fallback_used: bool = False
    fallback_reason: str | None = None
    skill_id: str | None = None
    skill_version: str | None = None
    skill_hash: str | None = None
    prompt_name: str | None = None
    prompt_version: str | None = None
    prompt_hash: str | None = None
    retrieval_query: str | None = None
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    citation_count: int = 0
    validation: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None = None
```

### 6.2 API response upgrade

Modify:

```text
src/chec_dashboard/api/schemas/responses.py
```

Current response:

```python
class SummaryInterpretabilityResponse(APIResponseModel):
    start_date: str
    end_date: str
    circuit_label: str
    metric_mode: str
    generated_at: str
    critical_points: list[CriticalPoint] = Field(default_factory=list)
    critical_periods: list[CriticalPeriod] = Field(default_factory=list)
    insight_text: str | None = None
    corpus_citations: list[dict[str, Any]] = Field(default_factory=list)
    status_text: str
```

Recommended V2-compatible response:

```python
class SummaryInterpretabilityResponse(APIResponseModel):
    start_date: str
    end_date: str
    circuit_label: str
    metric_mode: str
    generated_at: str
    critical_points: list[CriticalPoint] = Field(default_factory=list)
    critical_periods: list[CriticalPeriod] = Field(default_factory=list)

    # Backward-compatible field. UI should no longer rely on this first.
    insight_text: str | None = None

    # New fields.
    narrative: dict[str, Any] | None = None
    deterministic_narrative: dict[str, Any] | None = None
    status: dict[str, Any] | None = None
    interpretability_trace: dict[str, Any] | None = None

    corpus_citations: list[dict[str, Any]] = Field(default_factory=list)
    status_text: str
```

After the UI is migrated, consider replacing `dict[str, Any]` with full Pydantic models imported from a shared schema module.

---

## 7. Dedicated Skill File

### 7.1 Add the skill

Create:

```text
src/chec_dashboard/agent_skills/active/time_series_interpretability.yml
```

Recommended content:

```yaml
skill_id: time_series_interpretability
version: "1.0"
status: active
role: Asistente tecnico de interpretabilidad de evolucion SAIDI/SAIFI para CHEC.
language: es
tone: Claro, tecnico, prudente y orientado a evidencia.
allowed_tools:
  - get_timeseries_interpretability_context
  - search_technical_documents
  - search_regulatory_documents
instructions:
  - Explica solamente puntos, periodos y banderas ya calculadas por el sistema.
  - No detectes nuevas anomalias desde la serie cruda.
  - Separa observaciones, posibles explicaciones, evidencia documental y datos faltantes.
  - Usa valores concretos de SAIDI, SAIFI, eventos, duracion y usuarios afectados.
  - Si una causa, familia, equipo o circuito domina el dia, menciona su contribucion.
  - Si hay senales ambientales, usa lenguaje de coincidencia o asociacion operativa, no causalidad confirmada.
  - Si el corpus no aporta soporte suficiente, dilo explicitamente.
suggested_questions:
  - Que explica el punto critico principal de la evolucion SAIDI/SAIFI?
  - Que evidencia falta para confirmar la causa de los picos?
  - Que acciones operativas deberian revisarse primero?
output:
  sections:
    - Resumen ejecutivo
    - Puntos criticos
    - Evidencia de eventos
    - Evidencia documental
    - Datos faltantes
    - Recomendaciones
    - Limitaciones
    - Citas
constraints:
  must_cite_regulatory_claims: true
  cannot_make_legal_conclusions: true
  forbidden_phrases:
    - causa definitiva comprobada
    - esto demuestra que
    - incumplimiento confirmado
    - no cumple
missing_evidence_behavior: Declarar el dato faltante antes de formular una hipotesis operativa.
retrieval:
  backend: local_jsonl
  top_k: 6
  max_top_k: 8
  boost_tags:
    - SAIDI
    - SAIFI
    - confiabilidad
    - calidad_servicio
    - mantenimiento
    - interrupciones
```

### 7.2 Update skill registry

Modify:

```text
src/chec_dashboard/services/skill_service.py
```

Add the guided skill mapping:

```python
GUIDED_SKILL_IDS = {
    "reliability": "confiabilidad",
    "compliance": "cumplimiento",
    "maintenance": "mantenimiento",
    "timeseries_interpretability": "time_series_interpretability",
}
```

Add the expected file:

```python
EXPECTED_SKILL_FILES = {
    "confiabilidad": "confiabilidad.yml",
    "cumplimiento": "cumplimiento.yml",
    "mantenimiento": "mantenimiento.yml",
    "time_series_interpretability": "time_series_interpretability.yml",
    "free_form_chat": "free_form_chat.yml",
    "global_policy": "global_policy.yml",
    "retrieval_policy": "retrieval_policy.yml",
}
```

Add the tool to the allowlist:

```python
ALLOWED_TOOLS = {
    "get_dashboard_context",
    "get_reliability_summary",
    "get_compliance_context",
    "get_circuit_history",
    "search_technical_documents",
    "search_regulatory_documents",
    "get_event_context",
    "get_asset_context",
    "get_timeseries_interpretability_context",
}
```

### 7.3 Add validation tests

Add or extend tests so the new skill is loaded and validated:

```text
tests/test_skill_service.py
```

Suggested assertions:

```python
def test_timeseries_interpretability_skill_loads(settings):
    resolution = resolve_skill("timeseries_interpretability", settings)
    assert resolution.skill_id == "time_series_interpretability"
    assert "get_timeseries_interpretability_context" in resolution.skill.allowed_tools
    assert not resolution.validation_errors
```

---

## 8. Dedicated Prompt Template

### 8.1 Add prompt file

Create:

```text
src/chec_dashboard/agent_prompts/time_series_interpretability.v1.md
```

Recommended content:

```md
Eres un asistente tecnico para CHEC. Responde siempre en espanol.

Tarea:
Genera una explicacion compacta de la evolucion SAIDI/SAIFI usando unicamente:
1. El paquete estructurado de puntos criticos.
2. La atribucion de eventos.
3. Las senales externas disponibles.
4. Los documentos recuperados.

Reglas criticas:
- No detectes nuevos puntos criticos.
- No cambies los tipos de criticidad calculados.
- No afirmes causalidad definitiva.
- Distingue observacion, hipotesis operativa y dato faltante.
- Toda afirmacion documental o regulatoria debe citar indices existentes.
- Si no hay documentos utiles, marca soporte documental insuficiente.
- Devuelve solo un objeto JSON valido con el esquema configurado por la aplicacion.

Estilo:
- Claro, tecnico y prudente.
- Frases cortas.
- Prioriza fechas, valores, eventos, duracion y usuarios afectados.
- Evita relleno y conclusiones legales.

Paquete estructurado:
{{context_json}}

Documentos recuperados:
{{docs_text}}

Pregunta de analisis:
{{question_text}}
```

Important implementation detail: when using an API that supports structured outputs, keep the JSON schema in API configuration rather than duplicating the full schema in the prompt. The prompt can say that the application configures the schema.

### 8.2 Add prompt loader

Add:

```text
src/chec_dashboard/services/timeseries_interpretability/prompts.py
```

Suggested functions:

```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PROMPT_NAME = "time_series_interpretability"
PROMPT_VERSION = "1"


def prompt_path() -> Path:
    return Path(__file__).resolve().parents[2] / "agent_prompts" / "time_series_interpretability.v1.md"


def load_timeseries_prompt_template() -> str:
    return prompt_path().read_text(encoding="utf-8")


def prompt_hash(template: str) -> str:
    return hashlib.sha256(template.encode("utf-8")).hexdigest()[:16]


def render_timeseries_prompt(
    *,
    context_package: dict[str, Any],
    docs_text: str,
    question_text: str,
) -> tuple[str, dict[str, str]]:
    template = load_timeseries_prompt_template()
    values = {
        "context_json": json.dumps(context_package, ensure_ascii=False, indent=2),
        "docs_text": docs_text or "Sin documentos recuperados.",
        "question_text": question_text,
    }
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    metadata = {
        "prompt_name": PROMPT_NAME,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": prompt_hash(template),
    }
    return rendered, metadata
```

---

## 9. Context Package V2

### 9.1 Current context package issue

The current `build_timeseries_context_package()` returns a small object with:

```python
{
    "kind": "timeseries_criticality",
    "context_kind": "timeseries_criticality",
    "tool_name": "get_timeseries_interpretability_context",
    "summary": {...},
    "records": payload.get("critical_points") or [],
    "metrics": {...},
    "traceability": {...},
}
```

This is valid but too generic. It loses structure that would help retrieval, validation, and UI rendering.

### 9.2 Recommended V2 context

Add:

```text
src/chec_dashboard/services/timeseries_interpretability/context_builder.py
```

Recommended shape:

```python
def build_timeseries_context_package_v2(payload: dict[str, Any]) -> dict[str, Any]:
    points = payload.get("critical_points") or []
    periods = payload.get("critical_periods") or []
    global_flags = sorted(
        {
            flag
            for point in points
            for flag in (point.get("data_quality_flags") or [])
        }
    )

    retrieval_hints = build_retrieval_hints(points, periods)

    return {
        "tipo_analisis": "reliability",
        "nombre_analisis": "Interpretabilidad de evolucion SAIDI/SAIFI",
        "kind": "timeseries_criticality",
        "context_kind": "timeseries_criticality",
        "tool_name": "get_timeseries_interpretability_context",
        "selected_context": {
            "circuito": payload.get("circuit_label"),
            "start_date": payload.get("start_date"),
            "end_date": payload.get("end_date"),
            "metric_mode": payload.get("metric_mode"),
        },
        "window_summary": {
            "critical_point_count": len(points),
            "critical_period_count": len(periods),
            "global_data_quality_flags": global_flags,
            "status_text": payload.get("status_text"),
        },
        "critical_points": points,
        "critical_periods": periods,
        "retrieval_hints": retrieval_hints,
        "response_guardrails": {
            "do_not_detect_new_anomalies": True,
            "do_not_change_criticality_types": True,
            "do_not_claim_causality": True,
            "cite_documentary_claims": True,
            "report_missing_evidence": True,
        },
        "traceability": {
            "claim_scope": "summary_time_series_interpretability",
            "read_only": True,
            "source_tables": [
                "gold_saidi_saifi_daily",
                "gold_timeseries_daily_attribution",
                "gold_timeseries_event_details",
                "gold_timeseries_environment_daily",
            ],
        },
    }
```

### 9.3 Retrieval hints

The context builder should extract dominant values from critical points:

```python
def build_retrieval_hints(points: list[dict[str, Any]], periods: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "dominant_causes": top_labels(points, "top_causes", limit=5),
        "dominant_event_families": top_labels(points, "top_event_families", limit=5),
        "dominant_equipment": top_labels(points, "top_equipment", limit=5),
        "dominant_circuits": top_labels(points, "top_circuits", limit=5),
        "criticality_types": sorted(
            {
                item
                for point in points
                for item in (point.get("criticality_types") or [])
            }
        ),
        "period_types": sorted({period.get("period_type") for period in periods if period.get("period_type")}),
    }
```

---

## 10. Deterministic Retrieval Query Builder

### 10.1 Why this is needed

The current retrieval call receives a broad question:

```text
Explica los puntos criticos de la evolucion SAIDI/SAIFI usando solo los datos estructurados y documentos recuperados...
```

That is not enough to retrieve targeted documents. The RAG query should include the actual dominant facts:

- SAIDI / SAIFI,
- reliability / quality service terms,
- criticality types,
- dominant causes,
- event families,
- equipment,
- circuits,
- municipalities if present,
- environmental signals if present.

### 10.2 Add module

Create:

```text
src/chec_dashboard/services/timeseries_interpretability/retrieval_query.py
```

Suggested implementation:

```python
from __future__ import annotations

from typing import Any


def _append_unique(values: list[str], candidate: Any) -> None:
    text = str(candidate or "").strip()
    if text and text.lower() not in {item.lower() for item in values}:
        values.append(text)


def _collect_labels(points: list[dict[str, Any]], key: str, limit: int = 5) -> list[str]:
    labels: list[str] = []
    for point in points:
        for item in point.get(key) or []:
            _append_unique(labels, item.get("label"))
            if len(labels) >= limit:
                return labels
    return labels


def build_timeseries_retrieval_query(context_package: dict[str, Any]) -> str:
    points = context_package.get("critical_points") or []
    hints = context_package.get("retrieval_hints") or {}
    terms: list[str] = []

    for base in [
        "SAIDI",
        "SAIFI",
        "confiabilidad",
        "calidad del servicio",
        "interrupciones",
        "duracion",
        "usuarios afectados",
        "mantenimiento",
    ]:
        _append_unique(terms, base)

    for value in hints.get("criticality_types") or []:
        _append_unique(terms, value)

    for key in [
        "dominant_causes",
        "dominant_event_families",
        "dominant_equipment",
        "dominant_circuits",
    ]:
        for value in hints.get(key) or []:
            _append_unique(terms, value)

    for key in ["top_causes", "top_event_families", "top_equipment", "top_circuits"]:
        for value in _collect_labels(points, key):
            _append_unique(terms, value)

    return " ".join(terms[:40])
```

### 10.3 Retrieval trace

Store the exact query in:

```json
"interpretability_trace": {
  "retrieval_query": "SAIDI SAIFI confiabilidad calidad del servicio ..."
}
```

This helps debug poor citations.

---

## 11. Structured LLM Generation

### 11.1 Add a structured LLM method

Current `generate_llm_answer()` returns free-form text. Add a wrapper for schema-constrained generation if the configured LLM provider supports it.

Suggested function:

```text
src/chec_dashboard/services/llm_service.py
```

```python
def generate_llm_structured_answer(
    settings: Settings,
    *,
    prompt: str,
    schema_name: str,
    json_schema: dict[str, Any],
    context_package: dict[str, Any],
    question: str,
    citations: list[dict[str, Any]],
    skill_resolution: SkillResolution,
) -> dict[str, Any] | None:
    """Return parsed JSON matching json_schema when supported.

    Fallback provider behavior:
    - If structured outputs are supported, enforce schema in API parameters.
    - If not supported, request JSON-only output and parse strictly.
    - Return None on invalid JSON; do not silently accept malformed text.
    """
```

### 11.2 Avoid exposing chain-of-thought

The model should provide concise evidence rationales, not hidden reasoning. The schema should ask for:

- `why_marked`,
- `observed_values`,
- `likely_drivers`,
- `missing_evidence`,
- `recommended_checks`,

not long reasoning traces.

### 11.3 Backward-compatible fallback

If structured output is unavailable or fails validation:

1. create `deterministic_narrative`,
2. set `narrative = deterministic_narrative`,
3. set `status.fallback_used = true`,
4. keep `insight_text` as a flattened text version,
5. store the fallback reason in trace.

---

## 12. Validation Gate

### 12.1 Add validators

Create:

```text
src/chec_dashboard/services/timeseries_interpretability/validators.py
```

The validator should check:

| Check | Rule |
|---|---|
| JSON schema | Output parses into `TimeseriesInterpretabilityNarrative`. |
| Date grounding | Every `point_narratives[].fecha_dia` must exist in `critical_points`. |
| Rank grounding | Every point rank must match a deterministic point rank. |
| Criticality grounding | LLM cannot invent criticality types. |
| Citation validity | Citation indexes must be within `corpus_citations`. |
| No new entities | New cause/equipment/circuit labels must not appear unless in deterministic payload or citations. |
| No overclaim phrases | Reject forbidden phrases like “causa definitiva comprobada”. |
| Missing evidence | Low-confidence points must include at least one missing-evidence item. |
| Regulatory caution | No legal/compliance conclusion without explicit cited support. |

### 12.2 Suggested validator skeleton

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chec_dashboard.services.timeseries_interpretability.contracts import (
    TimeseriesInterpretabilityNarrative,
)


FORBIDDEN_PHRASES = (
    "causa definitiva comprobada",
    "esto demuestra que",
    "incumplimiento confirmado",
    "no cumple",
)


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {"valid": self.valid, "errors": self.errors, "warnings": self.warnings}


def validate_narrative(
    *,
    narrative: TimeseriesInterpretabilityNarrative,
    deterministic_payload: dict[str, Any],
    citations: list[dict[str, Any]],
) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    points = deterministic_payload.get("critical_points") or []
    allowed_dates = {str(point.get("fecha_dia")) for point in points}
    ranks_by_date = {str(point.get("fecha_dia")): int(point.get("rank", 0)) for point in points}
    max_citation = len(citations)

    for point in narrative.point_narratives:
        if point.fecha_dia not in allowed_dates:
            errors.append(f"point_narrative_date_not_grounded:{point.fecha_dia}")
        elif point.rank != ranks_by_date.get(point.fecha_dia):
            errors.append(f"point_rank_mismatch:{point.fecha_dia}")
        for idx in point.citations_used:
            if idx < 1 or idx > max_citation:
                errors.append(f"invalid_citation:{idx}")
        if point.confidence == "low" and not point.missing_evidence:
            errors.append(f"low_confidence_without_missing_evidence:{point.fecha_dia}")

    flattened = "\n".join(
        [narrative.headline]
        + narrative.executive_summary
        + narrative.key_findings
        + narrative.data_gaps
        + narrative.recommended_actions
        + narrative.limitations
    ).lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in flattened:
            errors.append(f"forbidden_phrase:{phrase}")

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)
```

### 12.3 Repair policy

For MVP, do not implement multiple repair loops. Recommended behavior:

```text
Try structured LLM once.
If parse fails or validation fails:
  -> use deterministic narrative.
Optional later:
  -> one repair call with validation errors and same schema.
```

This keeps latency and complexity under control.

---

## 13. Deterministic Narrative Object

### 13.1 Why convert fallback text into a structured object

The current fallback is useful but plain. It should become a structured narrative object so the UI always receives the same shape whether the LLM is available or not.

Add:

```text
src/chec_dashboard/services/timeseries_interpretability/deterministic_narrative.py
```

Suggested behavior:

```python
def build_deterministic_narrative(payload: dict[str, Any]) -> TimeseriesInterpretabilityNarrative:
    points = payload.get("critical_points") or []
    periods = payload.get("critical_periods") or []

    if not points:
        return TimeseriesInterpretabilityNarrative(
            source="deterministic",
            headline="No se detectaron puntos criticos bajo los umbrales actuales.",
            executive_summary=[
                f"La ventana {payload.get('start_date')} a {payload.get('end_date')} no presenta picos, cambios bruscos o aportes concentrados bajo la configuracion actual."
            ],
            limitations=["La conclusion depende de los umbrales configurados y de la cobertura de datos disponible."],
        )

    point_narratives = []
    for point in points:
        metrics = point.get("metrics") or {}
        aggregates = point.get("daily_aggregates") or {}
        drivers = []
        for group_key in ["top_causes", "top_event_families", "top_equipment", "top_circuits"]:
            values = point.get(group_key) or []
            if values:
                first = values[0]
                drivers.append(f"{first.get('label')} domina en {group_key} con {first.get('event_count', 0)} eventos.")

        point_narratives.append(
            PointNarrative(
                fecha_dia=str(point.get("fecha_dia")),
                rank=int(point.get("rank", 0)),
                headline=f"Punto #{point.get('rank')} en {point.get('fecha_dia')}",
                confidence=point.get("confidence", "medium"),
                why_marked=[reason.get("detail") for reason in point.get("reasons") or [] if reason.get("detail")],
                observed_values=[
                    f"SAIDI={metrics.get('SAIDI', 0)}",
                    f"SAIFI={metrics.get('SAIFI', 0)}",
                    f"Eventos={aggregates.get('event_count', 0)}",
                    f"Duracion_h={aggregates.get('duration_total_h', 0)}",
                    f"Usuarios_afectados={aggregates.get('users_affected_total', 0)}",
                ],
                likely_drivers=drivers or ["No hay agrupacion dominante disponible en la atribucion."],
                missing_evidence=point.get("data_quality_flags") or [],
            )
        )

    return TimeseriesInterpretabilityNarrative(
        source="deterministic",
        headline=f"Se detectaron {len(points)} puntos criticos en la ventana seleccionada.",
        executive_summary=[payload.get("status_text") or "Analisis deterministico generado."],
        key_findings=[point_narratives[0].headline],
        point_narratives=point_narratives,
        period_narratives=[period.get("summary") for period in periods if period.get("summary")],
        data_gaps=sorted({flag for point in points for flag in point.get("data_quality_flags", [])}),
        limitations=["Narrativa generada sin interpretacion documental adicional."],
    )
```

---

## 14. Orchestrator

### 14.1 Replace the naive text attachment

Current function:

```python
attach_interpretability_agent_text(settings, payload, include_agent_text=True)
```

Recommended replacement:

```python
attach_interpretability_narrative(settings, payload, include_agent_text=True)
```

or a dedicated class:

```text
src/chec_dashboard/services/timeseries_interpretability/orchestrator.py
```

### 14.2 Orchestrator responsibilities

The orchestrator should do exactly these steps:

1. Build deterministic fallback narrative.
2. Return fallback immediately if LLM is disabled or not configured.
3. Resolve `timeseries_interpretability` skill.
4. Build context package V2.
5. Build retrieval query from context facts.
6. Retrieve chunks.
7. Convert chunks to citation payload.
8. Render dedicated prompt.
9. Generate structured answer.
10. Parse and validate answer.
11. Use LLM narrative only if valid.
12. Attach trace and status.

### 14.3 Suggested orchestrator skeleton

```python
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from chec_dashboard.core.config import Settings
from chec_dashboard.services.citation_service import citation_payload
from chec_dashboard.services.llm_service import llm_configured, generate_llm_structured_answer
from chec_dashboard.services.retrieval_service import retrieve_chatbot_chunks
from chec_dashboard.services.skill_service import resolve_skill
from chec_dashboard.services.timeseries_interpretability.context_builder import build_timeseries_context_package_v2
from chec_dashboard.services.timeseries_interpretability.deterministic_narrative import build_deterministic_narrative
from chec_dashboard.services.timeseries_interpretability.prompts import render_timeseries_prompt
from chec_dashboard.services.timeseries_interpretability.retrieval_query import build_timeseries_retrieval_query
from chec_dashboard.services.timeseries_interpretability.validators import validate_narrative
from chec_dashboard.services.timeseries_interpretability.contracts import (
    InterpretabilityStatus,
    InterpretabilityTrace,
    TimeseriesInterpretabilityNarrative,
)


TIMESERIES_INTERPRETABILITY_QUESTION = (
    "Explica los puntos criticos de la evolucion SAIDI/SAIFI usando solo los datos "
    "estructurados y documentos recuperados. Indica datos faltantes y evita afirmar "
    "causalidad definitiva."
)


@dataclass(frozen=True)
class TimeseriesInterpretabilityRun:
    payload: dict[str, Any]
    narrative: TimeseriesInterpretabilityNarrative
    citations: list[dict[str, Any]]
    status: InterpretabilityStatus
    trace: InterpretabilityTrace


class TimeseriesInterpretabilityOrchestrator:
    def run(
        self,
        settings: Settings,
        *,
        deterministic_payload: dict[str, Any],
        include_agent_text: bool,
    ) -> TimeseriesInterpretabilityRun:
        started = perf_counter()
        deterministic = build_deterministic_narrative(deterministic_payload)

        def fallback(reason: str, mode: str = "deterministic") -> TimeseriesInterpretabilityRun:
            latency_ms = int((perf_counter() - started) * 1000)
            return TimeseriesInterpretabilityRun(
                payload=deterministic_payload,
                narrative=deterministic,
                citations=[],
                status=InterpretabilityStatus(
                    text=deterministic_payload.get("status_text") or deterministic.headline,
                    severity="warning" if reason not in {"disabled", "not_configured"} else "ok",
                    fallback_used=True,
                    fallback_reason=reason,
                ),
                trace=InterpretabilityTrace(
                    mode=mode,
                    fallback_used=True,
                    fallback_reason=reason,
                    latency_ms=latency_ms,
                ),
            )

        if not include_agent_text or not settings.chatbot_enabled:
            return fallback("disabled")
        if not llm_configured(settings):
            return fallback("not_configured")

        try:
            skill_resolution = resolve_skill("timeseries_interpretability", settings)
            context_package = build_timeseries_context_package_v2(deterministic_payload)
            retrieval_query = build_timeseries_retrieval_query(context_package)
            chunks = retrieve_chatbot_chunks(
                settings,
                selected_context=context_package,
                question=retrieval_query,
                skill_resolution=skill_resolution,
            )
            citations = citation_payload(chunks)
            prompt, prompt_meta = render_timeseries_prompt(
                context_package=context_package,
                docs_text=format_chunks_for_prompt(chunks),
                question_text=TIMESERIES_INTERPRETABILITY_QUESTION,
            )
            raw_narrative = generate_llm_structured_answer(
                settings,
                prompt=prompt,
                schema_name="TimeseriesInterpretabilityNarrative",
                json_schema=TimeseriesInterpretabilityNarrative.model_json_schema(),
                context_package=context_package,
                question=TIMESERIES_INTERPRETABILITY_QUESTION,
                citations=citations,
                skill_resolution=skill_resolution,
            )
            if raw_narrative is None:
                return fallback("structured_generation_failed", mode="llm_failed")

            narrative = TimeseriesInterpretabilityNarrative.model_validate(raw_narrative)
            validation = validate_narrative(
                narrative=narrative,
                deterministic_payload=deterministic_payload,
                citations=citations,
            )
            if not validation.valid:
                run = fallback("validation_failed", mode="llm_validation_failed")
                run.trace.validation = validation.to_payload()
                return run

            latency_ms = int((perf_counter() - started) * 1000)
            return TimeseriesInterpretabilityRun(
                payload=deterministic_payload,
                narrative=narrative,
                citations=citations,
                status=InterpretabilityStatus(
                    text=deterministic_payload.get("status_text") or narrative.headline,
                    severity="ok",
                    fallback_used=False,
                ),
                trace=InterpretabilityTrace(
                    mode="llm_structured",
                    fallback_used=False,
                    skill_id=skill_resolution.skill_id,
                    skill_version=skill_resolution.skill_version,
                    skill_hash=skill_resolution.skill_hash,
                    prompt_name=prompt_meta["prompt_name"],
                    prompt_version=prompt_meta["prompt_version"],
                    prompt_hash=prompt_meta["prompt_hash"],
                    retrieval_query=retrieval_query,
                    retrieved_chunk_ids=[str(chunk.get("chunk_id") or chunk.get("id")) for chunk in chunks],
                    citation_count=len(citations),
                    validation=validation.to_payload(),
                    latency_ms=latency_ms,
                ),
            )
        except Exception as exc:
            return fallback(f"exception:{exc.__class__.__name__}", mode="exception_fallback")
```

Note: `format_chunks_for_prompt()` should either reuse current prompt formatting logic or be implemented in `prompts.py`.

---

## 15. Public Attachment Function

Modify:

```text
src/chec_dashboard/services/time_series_interpretability_agent.py
```

Recommended behavior:

```python
def attach_interpretability_narrative(
    settings: Settings,
    payload: dict[str, Any],
    *,
    include_agent_text: bool,
) -> dict[str, Any]:
    updated = dict(payload)
    run = TimeseriesInterpretabilityOrchestrator().run(
        settings,
        deterministic_payload=updated,
        include_agent_text=include_agent_text,
    )

    deterministic = build_deterministic_narrative(updated)
    updated["deterministic_narrative"] = deterministic.model_dump(mode="json")
    updated["narrative"] = run.narrative.model_dump(mode="json")
    updated["status"] = run.status.model_dump(mode="json")
    updated["interpretability_trace"] = run.trace.model_dump(mode="json")
    updated["corpus_citations"] = run.citations

    # Backward compatibility for existing UI/tests.
    updated["insight_text"] = flatten_narrative_to_text(run.narrative)
    updated["status_text"] = run.status.text or updated.get("status_text")
    return updated
```

Keep the old function for one release:

```python
def attach_interpretability_agent_text(...):
    return attach_interpretability_narrative(...)
```

---

## 16. Databricks Service Integration

Modify:

```text
src/chec_dashboard/services/databricks_data_service.py
```

Current flow inside `get_summary_interpretability_payload()`:

```python
payload = build_summary_interpretability_payload(...)
payload = attach_interpretability_agent_text(...)
_cache_set(...)
return payload
```

Recommended flow:

```python
payload = build_summary_interpretability_payload(...)
if selected_date:
    payload["critical_points"] = [
        point for point in payload.get("critical_points", [])
        if point.get("fecha_dia") == selected_date
    ]
payload = attach_interpretability_narrative(
    settings,
    payload,
    include_agent_text=bool(include_agent_text and settings.summary_interpretability_enabled),
)
_cache_set(settings, cache_key, payload, settings.summary_interpretability_cache_seconds)
return payload
```

### 16.1 Cache key additions

The cache key currently includes thresholds and `include_agent_text`. Add:

- skill hash if available,
- prompt hash if easy to compute without expensive work,
- narrative schema version,
- selected date,
- LLM structured-output mode flag.

Suggested partial cache-key additions:

```python
"narrative_v2",
"schema_1",
str(settings.summary_interpretability_enabled),
```

Avoid reading remote resources just to build the cache key. Prompt hash can be included in trace even if not included in the cache key.

---

## 17. Runtime Tool Integration for Follow-Up Chat

The summary panel itself should use the explicit orchestrator. The chatbot, however, should be able to use the same context when users ask follow-up questions such as:

> Explicame el pico de SAIDI del 2024-01-04.

### 17.1 Update routing allowlist

Modify:

```text
src/chec_dashboard/services/agent_routing_service.py
```

Add:

```python
RUNTIME_AGENT_TOOLS = {
    ...,
    "get_timeseries_interpretability_context",
}
```

### 17.2 Add route terms

Add a small group:

```python
_TIMESERIES_TERMS = {
    "evolucion",
    "evolución",
    "serie",
    "tendencia",
    "pico",
    "anomalia",
    "anomalía",
    "punto critico",
    "punto crítico",
    "saidi",
    "saifi",
}
```

Then route to `get_timeseries_interpretability_context` when selected context or question indicates time-series analysis.

### 17.3 Execute structured tool

Extend `_execute_structured_tool()`:

```python
if tool_name == "get_timeseries_interpretability_context":
    return get_timeseries_interpretability_context_tool(
        settings,
        **scope,
        selected_date=selected_context.get("selected_date"),
    ), None
```

### 17.4 Add context tool implementation

The tool can live in:

```text
src/chec_dashboard/services/agent_context_service.py
```

or the new package:

```text
src/chec_dashboard/services/timeseries_interpretability/context_tool.py
```

Recommended output:

```json
{
  "tool_name": "get_timeseries_interpretability_context",
  "context_kind": "timeseries_criticality",
  "summary": {...},
  "critical_points": [...],
  "critical_periods": [...],
  "data_quality_flags": [...],
  "source": "summary_interpretability_payload"
}
```

---

## 18. UI Upgrade

### 18.1 Current UI issue

Current panel flow in `summary_page.py`:

```python
html.Div(str(payload.get("insight_text") or ""), className="summary-interpretability-text")
html.Div([_critical_point_card(point) for point in points])
```

This makes the output feel plain because the UI receives and renders one paragraph.

### 18.2 Target panel layout

Recommended visual structure:

```text
[Header]
Interpretabilidad de la evolucion
4 puntos criticos · confianza media · fallback no usado

[Executive summary]
- Finding 1
- Finding 2
- Finding 3

[Key findings chips]
SAIDI alto | Aumento brusco | Top contributor | Datos faltantes

[Critical point cards]
#1 2024-01-04 LOW
Por que se marco
Valores observados
Posibles drivers
Datos faltantes
Revisiones recomendadas
Citas

[Evidence matrix]
Fecha | Señal | Evidencia estructurada | Evidencia documental | Confianza

[Data gaps]
- Sin atribucion de evento para indicador no cero

[Recommended actions]
- Revisar eventos dominantes
- Validar causa/equipo/circuito

[Limitations]
- No causalidad definitiva
```

### 18.3 New renderer functions

Modify:

```text
src/chec_dashboard/pages/summary_page.py
```

Add:

```python
def _narrative_bullets(items: list[str], class_name: str) -> html.Ul:
    return html.Ul([html.Li(str(item)) for item in items[:5]], className=class_name)


def _narrative_header(payload: dict[str, Any], narrative: dict[str, Any]) -> html.Div:
    status = payload.get("status") or {}
    trace = payload.get("interpretability_trace") or {}
    fallback = "fallback" if trace.get("fallback_used") else "LLM validado"
    return html.Div(
        className="summary-interpretability-header",
        children=[
            html.Div("Interpretabilidad de la evolucion", className="summary-interpretability-title"),
            html.Div(str(narrative.get("headline") or payload.get("status_text") or ""), className="summary-interpretability-headline"),
            html.Div(
                f"{status.get('severity', 'ok').upper()} · {fallback}",
                className="summary-interpretability-status",
            ),
        ],
    )


def _point_narrative_card(point: dict[str, Any], narrative_by_date: dict[str, dict[str, Any]]) -> html.Div:
    narrative = narrative_by_date.get(str(point.get("fecha_dia"))) or {}
    metrics = point.get("metrics") or {}
    aggregates = point.get("daily_aggregates") or {}
    return html.Div(
        className="summary-critical-point-card summary-critical-point-card-v2",
        children=[
            html.Div(
                [
                    html.Span(f"#{point.get('rank')}"),
                    html.Span(str(point.get("fecha_dia"))),
                    html.Span(str(narrative.get("confidence") or point.get("confidence", "medium")).upper()),
                ],
                className="summary-critical-point-header",
            ),
            html.Div(str(narrative.get("headline") or "Punto critico"), className="summary-critical-point-title"),
            html.Div(
                f"SAIDI {_format_number(metrics.get('SAIDI'))} | SAIFI {_format_number(metrics.get('SAIFI'))} | "
                f"Eventos {aggregates.get('event_count', 0)} | Duracion {aggregates.get('duration_total_h', 0)} h",
                className="summary-critical-point-metrics",
            ),
            html.Div("Por que se marco", className="summary-critical-point-section-title"),
            _narrative_bullets(narrative.get("why_marked") or [], "summary-critical-point-list"),
            html.Div("Posibles drivers", className="summary-critical-point-section-title"),
            _narrative_bullets(narrative.get("likely_drivers") or [], "summary-critical-point-list"),
            html.Div("Datos faltantes", className="summary-critical-point-section-title"),
            _narrative_bullets(narrative.get("missing_evidence") or [], "summary-critical-point-list muted"),
        ],
    )
```

Then update `_interpretability_panel_from_payload()`:

```python
def _interpretability_panel_from_payload(payload: dict[str, Any] | None) -> html.Div:
    if not payload:
        return _interpretability_empty_panel()
    points = payload.get("critical_points") or []
    narrative = payload.get("narrative") or {}
    if not points:
        return _interpretability_empty_panel(str(payload.get("status_text") or "No se detectaron puntos criticos."))

    point_narratives = {
        str(item.get("fecha_dia")): item
        for item in narrative.get("point_narratives") or []
    }

    return html.Div(
        className="summary-interpretability-panel summary-interpretability-panel-v2",
        children=[
            _narrative_header(payload, narrative),
            html.Div(
                _narrative_bullets(narrative.get("executive_summary") or [], "summary-narrative-list"),
                className="summary-narrative-section",
            ),
            html.Div(
                [_point_narrative_card(point, point_narratives) for point in points],
                className="summary-critical-point-grid",
            ),
            _evidence_matrix(narrative.get("evidence_matrix") or []),
            _narrative_footer(narrative),
        ],
    )
```

### 18.4 Evidence matrix renderer

```python
def _evidence_matrix(rows: list[dict[str, Any]]) -> html.Div:
    if not rows:
        return html.Div()
    return html.Div(
        className="summary-evidence-matrix",
        children=[
            html.Div("Matriz de evidencia", className="summary-section-title"),
            html.Table(
                [
                    html.Thead(
                        html.Tr([
                            html.Th("Fecha"),
                            html.Th("Senal"),
                            html.Th("Evidencia estructurada"),
                            html.Th("Evidencia documental"),
                            html.Th("Confianza"),
                        ])
                    ),
                    html.Tbody([
                        html.Tr([
                            html.Td(str(row.get("fecha_dia") or "-")),
                            html.Td(str(row.get("signal") or "")),
                            html.Td(str(row.get("structured_evidence") or "")),
                            html.Td(str(row.get("documentary_evidence") or "Sin soporte documental suficiente")),
                            html.Td(str(row.get("confidence") or "medium")),
                        ])
                        for row in rows[:8]
                    ]),
                ]
            ),
        ],
    )
```

### 18.5 CSS additions

Modify:

```text
src/chec_dashboard/assets/base.css
```

Add classes such as:

```css
.summary-interpretability-panel-v2 {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.summary-interpretability-headline {
  font-weight: 700;
  color: #014719;
  margin-top: 4px;
}

.summary-narrative-section {
  background: #f7faf8;
  border: 1px solid #e0ece4;
  border-radius: 12px;
  padding: 12px 14px;
}

.summary-narrative-list,
.summary-critical-point-list {
  margin: 6px 0 0 18px;
  padding: 0;
}

.summary-critical-point-card-v2 {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.summary-critical-point-section-title,
.summary-section-title {
  font-weight: 700;
  color: #014719;
  margin-top: 6px;
}

.summary-evidence-matrix table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}

.summary-evidence-matrix th,
.summary-evidence-matrix td {
  border-bottom: 1px solid #e3e8e4;
  padding: 8px;
  text-align: left;
  vertical-align: top;
}
```

---

## 19. Chart Interaction Improvements

Keep `_apply_interpretability_markers()` and add these upgrades later:

1. **Marker hover detail**
   - show rank,
   - date,
   - top criticality types,
   - SAIDI/SAIFI values,
   - event count,
   - confidence.

2. **Selected point filter**
   - when a user clicks a critical marker, pass `selected_date` to `summary_interpretability`,
   - render only that point in the panel,
   - keep a “show all points” action.

3. **Period shading**
   - use `critical_periods` to add transparent vertical rectangles for sustained elevated periods.

4. **Metric-specific markers**
   - SAIDI and SAIFI markers should stay visually distinct,
   - divergence points can include a separate symbol or annotation label.

---

## 20. Observability and Traceability

### 20.1 Trace payload

Add this to every interpretability response:

```json
"interpretability_trace": {
  "mode": "llm_structured",
  "fallback_used": false,
  "fallback_reason": null,
  "skill_id": "time_series_interpretability",
  "skill_version": "1.0",
  "skill_hash": "...",
  "prompt_name": "time_series_interpretability",
  "prompt_version": "1",
  "prompt_hash": "...",
  "retrieval_query": "SAIDI SAIFI confiabilidad interrupciones ...",
  "retrieved_chunk_ids": ["..."],
  "citation_count": 3,
  "validation": {
    "valid": true,
    "errors": [],
    "warnings": []
  },
  "latency_ms": 1240
}
```

### 20.2 Logging

Log at INFO level:

- start/end of interpretability run,
- number of critical points,
- number of retrieved chunks,
- fallback reason,
- validation errors,
- latency.

Do not log full prompts by default. Prompt logging should be opt-in and scrubbed.

### 20.3 MLflow / Databricks future integration

For Databricks deployment, map the same trace fields into MLflow traces later:

- input context hash,
- prompt version/hash,
- retrieved chunk IDs,
- structured output,
- validation result,
- user feedback if available,
- latency and cost metadata if available.

---

## 21. Evaluation Plan

### 21.1 Create a small golden dataset

Add:

```text
tests/fixtures/timeseries_interpretability_cases.json
```

Each case should include:

```json
{
  "case_id": "single_saidi_spike_with_events",
  "description": "One SAIDI spike with matching event attribution",
  "daily_data": [...],
  "attribution_frame": [...],
  "event_frame": [...],
  "expected": {
    "critical_dates": ["2024-01-04"],
    "required_criticality_types": ["saidi_high_outlier", "sharp_saidi_increase"],
    "required_narrative_fields": ["headline", "executive_summary", "point_narratives"],
    "must_include_missing_evidence": false,
    "forbidden_terms": ["causa definitiva comprobada", "incumplimiento confirmado"]
  }
}
```

Recommended initial cases:

| Case | Purpose |
|---|---|
| `no_critical_points` | Validates clean fallback. |
| `single_saidi_spike_with_events` | Validates spike detection and event attribution. |
| `single_saifi_spike_many_events` | Validates frequency-impact narrative. |
| `divergent_saidi_saifi` | Validates duration-vs-frequency distinction. |
| `sustained_period` | Validates interval narrative. |
| `missing_event_attribution` | Validates low confidence and missing evidence. |
| `all_zero_window` | Validates data-quality caution. |
| `selected_date_filter` | Validates point-level drilldown. |

### 21.2 Automated quality checks

Add deterministic tests for:

- schema validity,
- date grounding,
- citation grounding,
- no forbidden phrases,
- data gaps when confidence is low,
- fallback behavior when LLM disabled,
- fallback behavior when LLM returns invalid JSON,
- UI rendering with narrative present,
- UI rendering with only `insight_text` present.

### 21.3 Human review rubric

Use a lightweight review rubric for expert evaluation:

| Criterion | Pass condition |
|---|---|
| Correctness | Dates and values match deterministic payload. |
| Grounding | No causes or entities are invented. |
| Caution | No definitive causality or compliance conclusion. |
| Evidence | Document-backed claims cite available sources. |
| Usefulness | Recommendations are operational and specific. |
| Readability | Output is concise and easy to scan in the UI. |

---

## 22. Test Plan

### 22.1 Unit tests

Add:

```text
tests/test_timeseries_interpretability_contracts.py
tests/test_timeseries_interpretability_context_builder.py
tests/test_timeseries_interpretability_retrieval_query.py
tests/test_timeseries_interpretability_deterministic_narrative.py
tests/test_timeseries_interpretability_validator.py
tests/test_timeseries_interpretability_orchestrator.py
```

Extend:

```text
tests/test_time_series_interpretability_service.py
tests/test_api.py
tests/test_dash_startup.py
tests/test_chatbot_service.py
tests/test_chatbot_callbacks.py
```

### 22.2 Test examples

```python
def test_validator_rejects_unseen_date(sample_payload, sample_citations):
    narrative = TimeseriesInterpretabilityNarrative(
        source="llm",
        headline="Resumen",
        point_narratives=[
            PointNarrative(
                fecha_dia="2099-01-01",
                rank=1,
                headline="Fecha inventada",
            )
        ],
    )
    result = validate_narrative(
        narrative=narrative,
        deterministic_payload=sample_payload,
        citations=sample_citations,
    )
    assert not result.valid
    assert any("point_narrative_date_not_grounded" in error for error in result.errors)
```

```python
def test_retrieval_query_includes_dominant_cause(sample_payload):
    context = build_timeseries_context_package_v2(sample_payload)
    query = build_timeseries_retrieval_query(context)
    assert "SAIDI" in query
    assert "SAIFI" in query
    assert "confiabilidad" in query
```

```python
def test_orchestrator_falls_back_when_llm_disabled(settings, sample_payload):
    settings.chatbot_enabled = False
    run = TimeseriesInterpretabilityOrchestrator().run(
        settings,
        deterministic_payload=sample_payload,
        include_agent_text=True,
    )
    assert run.status.fallback_used
    assert run.narrative.source == "deterministic"
```

### 22.3 UI tests

Add callback/render tests for:

- payload with `narrative`,
- payload without `narrative` but with `insight_text`,
- payload with no critical points,
- payload with low-confidence point and data gaps,
- evidence matrix with citations.

---

## 23. Rollout Plan

### Phase 0 — Baseline and decisions

Deliverables:

- Keep current implementation working.
- Add this upgrade plan to `docs/`.
- Decide whether `narrative` schemas live only in services or are shared with API schemas.
- Decide whether the first release uses provider-native structured outputs or strict JSON parsing fallback.

Acceptance criteria:

- No behavior change yet.
- Existing tests pass.

### Phase 1 — Structured deterministic narrative

Deliverables:

- Add `contracts.py`.
- Add `deterministic_narrative.py`.
- Add `narrative`, `deterministic_narrative`, `status`, and `interpretability_trace` fields to payload.
- Keep `insight_text` for compatibility.

Acceptance criteria:

- With LLM disabled, API returns a valid `narrative` object.
- UI can still display the old `insight_text` if needed.
- Existing tests pass.

### Phase 2 — Dedicated skill and prompt

Deliverables:

- Add `time_series_interpretability.yml`.
- Update `skill_service.py` allowlists/mappings.
- Add prompt template under `agent_prompts/`.
- Add prompt loader/renderer.

Acceptance criteria:

- Skill validation passes.
- Prompt hash appears in trace.
- No generic reliability prompt is used for this feature.

### Phase 3 — Context and retrieval upgrade

Deliverables:

- Add context package V2.
- Add retrieval hints.
- Add deterministic retrieval query builder.
- Pass targeted query to `retrieve_chatbot_chunks()`.

Acceptance criteria:

- Trace includes retrieval query.
- Retrieved chunks are tied to targeted facts.
- Empty retrieval still produces deterministic narrative.

### Phase 4 — Structured LLM and validator

Deliverables:

- Add `generate_llm_structured_answer()` or equivalent provider wrapper.
- Add validators.
- Add single-pass fallback behavior.
- Add validation metadata to trace.

Acceptance criteria:

- Invalid JSON falls back.
- Invented dates are rejected.
- Invalid citations are rejected.
- Forbidden overclaim phrases are rejected.

### Phase 5 — Rich UI renderer

Deliverables:

- Update `_interpretability_panel_from_payload()` to prefer `narrative`.
- Add executive summary, point narrative cards, evidence matrix, data gaps, recommendations, limitations.
- Add CSS for the new panel.

Acceptance criteria:

- The summary panel no longer feels like one plain paragraph.
- Users can scan critical dates, evidence, gaps, and actions quickly.
- UI works with both LLM and deterministic fallback narratives.

### Phase 6 — Follow-up chatbot tool integration

Deliverables:

- Add `get_timeseries_interpretability_context` to runtime tool allowlists.
- Add route terms.
- Add execution function.
- Add skill tests and chatbot route tests.

Acceptance criteria:

- Follow-up questions about the time-series analysis can use the structured context tool.
- Unsupported tools are not exposed outside the allowlist.

### Phase 7 — Observability and evaluation

Deliverables:

- Add trace logging.
- Add evaluation fixtures.
- Add expert-review rubric.
- Prepare MLflow trace mapping for Databricks deployment.

Acceptance criteria:

- Each response can be debugged from trace metadata.
- Evaluation cases detect regressions in grounding and overclaim behavior.

---

## 24. Recommended Pull Request Breakdown

### PR 1 — Contracts and deterministic narrative

Files:

```text
src/chec_dashboard/services/timeseries_interpretability/__init__.py
src/chec_dashboard/services/timeseries_interpretability/contracts.py
src/chec_dashboard/services/timeseries_interpretability/deterministic_narrative.py
src/chec_dashboard/services/time_series_interpretability_agent.py
src/chec_dashboard/api/schemas/responses.py
tests/test_timeseries_interpretability_contracts.py
tests/test_timeseries_interpretability_deterministic_narrative.py
```

### PR 2 — Skill and prompt

Files:

```text
src/chec_dashboard/agent_skills/active/time_series_interpretability.yml
src/chec_dashboard/agent_prompts/time_series_interpretability.v1.md
src/chec_dashboard/services/skill_service.py
src/chec_dashboard/services/timeseries_interpretability/prompts.py
tests/test_skill_service.py
tests/test_timeseries_interpretability_prompts.py
```

### PR 3 — Context builder, retrieval query, orchestrator

Files:

```text
src/chec_dashboard/services/timeseries_interpretability/context_builder.py
src/chec_dashboard/services/timeseries_interpretability/retrieval_query.py
src/chec_dashboard/services/timeseries_interpretability/orchestrator.py
src/chec_dashboard/services/time_series_interpretability_agent.py
src/chec_dashboard/services/databricks_data_service.py
tests/test_timeseries_interpretability_context_builder.py
tests/test_timeseries_interpretability_retrieval_query.py
tests/test_timeseries_interpretability_orchestrator.py
```

### PR 4 — Validation gate

Files:

```text
src/chec_dashboard/services/timeseries_interpretability/validators.py
src/chec_dashboard/services/llm_service.py
tests/test_timeseries_interpretability_validator.py
tests/test_timeseries_interpretability_orchestrator.py
```

### PR 5 — UI upgrade

Files:

```text
src/chec_dashboard/pages/summary_page.py
src/chec_dashboard/assets/base.css
tests/test_dash_startup.py
tests/test_summary_page_interpretability.py
```

### PR 6 — Chatbot follow-up tool

Files:

```text
src/chec_dashboard/services/agent_routing_service.py
src/chec_dashboard/services/agent_context_service.py
src/chec_dashboard/services/timeseries_interpretability/context_tool.py
tests/test_chatbot_service.py
tests/test_chatbot_callbacks.py
```

---

## 25. Backward Compatibility

The upgrade should preserve these behaviors during migration:

| Existing behavior | Compatibility plan |
|---|---|
| `insight_text` exists | Keep it as flattened narrative text for at least one release. |
| `status_text` exists | Keep it; also add structured `status`. |
| `critical_points` shape exists | Keep shape unchanged. |
| `critical_periods` shape exists | Keep shape unchanged. |
| UI renders with no LLM | Deterministic narrative must render the same UI sections. |
| Existing tests expect text | Update tests gradually; avoid deleting old fields immediately. |

Recommended deprecation path:

1. Release V2 with both `insight_text` and `narrative`.
2. Update UI to prefer `narrative`.
3. Update tests to assert both backward compatibility and new structure.
4. Later remove direct UI dependency on `insight_text`.

---

## 26. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| LLM invents causes or dates | Loss of trust | Validator rejects unseen dates/entities; fallback to deterministic narrative. |
| Retrieval returns irrelevant documents | Weak citations | Build targeted retrieval query; show “soporte documental insuficiente” when needed. |
| UI becomes too dense | Poor usability | Use collapsible sections or tabs; cap visible items. |
| Latency increases | Bad UX | Cache deterministic payload; cap chunks; use one LLM call; fallback quickly on failure. |
| Skill validation blocks new file | Feature silently falls back | Update `EXPECTED_SKILL_FILES` and `ALLOWED_TOOLS`; add tests. |
| Prompt/schema drift | Hard to debug | Add prompt version/hash and narrative schema version to trace. |
| Databricks tables unavailable | Missing attribution | Keep deterministic time-series analysis; mark `missing_event_attribution`. |
| Regulatory overclaim | Compliance risk | Dedicated skill constraints, forbidden phrases, citation validation. |

---

## 27. Acceptance Criteria

The upgrade is complete when:

1. The summary interpretability endpoint returns:
   - `critical_points`,
   - `critical_periods`,
   - `narrative`,
   - `deterministic_narrative`,
   - `status`,
   - `interpretability_trace`,
   - `corpus_citations`,
   - backward-compatible `insight_text`.

2. The LLM uses:
   - `time_series_interpretability.yml`,
   - a dedicated prompt template,
   - a targeted retrieval query,
   - structured output.

3. The validator rejects:
   - invented dates,
   - invalid ranks,
   - invalid citations,
   - forbidden overclaim phrases,
   - low-confidence points without missing evidence.

4. The UI displays:
   - executive summary,
   - critical point cards,
   - evidence matrix,
   - data gaps,
   - recommended actions,
   - limitations,
   - deterministic fallback with the same layout.

5. Observability includes:
   - fallback reason,
   - prompt version/hash,
   - skill version/hash,
   - retrieval query,
   - retrieved chunk IDs,
   - validation result,
   - latency.

6. Tests cover:
   - deterministic feature and detection behavior,
   - context construction,
   - retrieval query construction,
   - structured narrative validation,
   - fallback behavior,
   - UI rendering.

---

## 28. Minimal First Implementation

If you want the smallest high-value implementation, do this first:

1. Add `contracts.py` with narrative/status/trace models.
2. Add `deterministic_narrative.py`.
3. Modify `attach_interpretability_agent_text()` to attach:
   - `narrative`,
   - `deterministic_narrative`,
   - `status`,
   - `interpretability_trace`.
4. Update the UI to render `narrative` if present.
5. Keep the existing generic LLM path temporarily.

This immediately fixes the “too plain” UI problem without changing Databricks queries or the LLM provider.

Then implement the dedicated skill/prompt/orchestrator in the next PR.

---

## 29. Strongly Recommended Final Design

The final design should look like this:

```text
Deterministic detector owns truth.
Attribution layer owns event facts.
Retrieval layer owns document evidence.
LLM owns only narrative organization.
Validator owns trust boundary.
UI owns structured presentation.
Trace owns debuggability.
```

This gives the feature a clear contract and avoids making the LLM an opaque decision-maker.

---

## 30. Implementation Checklist

### Backend contracts

- [ ] Add `TimeseriesInterpretabilityNarrative` model.
- [ ] Add `PointNarrative` model.
- [ ] Add `EvidenceMatrixRow` model.
- [ ] Add `InterpretabilityStatus` model.
- [ ] Add `InterpretabilityTrace` model.
- [ ] Add response fields to `SummaryInterpretabilityResponse`.

### Deterministic layer

- [ ] Convert fallback text into structured deterministic narrative.
- [ ] Preserve `insight_text` as flattened text.
- [ ] Add data gaps to deterministic narrative.
- [ ] Add period summaries to deterministic narrative.

### Skill and prompt

- [ ] Add `time_series_interpretability.yml`.
- [ ] Update `GUIDED_SKILL_IDS`.
- [ ] Update `EXPECTED_SKILL_FILES`.
- [ ] Update `ALLOWED_TOOLS`.
- [ ] Add prompt file.
- [ ] Add prompt loader.
- [ ] Add prompt hash to trace.

### Context and retrieval

- [ ] Add context package V2.
- [ ] Add retrieval hints.
- [ ] Add deterministic retrieval query builder.
- [ ] Add retrieval query tests.
- [ ] Add retrieved chunk IDs to trace.

### LLM orchestration

- [ ] Add structured LLM generation wrapper.
- [ ] Add orchestrator.
- [ ] Use dedicated skill.
- [ ] Use dedicated prompt.
- [ ] Use targeted retrieval query.
- [ ] Add fallback modes.

### Validation

- [ ] Validate schema.
- [ ] Validate dates and ranks.
- [ ] Validate citation indexes.
- [ ] Validate forbidden phrases.
- [ ] Validate low-confidence missing evidence.
- [ ] Add validation result to trace.

### UI

- [ ] Render narrative headline.
- [ ] Render executive summary.
- [ ] Render point narrative cards.
- [ ] Render evidence matrix.
- [ ] Render data gaps.
- [ ] Render recommended actions.
- [ ] Render limitations.
- [ ] Add CSS classes.
- [ ] Preserve fallback rendering.

### Chatbot follow-up

- [ ] Add runtime tool allowlist entry.
- [ ] Add route terms.
- [ ] Add structured tool executor.
- [ ] Add context tool.
- [ ] Add chatbot tests.

### Observability and evals

- [ ] Add trace logging.
- [ ] Add golden fixtures.
- [ ] Add expert review rubric.
- [ ] Add no-overclaim tests.
- [ ] Prepare MLflow mapping.

---

## 31. Definition of Done

The upgrade is done when a user can open the SAIDI/SAIFI time-evolution tab and see a structured explanation that answers:

1. What dates are critical?
2. Why were they marked?
3. What values changed?
4. What events or groups appear to explain the behavior?
5. What documentary evidence supports the interpretation?
6. What evidence is missing?
7. What operational checks should be prioritized?
8. What limitations prevent stronger claims?

The answer must remain useful even with the LLM disabled.
