from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import yaml

from chec_dashboard.core.config import Settings
from chec_dashboard.services.retrieval_service import read_databricks_file_text


DOMAIN_RULES_FILE = "variable_interactions.yml"
DOMAIN_RULES_MARKDOWN_FILE = "variable_interactions.md"
VARIABLE_CONTEXT_FILE = "variable_context.yml"
VARIABLE_CONTEXT_MARKDOWN_FILE = "variable_context.md"

FIELD_ALIASES = {
    "causa": ("COD_CAUSA", "DESC_CAUSA"),
    "circuito": ("CIRCUITO",),
    "cto_equi_ope": ("CIRCUITO",),
    "duration_raw": ("DURACION", "DURATION_RAW"),
    "DURATION_RAW": ("DURACION",),
    "users_affected": ("TOT_USUS", "CNT_USUS", "USERS"),
    "USERS": ("TOT_USUS", "CNT_USUS"),
    "uiti": ("UITI",),
    "UITI": ("UITI",),
    "uiti_vano": ("UITI_VANO",),
    "UITI_VANO": ("UITI_VANO",),
    "equipo_ope": ("FID_SW", "COD_EQ_PROTEGE"),
    "tipo_equi_ope": ("TIPO",),
    "asset_id": ("FID_VANO",),
    "latitude": ("Y1",),
    "longitude": ("X1",),
    "latitude_end": ("Y2",),
    "longitude_end": ("X2",),
}


@dataclass(frozen=True)
class DomainRulesManifest:
    schema_version: int
    source_document: str
    source_section: str
    rules: tuple[dict[str, Any], ...]
    source_path: str
    source_type: str
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class VariableContextManifest:
    schema_version: int
    source_document: str
    source_sections: tuple[str, ...]
    modes: tuple[dict[str, Any], ...]
    variables: tuple[dict[str, Any], ...]
    source_path: str
    source_type: str
    errors: tuple[str, ...] = ()


def _default_knowledge_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "agent_knowledge"


def _configured_knowledge_dir(settings: Settings) -> Path | None:
    if settings.chatbot_skills_dir is None:
        return None
    return settings.chatbot_skills_dir.parent / "knowledge"


def _read_text(path: Path) -> str | None:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return read_databricks_file_text(path)


def _candidate_paths(settings: Settings, filename: str = DOMAIN_RULES_FILE) -> list[tuple[Path, str]]:
    paths: list[tuple[Path, str]] = []
    configured_dir = _configured_knowledge_dir(settings)
    if configured_dir is not None:
        paths.append((configured_dir / filename, "configured"))
    paths.append((_default_knowledge_dir() / filename, "default"))
    return paths


def _as_string_list(value: Any, field_name: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{field_name} must be a list.")
        return []
    items: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            items.append(text)
    if not items:
        errors.append(f"{field_name} must include at least one value.")
    return items


def _validate_manifest(payload: Any, *, source_path: str, source_type: str) -> DomainRulesManifest:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return DomainRulesManifest(1, "", "", (), source_path, source_type, ("manifest must be an object.",))

    schema_version = payload.get("schema_version")
    try:
        schema_version_int = int(schema_version)
    except (TypeError, ValueError):
        schema_version_int = 1
        errors.append("schema_version must be an integer.")

    source_document = str(payload.get("source_document") or "").strip()
    source_section = str(payload.get("source_section") or "").strip()
    if not source_document:
        errors.append("source_document is required.")
    if not source_section:
        errors.append("source_section is required.")

    raw_rules = payload.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raw_rules = []
        errors.append("rules must be a non-empty list.")

    rules: list[dict[str, Any]] = []
    for index, raw_rule in enumerate(raw_rules, start=1):
        if not isinstance(raw_rule, dict):
            errors.append(f"rules[{index}] must be an object.")
            continue
        rule_errors: list[str] = []
        rule_id = str(raw_rule.get("rule_id") or "").strip()
        origin_variables = _as_string_list(raw_rule.get("origin_variables"), f"rules[{index}].origin_variables", rule_errors)
        destination_variables = _as_string_list(
            raw_rule.get("destination_variables"),
            f"rules[{index}].destination_variables",
            rule_errors,
        )
        try:
            weight = float(raw_rule.get("weight"))
        except (TypeError, ValueError):
            weight = 0.0
            rule_errors.append(f"rules[{index}].weight must be numeric.")
        if not rule_id:
            rule_errors.append(f"rules[{index}].rule_id is required.")
        if rule_errors:
            errors.extend(rule_errors)
            continue
        rules.append(
            {
                "rule_id": rule_id,
                "origin_group": str(raw_rule.get("origin_group") or "").strip(),
                "origin_variables": origin_variables,
                "destination_group": str(raw_rule.get("destination_group") or "").strip(),
                "destination_variables": destination_variables,
                "relation_type": str(raw_rule.get("relation_type") or "").strip(),
                "weight": max(0.0, min(weight, 1.0)),
                "rationale": str(raw_rule.get("rationale") or "").strip(),
            }
        )

    return DomainRulesManifest(
        schema_version=schema_version_int,
        source_document=source_document,
        source_section=source_section,
        rules=tuple(rules),
        source_path=source_path,
        source_type=source_type,
        errors=tuple(errors),
    )


def _validate_variable_context_manifest(
    payload: Any,
    *,
    source_path: str,
    source_type: str,
) -> VariableContextManifest:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return VariableContextManifest(1, "", (), (), (), source_path, source_type, ("manifest must be an object.",))

    try:
        schema_version_int = int(payload.get("schema_version"))
    except (TypeError, ValueError):
        schema_version_int = 1
        errors.append("schema_version must be an integer.")

    source_document = str(payload.get("source_document") or "").strip()
    if not source_document:
        errors.append("source_document is required.")

    raw_sections = payload.get("source_sections") or payload.get("source_section") or []
    if isinstance(raw_sections, str):
        raw_sections = [raw_sections]
    source_sections = tuple(str(item).strip() for item in raw_sections if str(item or "").strip())
    if not source_sections:
        errors.append("source_sections must include at least one value.")

    raw_modes = payload.get("modes")
    if not isinstance(raw_modes, list) or not raw_modes:
        raw_modes = []
        errors.append("modes must be a non-empty list.")
    modes: list[dict[str, Any]] = []
    mode_labels: dict[str, str] = {}
    for index, raw_mode in enumerate(raw_modes, start=1):
        if not isinstance(raw_mode, dict):
            errors.append(f"modes[{index}] must be an object.")
            continue
        mode_id = str(raw_mode.get("mode_id") or "").strip()
        label = str(raw_mode.get("label") or "").strip()
        description = str(raw_mode.get("description") or "").strip()
        if not mode_id:
            errors.append(f"modes[{index}].mode_id is required.")
            continue
        if not label:
            errors.append(f"modes[{index}].label is required.")
        mode_labels[mode_id] = label
        modes.append({"mode_id": mode_id, "label": label, "description": description})

    raw_variables = payload.get("variables")
    if not isinstance(raw_variables, list) or not raw_variables:
        raw_variables = []
        errors.append("variables must be a non-empty list.")
    variables: list[dict[str, Any]] = []
    for index, raw_variable in enumerate(raw_variables, start=1):
        if not isinstance(raw_variable, dict):
            errors.append(f"variables[{index}] must be an object.")
            continue
        name = str(raw_variable.get("name") or "").strip()
        mode_id = str(raw_variable.get("mode_id") or "").strip()
        description = str(raw_variable.get("description") or "").strip()
        aliases = raw_variable.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        if not isinstance(aliases, list):
            aliases = []
            errors.append(f"variables[{index}].aliases must be a list.")
        if not name:
            errors.append(f"variables[{index}].name is required.")
            continue
        if not mode_id:
            errors.append(f"variables[{index}].mode_id is required.")
        if not description:
            errors.append(f"variables[{index}].description is required.")
        variables.append(
            {
                "name": name,
                "mode_id": mode_id,
                "mode_label": str(raw_variable.get("mode_label") or mode_labels.get(mode_id) or "").strip(),
                "description": description,
                "aliases": [str(item).strip() for item in aliases if str(item or "").strip()],
            }
        )

    return VariableContextManifest(
        schema_version=schema_version_int,
        source_document=source_document,
        source_sections=source_sections,
        modes=tuple(modes),
        variables=tuple(variables),
        source_path=source_path,
        source_type=source_type,
        errors=tuple(errors),
    )


def load_variable_interaction_manifest(settings: Settings) -> DomainRulesManifest:
    fallback: DomainRulesManifest | None = None
    fallback_errors: list[str] = []
    for path, source_type in _candidate_paths(settings, DOMAIN_RULES_FILE):
        text = _read_text(path)
        if text is None:
            continue
        try:
            payload = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            fallback_errors.append(f"{source_type}:{path}:{exc}")
            continue
        manifest = _validate_manifest(payload, source_path=str(path), source_type=source_type)
        if manifest.rules and not manifest.errors:
            if fallback_errors:
                return DomainRulesManifest(
                    manifest.schema_version,
                    manifest.source_document,
                    manifest.source_section,
                    manifest.rules,
                    manifest.source_path,
                    manifest.source_type,
                    tuple(fallback_errors),
                )
            return manifest
        fallback = fallback or manifest
        fallback_errors.extend(f"{source_type}:{error}" for error in manifest.errors)

    if fallback and fallback.rules:
        return DomainRulesManifest(
            fallback.schema_version,
            fallback.source_document,
            fallback.source_section,
            fallback.rules,
            fallback.source_path,
            fallback.source_type,
            tuple(fallback_errors),
        )
    return DomainRulesManifest(1, "", "", (), "", "missing", tuple(fallback_errors or ["no manifest found."]))


def load_variable_context_manifest(settings: Settings) -> VariableContextManifest:
    fallback: VariableContextManifest | None = None
    fallback_errors: list[str] = []
    for path, source_type in _candidate_paths(settings, VARIABLE_CONTEXT_FILE):
        text = _read_text(path)
        if text is None:
            continue
        try:
            payload = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            fallback_errors.append(f"{source_type}:{path}:{exc}")
            continue
        manifest = _validate_variable_context_manifest(payload, source_path=str(path), source_type=source_type)
        if manifest.variables and not manifest.errors:
            if fallback_errors:
                return VariableContextManifest(
                    manifest.schema_version,
                    manifest.source_document,
                    manifest.source_sections,
                    manifest.modes,
                    manifest.variables,
                    manifest.source_path,
                    manifest.source_type,
                    tuple(fallback_errors),
                )
            return manifest
        fallback = fallback or manifest
        fallback_errors.extend(f"{source_type}:{error}" for error in manifest.errors)

    if fallback and fallback.variables:
        return VariableContextManifest(
            fallback.schema_version,
            fallback.source_document,
            fallback.source_sections,
            fallback.modes,
            fallback.variables,
            fallback.source_path,
            fallback.source_type,
            tuple(fallback_errors),
        )
    return VariableContextManifest(1, "", (), (), (), "", "missing", tuple(fallback_errors or ["no manifest found."]))


def _available_variable_names(*payloads: dict[str, Any] | None) -> set[str]:
    names: set[str] = set()
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            if value in (None, ""):
                continue
            key_text = str(key)
            names.add(key_text)
            names.add(key_text.upper())
            for alias in FIELD_ALIASES.get(key_text, ()):
                names.add(alias)
    return names


def _add_name_with_aliases(names: set[str], key: Any) -> None:
    key_text = str(key or "").strip()
    if not key_text:
        return
    names.add(key_text)
    names.add(key_text.upper())
    for alias in FIELD_ALIASES.get(key_text, ()):
        names.add(alias)


def _available_names_from_context_payload(payload: dict[str, Any] | None) -> set[str]:
    names: set[str] = set()
    if not isinstance(payload, dict):
        return names

    for key in ("circuit_label", "metric_key"):
        if payload.get(key) not in (None, ""):
            _add_name_with_aliases(names, key)
            _add_name_with_aliases(names, payload.get(key))

    for point in payload.get("critical_points") or []:
        if not isinstance(point, dict):
            continue
        for metric_name in (point.get("metrics") or {}).keys():
            _add_name_with_aliases(names, metric_name)
        for key in (point.get("daily_aggregates") or {}).keys():
            _add_name_with_aliases(names, key)
        if point.get("top_causes"):
            names.update({"COD_CAUSA", "DESC_CAUSA"})
        if point.get("top_circuits"):
            names.add("CIRCUITO")
        if point.get("top_equipment"):
            names.update({"FID_SW", "COD_EQ_PROTEGE", "TIPO"})
        if point.get("top_event_families"):
            names.add("TIPO")
        for key in (point.get("external_signals") or {}).keys():
            _add_name_with_aliases(names, key)
        for event in point.get("top_events") or []:
            names.update(_available_variable_names(event if isinstance(event, dict) else None))

    history = payload.get("circuit_history_12m")
    if isinstance(history, dict):
        for key in ("aggregate_totals", "trend_summary"):
            values = history.get(key)
            if isinstance(values, dict):
                for item_key in values.keys():
                    _add_name_with_aliases(names, item_key)
        for key in ("dominant_causes", "dominant_equipment", "dominant_event_families", "dominant_circuits"):
            if history.get(key):
                if key == "dominant_causes":
                    names.update({"COD_CAUSA", "DESC_CAUSA"})
                elif key == "dominant_equipment":
                    names.update({"FID_SW", "COD_EQ_PROTEGE", "TIPO"})
                elif key == "dominant_circuits":
                    names.add("CIRCUITO")
                elif key == "dominant_event_families":
                    names.add("TIPO")
        for row in history.get("daily_indicators") or []:
            if isinstance(row, dict):
                for item_key in row.keys():
                    _add_name_with_aliases(names, item_key)

    return names


def _matches(patterns: list[str], available_names: set[str]) -> list[str]:
    matched: list[str] = []
    for pattern in patterns:
        normalized_pattern = pattern.upper()
        for name in sorted(available_names):
            if fnmatchcase(name.upper(), normalized_pattern) and name not in matched:
                matched.append(name)
    return matched


def variable_interactions_payload(
    settings: Settings,
    *,
    selected_event: dict[str, Any] | None = None,
    context_payload: dict[str, Any] | None = None,
    external_signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = load_variable_interaction_manifest(settings)
    available_names = _available_variable_names(selected_event, external_signals)
    available_names.update(_available_names_from_context_payload(context_payload))
    matched_rules: list[dict[str, Any]] = []

    for rule in manifest.rules:
        origin_matches = _matches(list(rule.get("origin_variables") or []), available_names)
        destination_matches = _matches(list(rule.get("destination_variables") or []), available_names)
        if not origin_matches and not destination_matches:
            continue
        matched_rules.append(
            {
                **rule,
                "matched_origin_variables": origin_matches,
                "matched_destination_variables": destination_matches,
                "match_strength": round(float(rule.get("weight") or 0.0), 4),
            }
        )

    flags: list[str] = []
    if selected_event is None and context_payload is None:
        flags.append("no_selected_event")
    if not matched_rules:
        flags.append("no_variable_interaction_matches")

    return {
        "schema_version": manifest.schema_version,
        "source_document": manifest.source_document,
        "source_section": manifest.source_section,
        "source_path": manifest.source_path,
        "source_type": manifest.source_type,
        "rules_evaluated": len(manifest.rules),
        "matched_rules": matched_rules,
        "data_quality_flags": flags,
        "errors": list(manifest.errors),
    }


def variable_context_payload(
    settings: Settings,
    *,
    selected_event: dict[str, Any] | None = None,
    context_payload: dict[str, Any] | None = None,
    external_signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = load_variable_context_manifest(settings)
    available_names = _available_variable_names(selected_event, external_signals)
    available_names.update(_available_names_from_context_payload(context_payload))
    matched_variables: list[dict[str, Any]] = []

    for variable in manifest.variables:
        patterns = [str(variable.get("name") or ""), *list(variable.get("aliases") or [])]
        matches = _matches(patterns, available_names)
        if not matches:
            continue
        matched_variables.append(
            {
                "name": variable.get("name"),
                "mode_id": variable.get("mode_id"),
                "mode_label": variable.get("mode_label"),
                "description": variable.get("description"),
                "matched_names": matches,
            }
        )

    mode_lookup = {str(mode.get("mode_id")): mode for mode in manifest.modes}
    matched_modes: list[dict[str, Any]] = []
    for mode_id in sorted({str(item.get("mode_id")) for item in matched_variables if item.get("mode_id")}):
        mode = mode_lookup.get(mode_id, {"mode_id": mode_id, "label": "", "description": ""})
        mode_variables = [
            str(item.get("name"))
            for item in matched_variables
            if str(item.get("mode_id")) == mode_id and item.get("name")
        ]
        matched_modes.append({**mode, "matched_variables": mode_variables})

    flags: list[str] = []
    if not matched_variables:
        flags.append("no_variable_context_matches")

    return {
        "schema_version": manifest.schema_version,
        "source_document": manifest.source_document,
        "source_sections": list(manifest.source_sections),
        "source_path": manifest.source_path,
        "source_type": manifest.source_type,
        "variables_evaluated": len(manifest.variables),
        "matched_variables": matched_variables,
        "matched_modes": matched_modes,
        "data_quality_flags": flags,
        "errors": list(manifest.errors),
    }
