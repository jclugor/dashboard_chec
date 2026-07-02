from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from chec_dashboard.core.config import Settings
from chec_dashboard.services.agent_context_service import BRIEFING_LABELS
from chec_dashboard.services.agent_contract_service import contract_metadata
from chec_dashboard.services.observability_service import load_registered_prompt_template
from chec_dashboard.services.skill_service import SkillResolution


ANSWER_PROMPT_TEMPLATE = """
Eres un asistente técnico para CHEC. Responde siempre en español.

Objetivo:
Analiza el evento o elemento de red seleccionado con base en requisitos técnicos,
condiciones externas y valores de indicadores. Explica el estado observado, si
hay señales de cumplimiento o posible incumplimiento, qué condiciones pueden
explicar los valores, y qué revisiones de campo o datos recomendarías.

Tipo de análisis:
{{briefing_label}}

Instrucción específica:
{{briefing_instruction}}

Reglas:
- Usa únicamente el contexto seleccionado y los documentos recuperados.
- Si falta información, dilo claramente y sugiere qué dato falta.
- Cita los documentos usando referencias como [1], [2].
- No inventes requisitos que no estén soportados por los documentos.
- Sé conciso, orientado a las personas interesadas y accionable.
- No uses términos en inglés cuando exista una alternativa clara en español.
- Estructura la respuesta con estos encabezados exactos, en este orden:
  ## Estado observado
  ## Banderas de evidencia
  ## Requisitos posiblemente aplicables
  ## Datos faltantes
  ## Riesgo posible
  ## Recomendaciones
  ## Limitaciones
  ## Citas usadas
  ## Preguntas sugeridas
- En afirmaciones regulatorias, normativas o de cumplimiento, incluye un marcador de cita como [1].
- Usa lenguaje de control prudente: posible riesgo, evidencia disponible, bandera de evidencia, dato faltante o recomendación de verificación.
- No afirmes conclusiones definitivas como cumple, no cumple, incumplimiento confirmado, sanción aplicable o responsabilidad legal demostrada.
{{skill_text}}

Paquete de contexto estructurado:
{{context_json}}

Pregunta guía y/o pregunta adicional del usuario:
{{question_text}}

Historial reciente de la conversación:
{{history_text}}

Documentos recuperados:
{{docs_text}}
""".strip()


STAGE_PROMPT_FILES = {
    "structured_context": "structured_context_builder.v1.md",
    "critical_point_interpretation": "critical_point_interpreter.v1.md",
    "uiti_vano_behavior_explanation": "uiti_vano_behavior_explainer.v1.md",
    "documentary_analysis": "documentary_normative_analyst.v1.md",
    "predictive_interpretation": "predictive_model_interpreter.v1.md",
    "feature_mask_interpretation": "feature_mask_interpreter.v1.md",
    "three_way_causal_synthesis": "three_way_causal_synthesis.v1.md",
    "intervention_selection": "intervention_candidate_selector.v1.md",
    "what_if_simulation": "what_if_simulation_assistant.v1.md",
    "evidence_report": "evidence_report_writer.v1.md",
}

STAGE_CONTRACT_NAMES = {
    "structured_context": "structured_context",
    "critical_point_interpretation": "critical_point_interpretation",
    "uiti_vano_behavior_explanation": "structured_context",
    "documentary_analysis": "documentary_analysis",
    "predictive_interpretation": "model_evidence",
    "feature_mask_interpretation": "feature_masks",
    "three_way_causal_synthesis": "three_way_synthesis",
    "intervention_selection": "intervention_candidates",
    "what_if_simulation": "what_if_result",
    "evidence_report": "evidence_report",
}


def briefing_instruction(briefing_type: str, skill_resolution: SkillResolution | None = None) -> str:
    if skill_resolution is not None:
        skill = skill_resolution.skill
        if skill.instructions:
            return "\n".join(f"- {instruction}" for instruction in skill.instructions)
    if briefing_type == "compliance":
        return (
            "Enfoca la respuesta en cumplimiento técnico/regulatorio. Usa una sección "
            "'Banderas de evidencia' con señales soportadas por datos y citas. No uses "
            "lenguaje de cumple/no cumple, aprobado/reprobado ni puntajes formales."
        )
    if briefing_type == "maintenance":
        return (
            "Enfoca la respuesta en priorización de mantenimiento: causa raíz probable, "
            "revisiones de campo, activos/circuitos a priorizar y acciones preventivas."
        )
    return (
        "Enfoca la respuesta en confiabilidad: impacto UITI, recurrencia, concentración "
        "por circuito/municipio/causa y señales ambientales u operativas."
    )


def build_prompt(
    *,
    context_package: dict[str, Any],
    question: str | None,
    briefing_type: str,
    chunks: list[dict[str, Any]],
    skill_resolution: SkillResolution | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> str:
    context_json = json.dumps(context_package, ensure_ascii=False, indent=2, default=str)
    snippets = []
    for index, chunk in enumerate(chunks, start=1):
        title = chunk.get("document_title") or chunk.get("title") or "Documento técnico"
        snippets.append(f"[{index}] {title}\n{chunk.get('snippet') or chunk.get('text')}")
    docs_text = "\n\n".join(snippets)
    skill_text = _skill_prompt_text(skill_resolution)
    history_text = _conversation_history_text(conversation_history or [])
    template = load_registered_prompt_template(settings) if settings is not None else None
    return _render_prompt_template(
        template or ANSWER_PROMPT_TEMPLATE,
        {
            "briefing_label": BRIEFING_LABELS.get(briefing_type, "Confiabilidad"),
            "briefing_instruction": briefing_instruction(briefing_type, skill_resolution),
            "skill_text": skill_text,
            "context_json": context_json,
            "question_text": question or "Sin pregunta adicional.",
            "history_text": history_text or "Sin historial previo.",
            "docs_text": docs_text or "No se recuperaron documentos.",
        },
    ).strip()


def build_stage_prompt(
    *,
    context_package: dict[str, Any],
    question: str | None,
    briefing_type: str,
    analysis_stage: str | None,
    chunks: list[dict[str, Any]],
    skill_resolution: SkillResolution,
    conversation_history: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> str:
    if not analysis_stage or analysis_stage == "guided_answer":
        return build_prompt(
            context_package=context_package,
            question=question,
            briefing_type=briefing_type,
            chunks=chunks,
            skill_resolution=skill_resolution,
            conversation_history=conversation_history,
            settings=settings,
        )
    template = load_stage_prompt_template(analysis_stage)
    values = {
        "briefing_label": BRIEFING_LABELS.get(briefing_type, "Confiabilidad"),
        "briefing_instruction": briefing_instruction(briefing_type, skill_resolution),
        "skill_text": _skill_prompt_text(skill_resolution),
        "contract_text": _contract_prompt_text(analysis_stage),
        "context_json": json.dumps(_compact_context(context_package), ensure_ascii=False, indent=2, default=str),
        "question_text": question or "Sin pregunta adicional.",
        "history_text": _conversation_history_text(conversation_history or []) or "Sin historial previo.",
        "docs_text": _docs_text(chunks) or "No se recuperaron documentos.",
    }
    return _render_prompt_template(template, values).strip()


def load_stage_prompt_template(analysis_stage: str) -> str:
    file_name = STAGE_PROMPT_FILES.get(analysis_stage)
    if not file_name:
        return ANSWER_PROMPT_TEMPLATE
    path = Path(__file__).resolve().parents[1] / "agent_prompts" / file_name
    return path.read_text(encoding="utf-8")


def stage_prompt_metadata(analysis_stage: str | None) -> dict[str, str]:
    if not analysis_stage or analysis_stage == "guided_answer":
        template = ANSWER_PROMPT_TEMPLATE
        return {
            "prompt_name": "chec_chatbot_answer_prompt",
            "prompt_version": "local",
            "prompt_hash": _hash_text(template),
            "prompt_source": "local",
        }
    file_name = STAGE_PROMPT_FILES.get(analysis_stage)
    template = load_stage_prompt_template(analysis_stage)
    return {
        "prompt_name": (file_name or analysis_stage).removesuffix(".md"),
        "prompt_version": "1",
        "prompt_hash": _hash_text(template),
        "prompt_source": "local",
    }


def _render_prompt_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def _docs_text(chunks: list[dict[str, Any]]) -> str:
    snippets = []
    for index, chunk in enumerate(chunks, start=1):
        title = chunk.get("document_title") or chunk.get("title") or "Documento tecnico"
        snippets.append(f"[{index}] {title}\n{chunk.get('snippet') or chunk.get('text')}")
    return "\n\n".join(snippets)


def _contract_prompt_text(analysis_stage: str | None) -> str:
    contract_name = STAGE_CONTRACT_NAMES.get(str(analysis_stage or ""))
    if not contract_name:
        return "Contrato: respuesta guiada sin contrato de etapa adicional."
    metadata = contract_metadata(contract_name)
    return (
        "Contrato de salida:\n"
        f"- contract_name: {metadata['contract_name']}\n"
        f"- contract_version: {metadata['contract_version']}\n"
        f"- contract_hash: {metadata['contract_hash']}\n"
        "- Incluye evidencia, supuestos, limitaciones y trazabilidad."
    )


def _compact_context(context_package: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(context_package, ensure_ascii=False, default=str)
    if len(text) <= 20000:
        return context_package
    compact = dict(context_package)
    for key in ("records", "agent_tool_evidence", "critical_points"):
        value = compact.get(key)
        if isinstance(value, list):
            compact[key] = value[:8]
    compact["context_compacted"] = True
    return compact


def _hash_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:16]


def _conversation_history_text(messages: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for message in messages:
        role = str(message.get("role") or "").strip().lower()
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        label = "Usuario" if role == "user" else "Asistente"
        rows.append(f"- {label}: {content[:900]}")
    return "\n".join(rows)


def _skill_prompt_text(skill_resolution: SkillResolution | None) -> str:
    if skill_resolution is None:
        return ""
    skill = skill_resolution.skill
    global_policy = skill_resolution.global_policy
    sections = "\n".join(f"- {section}" for section in skill.answer_sections)
    forbidden = "\n".join(f"- {phrase}" for phrase in skill.forbidden_phrases)
    global_instructions = "\n".join(f"- {instruction}" for instruction in global_policy.instructions)
    allowed_tools = ", ".join(skill.allowed_tools) if skill.allowed_tools else "sin herramientas adicionales"
    section_text = sections or "\n".join(
        [
            "- Estado observado",
            "- Datos faltantes",
            "- Recomendaciones",
            "- Citas",
        ]
    )
    global_instruction_text = global_instructions or "- Usar solo contexto aprobado y documentos recuperados."
    forbidden_text = forbidden or "- Ninguna frase adicional configurada."
    return f"""

Política global gobernada:
{global_instruction_text}

Skill activo:
- skill_id: {skill.skill_id}
- version: {skill.version}
- hash: {skill.skill_hash}
- rol: {skill.role or "Asistente técnico CHEC"}
- tono: {skill.tone or "Técnico y claro"}
- herramientas permitidas: {allowed_tools}

Secciones esperadas:
{section_text}

Restricciones del skill:
- Citar afirmaciones regulatorias: {skill.must_cite_regulatory_claims}
- Evitar conclusiones legales definitivas: {skill.cannot_make_legal_conclusions}
- Comportamiento ante evidencia faltante: {skill.missing_evidence_behavior or "Indicar datos faltantes."}

Frases prohibidas:
{forbidden_text}
""".rstrip()


_briefing_instruction = briefing_instruction
_build_prompt = build_prompt
_answer_prompt_template = ANSWER_PROMPT_TEMPLATE
