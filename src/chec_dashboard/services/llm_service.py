from __future__ import annotations

from typing import Any

from chec_dashboard.core.config import Settings


SUPPORTED_LLM_PROVIDERS = {
    "mock",
    "gemini",
    "databricks_model_serving",
    "azure_openai",
    "openai",
}


def llm_provider(settings: Settings) -> str:
    provider = (settings.llm_provider or "mock").strip().lower()
    if provider not in SUPPORTED_LLM_PROVIDERS:
        return provider
    return provider


def llm_configured(settings: Settings) -> bool:
    provider = llm_provider(settings)
    if provider == "mock":
        return True
    if provider == "gemini":
        return bool(settings.gemini_api_key)
    if provider == "databricks_model_serving":
        return False
    return False


def llm_configuration_message(settings: Settings) -> str:
    provider = llm_provider(settings)
    if provider == "mock":
        return "Proveedor LLM mock listo para respuestas determinísticas de desarrollo."
    if provider == "gemini" and not settings.gemini_api_key:
        return "El proveedor LLM 'gemini' no está configurado. Define GEMINI_API_KEY o usa LLM_PROVIDER=mock."
    if provider == "databricks_model_serving":
        return "Databricks Model Serving está reservado para Phase 6; usa LLM_PROVIDER=mock en Phase 1."
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
    for label, key in (("SAIDI", "saidi"), ("SAIFI", "saifi"), ("duración h", "duration_h")):
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


def generate_llm_answer(
    settings: Settings,
    *,
    prompt: str,
    context_package: dict[str, Any],
    question: str | None,
    citations: list[dict[str, Any]],
    skill_resolution: Any | None = None,
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
    raise RuntimeError(llm_configuration_message(settings))
