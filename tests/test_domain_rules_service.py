from __future__ import annotations

from dataclasses import replace

from chec_dashboard.core.config import settings as base_settings
from chec_dashboard.services.domain_rules_service import (
    variable_context_payload,
    variable_interactions_payload,
)


def test_variable_interaction_rules_match_aliases_and_wildcards() -> None:
    payload = variable_interactions_payload(
        replace(base_settings, chatbot_skills_dir=None),
        selected_event={
            "event_id": "evt-1",
            "causa": "VIENTO",
            "circuito": "CIR-1",
            "duration_raw": 2.0,
            "users_affected": 10.0,
            "uiti": 0.5,
            "uiti_vano": 0.3,
            "equipo_ope": "SW-1",
            "tipo_equi_ope": "RECONECTADOR",
            "latitude": 5.07,
            "longitude": -75.51,
        },
        external_signals={"WIND_GUST_SPD_MAX": 14.2},
    )

    rule_ids = {rule["rule_id"] for rule in payload["matched_rules"]}
    assert "entorno_riesgo_causa_directa" in rule_ids
    assert "eventos_indicadores_regulatorio" in rule_ids
    assert "atributos_espaciales_topologia" in rule_ids
    assert payload["rules_evaluated"] >= len(payload["matched_rules"])
    assert payload["data_quality_flags"] == []


def test_variable_interaction_rules_report_missing_inputs() -> None:
    payload = variable_interactions_payload(
        replace(base_settings, chatbot_skills_dir=None),
        selected_event=None,
        external_signals=None,
    )

    assert payload["matched_rules"] == []
    assert "no_selected_event" in payload["data_quality_flags"]
    assert "no_variable_interaction_matches" in payload["data_quality_flags"]


def test_variable_context_matches_circuit_period_payload() -> None:
    payload = variable_context_payload(
        replace(base_settings, chatbot_skills_dir=None),
        context_payload={
            "circuit_label": "CIR-1",
            "metric_key": "UITI",
            "critical_points": [
                {
                    "metrics": {"UITI": 6.0, "UITI_VANO": 2.0},
                    "daily_aggregates": {"event_count": 4, "duration_raw_total": 3.0},
                    "top_causes": [{"causa": "VIENTO", "event_count": 2}],
                    "external_signals": {"WIND_GUST_SPD_MAX": 14.2},
                }
            ],
        },
    )

    matched_names = {item["name"] for item in payload["matched_variables"]}
    matched_modes = {item["mode_id"] for item in payload["matched_modes"]}
    assert {"UITI", "UITI_VANO", "COD_CAUSA", "DURACION"}.issubset(matched_names)
    assert {"A", "C", "F"}.issubset(matched_modes)
    assert payload["data_quality_flags"] == []


def test_variable_context_reports_no_matches_for_empty_payload() -> None:
    payload = variable_context_payload(
        replace(base_settings, chatbot_skills_dir=None),
        context_payload={},
    )

    assert payload["matched_variables"] == []
    assert "no_variable_context_matches" in payload["data_quality_flags"]


def test_invalid_configured_manifest_falls_back_to_bundled_rules(tmp_path) -> None:
    skills_dir = tmp_path / "skills" / "active"
    knowledge_dir = tmp_path / "skills" / "knowledge"
    skills_dir.mkdir(parents=True)
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "variable_interactions.yml").write_text(
        "schema_version: not-an-int\nrules: []\n",
        encoding="utf-8",
    )

    payload = variable_interactions_payload(
        replace(base_settings, chatbot_skills_dir=skills_dir),
        selected_event={"duration_raw": 1.0, "users_affected": 2.0, "uiti": 0.1, "uiti_vano": 0.2},
    )

    assert payload["source_type"] == "default"
    assert payload["errors"]
    assert {rule["rule_id"] for rule in payload["matched_rules"]} >= {"eventos_indicadores_regulatorio"}


def test_invalid_configured_variable_context_falls_back_to_bundled_manifest(tmp_path) -> None:
    skills_dir = tmp_path / "skills" / "active"
    knowledge_dir = tmp_path / "skills" / "knowledge"
    skills_dir.mkdir(parents=True)
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "variable_context.yml").write_text(
        "schema_version: not-an-int\nvariables: []\n",
        encoding="utf-8",
    )

    payload = variable_context_payload(
        replace(base_settings, chatbot_skills_dir=skills_dir),
        context_payload={"metric_key": "UITI", "critical_points": [{"metrics": {"UITI": 1.0}}]},
    )

    assert payload["source_type"] == "default"
    assert payload["errors"]
    assert {item["name"] for item in payload["matched_variables"]} >= {"UITI"}
