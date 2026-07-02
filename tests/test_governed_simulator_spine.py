from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from chec_dashboard.core.config import settings as base_settings
from chec_dashboard.services.agent_contract_service import contract_metadata, validate_contract_payload
from chec_dashboard.services.agent_orchestrator import assess_chatbot_context, get_chatbot_conversation
from chec_dashboard.services.agent_routing_service import route_agent_tools
from chec_dashboard.services.capability_registry import capability_metadata, unavailable_payload
from chec_dashboard.services.conversation_service import reset_memory_conversation_store
from chec_dashboard.services.evidence_policy_service import contains_forbidden_claim, safe_claim_language
from chec_dashboard.services.evidence_report_service import build_evidence_report_context
from chec_dashboard.services.feature_mask_service import build_feature_mask_package
from chec_dashboard.services.intervention_candidate_service import build_intervention_candidate_context
from chec_dashboard.services.llm_output_validation_service import validate_llm_output
from chec_dashboard.services.model_evidence_service import build_model_evidence_package
from chec_dashboard.services.prompt_service import build_stage_prompt
from chec_dashboard.services.skill_service import get_skill_status, resolve_skill
from chec_dashboard.services.three_way_synthesis_service import build_three_way_context
from chec_dashboard.services.what_if_service import run_what_if_simulation


def _settings(tmp_path: Path, **overrides):
    data_dir = tmp_path / "data"
    corpus_dir = data_dir / "chatbot_corpus"
    output_dir = tmp_path / "outputs"
    data_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return replace(
        base_settings,
        data_dir=data_dir,
        output_dir=output_dir,
        cache_enabled=False,
        data_backend="pickle",
        chatbot_corpus_dir=corpus_dir,
        chatbot_retrieval_top_k=3,
        chatbot_max_context_chars=3000,
        **overrides,
    )


def test_stage_registry_contracts_and_prompt_rendering(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    status = get_skill_status(settings)
    skill = resolve_skill("reliability", settings, analysis_stage="what_if_simulation")
    fallback_skill = resolve_skill("reliability", settings, analysis_stage="unknown_stage")
    contract = contract_metadata("what_if_result")
    prompt = build_stage_prompt(
        context_package={"selected_context": {"CODE": "TR-1"}},
        question="simula un escenario",
        briefing_type="reliability",
        analysis_stage="what_if_simulation",
        chunks=[],
        skill_resolution=skill,
        settings=settings,
    )

    assert status["skills_count"] == 21
    assert skill.skill_id == "what_if_simulation_assistant"
    assert fallback_skill.skill_id == "confiabilidad"
    assert contract["contract_hash"]
    assert "Contrato de salida" in prompt
    assert "what_if_result" in prompt
    assert capability_metadata("what_if_simulation")["capability_tier"] == "skeleton_only"

    validation = validate_contract_payload(
        "structured_context",
        {
            "schema_version": "0.1.0",
            "generated_at": "2026-06-13T00:00:00Z",
            "source": "unit-test",
            "selected_context": {},
            "evidence": [],
            "limitations": [],
            "traceability": {},
        },
    )
    assert validation["valid"] is True


def test_governance_validation_rejects_forbidden_and_unavailable_claims() -> None:
    capability_payload = unavailable_payload(
        capability_id="model_prediction",
        reason="Falta vector de caracteristicas explicito.",
        missing_requirements=["explicit safe features payload"],
    )

    validation = validate_llm_output(
        "La prediccion generada demuestra que no cumple.",
        capability_payload=capability_payload,
        analysis_stage="predictive_interpretation",
    )

    assert contains_forbidden_claim("no cumple") is True
    assert safe_claim_language("model_claim")
    assert validation["valid"] is False
    assert "No se generaron resultados inventados" in validation["fallback_text"]


def test_skeleton_services_are_safe_without_productive_inputs(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    request = {"changes": {"unsupported_variable": 1.0}}
    original_request = deepcopy(request)

    model_payload = build_model_evidence_package(settings, features=None)
    mask_payload = build_feature_mask_package(None)
    synthesis = build_three_way_context(structured_evidence={"selected_context": {"CODE": "TR-1"}})
    intervention = build_intervention_candidate_context(settings)
    what_if = run_what_if_simulation(settings, request=request, baseline_features={"x": 1.0})
    report = build_evidence_report_context(structured_context={"selected_context": {"CODE": "TR-1"}})

    assert model_payload["status"] == "unavailable"
    assert "prediction_values" not in model_payload
    assert mask_payload["status"] == "not_provided"
    assert "feature_masks" not in mask_payload
    assert synthesis["status"] == "partial"
    assert intervention["status"] == "unavailable"
    assert what_if["status"] == "unavailable"
    assert "deltas" not in what_if
    assert report["status"] == "partial"
    assert request == original_request


def test_what_if_rejects_unsupported_variables_from_registry(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills" / "active"
    knowledge_dir = tmp_path / "skills" / "knowledge"
    knowledge_dir.mkdir(parents=True)
    skills_dir.mkdir(parents=True)
    (knowledge_dir / "intervention_variable_registry.yml").write_text(
        """
variables:
  - variable: poda_programada
    group: operational
    rationale: Variable de escenario permitida.
""".strip()
        + "\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, chatbot_skills_dir=skills_dir)

    payload = run_what_if_simulation(
        settings,
        request={"changes": {"variable_no_aprobada": 1}},
        baseline_features={"poda_programada": 0},
    )

    assert payload["status"] == "unavailable"
    assert payload["validation"]["unsupported_variables"] == ["variable_no_aprobada"]


def test_stage_routing_and_api_skeleton_metadata(tmp_path: Path) -> None:
    reset_memory_conversation_store()
    settings = _settings(tmp_path, chatbot_enabled=True, llm_provider="mock")

    candidates = route_agent_tools(
        selected_context={"CODE": "TR-1"},
        context_package={"selected_context": {"CODE": "TR-1"}},
        question="simula un escenario what-if",
        briefing_type="reliability",
        question_id=None,
        analysis_stage="what_if_simulation",
    )
    payload = assess_chatbot_context(
        settings,
        selected_context={"CODE": "TR-1", "causa": "VIENTO"},
        question="explica la senal predictiva",
        briefing_type="reliability",
        analysis_stage="predictive_interpretation",
    )
    detail = get_chatbot_conversation(settings, payload["conversation_id"])

    assert [candidate.tool_name for candidate in candidates][0] == "get_what_if_context"
    assert payload["ready"] is False
    assert payload["analysis_stage"] == "predictive_interpretation"
    assert payload["skill_id"] == "predictive_model_interpreter"
    assert payload["capability_id"] == "model_prediction"
    assert payload["capability_status"] == "unavailable"
    assert payload["safe_fallback_used"] is True
    assert payload["validation_status"] == "not_run_no_llm_output"
    assert "explicit safe features payload" in payload["missing_requirements"]
    assert "No se generaron resultados inventados" in payload["answer"]
    assert detail["messages"][-1]["analysis_stage"] == "predictive_interpretation"
