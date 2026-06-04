from __future__ import annotations

import json
from typing import Any

from chec_dashboard.services.agent_context_service import BRIEFING_LABELS
from chec_dashboard.services.skill_service import SkillResolution


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
        "Enfoca la respuesta en confiabilidad: SAIDI/SAIFI, recurrencia, concentración "
        "por circuito/municipio/causa y señales ambientales u operativas."
    )


def build_prompt(
    *,
    context_package: dict[str, Any],
    question: str | None,
    briefing_type: str,
    chunks: list[dict[str, Any]],
    skill_resolution: SkillResolution | None = None,
) -> str:
    context_json = json.dumps(context_package, ensure_ascii=False, indent=2, default=str)
    snippets = []
    for index, chunk in enumerate(chunks, start=1):
        title = chunk.get("document_title") or chunk.get("title") or "Documento técnico"
        snippets.append(f"[{index}] {title}\n{chunk.get('snippet') or chunk.get('text')}")
    docs_text = "\n\n".join(snippets)
    skill_text = _skill_prompt_text(skill_resolution)
    return f"""
Eres un asistente técnico para CHEC. Responde siempre en español.

Objetivo:
Analiza el evento o elemento de red seleccionado con base en requisitos técnicos,
condiciones externas y valores de indicadores. Explica el estado observado, si
hay señales de cumplimiento o posible incumplimiento, qué condiciones pueden
explicar los valores, y qué revisiones de campo o datos recomendarías.

Tipo de análisis:
{BRIEFING_LABELS.get(briefing_type, "Confiabilidad")}

Instrucción específica:
{briefing_instruction(briefing_type, skill_resolution)}

Reglas:
- Usa únicamente el contexto seleccionado y los documentos recuperados.
- Si falta información, dilo claramente y sugiere qué dato falta.
- Cita los documentos usando referencias como [1], [2].
- No inventes requisitos que no estén soportados por los documentos.
- Sé conciso, orientado a las personas interesadas y accionable.
- No uses términos en inglés cuando exista una alternativa clara en español.
{skill_text}

Paquete de contexto estructurado:
{context_json}

Pregunta guía y/o pregunta adicional del usuario:
{question or "Sin pregunta adicional."}

Documentos recuperados:
{docs_text or "No se recuperaron documentos."}
""".strip()


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
