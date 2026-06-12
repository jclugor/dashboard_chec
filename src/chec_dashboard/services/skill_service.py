from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
from typing import Any

import yaml

from chec_dashboard.core.config import Settings
from chec_dashboard.services.retrieval_service import read_databricks_file_text


GUIDED_SKILL_IDS = {
    "reliability": "confiabilidad",
    "compliance": "cumplimiento",
    "maintenance": "mantenimiento",
    "timeseries_interpretability": "time_series_interpretability",
}

EXPECTED_SKILL_FILES = {
    "confiabilidad": "confiabilidad.yml",
    "cumplimiento": "cumplimiento.yml",
    "mantenimiento": "mantenimiento.yml",
    "time_series_interpretability": "time_series_interpretability.yml",
    "free_form_chat": "free_form_chat.yml",
    "global_policy": "global_policy.yml",
    "retrieval_policy": "retrieval_policy.yml",
}

SUPPORTED_SKILL_SUFFIXES = (".yml", ".yaml", ".md")
SKILL_LIFECYCLE_DIRS = ("active", "draft", "archive")

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

ALLOWED_TOP_LEVEL_KEYS = {
    "skill_id",
    "version",
    "status",
    "role",
    "language",
    "tone",
    "allowed_tools",
    "instructions",
    "suggested_questions",
    "output",
    "constraints",
    "missing_evidence_behavior",
    "retrieval",
}

BLOCKED_KEY_PATTERNS = (
    "sql",
    "python",
    "code",
    "api_key",
    "secret",
    "token",
    "url",
    "endpoint",
    "model",
    "permission",
    "write",
)

BLOCKED_VALUE_PATTERNS = (
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"\b(select|insert|update|delete|drop|create|alter|merge)\b", re.IGNORECASE),
    re.compile(r"\b(import|exec|eval|def|class)\b", re.IGNORECASE),
    re.compile(r"__[a-z0-9_]+__", re.IGNORECASE),
)


@dataclass(frozen=True)
class SkillDefinition:
    skill_id: str
    version: str
    status: str
    role: str
    language: str
    tone: str
    allowed_tools: tuple[str, ...]
    instructions: tuple[str, ...]
    suggested_questions: tuple[str, ...]
    answer_sections: tuple[str, ...]
    must_cite_regulatory_claims: bool
    cannot_make_legal_conclusions: bool
    forbidden_phrases: tuple[str, ...]
    missing_evidence_behavior: str
    retrieval_backend: str
    retrieval_top_k: int | None
    retrieval_max_top_k: int | None
    retrieval_boost_tags: tuple[str, ...]
    source_type: str
    source_path: str
    skill_hash: str
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillResolution:
    skill_id: str
    skill_version: str
    skill_hash: str
    skill: SkillDefinition
    global_policy: SkillDefinition
    retrieval_policy: SkillDefinition
    validation_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillStatusItem:
    file_name: str
    skill_id: str | None
    version: str | None
    status: str | None
    source_type: str
    source_path: str
    skill_hash: str | None
    errors: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "file_name": self.file_name,
            "skill_id": self.skill_id,
            "version": self.version,
            "status": self.status,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "skill_hash": self.skill_hash,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class SkillRegistry:
    skills: dict[str, SkillDefinition] = field(default_factory=dict)
    status_items: tuple[SkillStatusItem, ...] = ()

    @property
    def errors(self) -> tuple[SkillStatusItem, ...]:
        return tuple(item for item in self.status_items if item.errors)


def _default_skills_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "agent_skills" / "active"


def _read_skill_text(path: Path) -> str | None:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return read_databricks_file_text(path)


def _skill_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _coerce_string_list(value: Any, field_name: str, errors: list[str]) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        errors.append(f"{field_name} debe ser una lista.")
        return ()
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{field_name} solo acepta textos no vacios.")
            continue
        items.append(item.strip())
    return tuple(items)


def _validate_blocked_controls(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key).strip().lower()
            if any(pattern in key_text for pattern in BLOCKED_KEY_PATTERNS):
                errors.append(f"{path}.{key} usa un control bloqueado.")
            _validate_blocked_controls(nested, f"{path}.{key}", errors)
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _validate_blocked_controls(nested, f"{path}[{index}]", errors)
        return
    if isinstance(value, str):
        for pattern in BLOCKED_VALUE_PATTERNS:
            if pattern.search(value):
                errors.append(f"{path} contiene texto bloqueado por politica.")
                break


def _validate_skill_payload(
    payload: dict[str, Any],
    *,
    source_type: str,
    source_path: str,
    skill_hash: str,
) -> SkillDefinition | tuple[str | None, str | None, str | None, tuple[str, ...]]:
    errors: list[str] = []
    unknown_keys = sorted(set(payload) - ALLOWED_TOP_LEVEL_KEYS)
    if unknown_keys:
        errors.append(f"Campos no permitidos: {', '.join(unknown_keys)}.")
    _validate_blocked_controls(payload, "skill", errors)

    skill_id = payload.get("skill_id")
    version = payload.get("version")
    status = payload.get("status", "active")
    if not isinstance(skill_id, str) or not skill_id.strip():
        errors.append("skill_id es obligatorio.")
        skill_id = None
    if not isinstance(version, (str, int, float)) or not str(version).strip():
        errors.append("version es obligatoria.")
        version = None
    if not isinstance(status, str) or status not in {"active", "draft", "archive"}:
        errors.append("status debe ser active, draft o archive.")
        status = None

    allowed_tools = _coerce_string_list(payload.get("allowed_tools"), "allowed_tools", errors)
    for tool_name in allowed_tools:
        if tool_name not in ALLOWED_TOOLS:
            errors.append(f"allowed_tools contiene una herramienta no aprobada: {tool_name}.")
    instructions = _coerce_string_list(payload.get("instructions"), "instructions", errors)
    suggested_questions = _coerce_string_list(payload.get("suggested_questions"), "suggested_questions", errors)

    output = payload.get("output") or {}
    if not isinstance(output, dict):
        errors.append("output debe ser un objeto.")
        output = {}
    answer_sections = _coerce_string_list(output.get("sections"), "output.sections", errors)

    constraints = payload.get("constraints") or {}
    if not isinstance(constraints, dict):
        errors.append("constraints debe ser un objeto.")
        constraints = {}
    forbidden_phrases = _coerce_string_list(
        constraints.get("forbidden_phrases"),
        "constraints.forbidden_phrases",
        errors,
    )

    retrieval = payload.get("retrieval") or {}
    if not isinstance(retrieval, dict):
        errors.append("retrieval debe ser un objeto.")
        retrieval = {}
    retrieval_backend = retrieval.get("backend") or "local_jsonl"
    if retrieval_backend not in {"local_jsonl", "databricks_ai_search"}:
        errors.append("retrieval.backend debe ser local_jsonl o databricks_ai_search.")
    retrieval_top_k = _optional_positive_int(retrieval.get("top_k"), "retrieval.top_k", errors)
    retrieval_max_top_k = _optional_positive_int(retrieval.get("max_top_k"), "retrieval.max_top_k", errors)
    boost_tags = _coerce_string_list(retrieval.get("boost_tags"), "retrieval.boost_tags", errors)

    if errors:
        return (
            str(skill_id).strip() if skill_id else None,
            str(version).strip() if version else None,
            status if isinstance(status, str) else None,
            tuple(errors),
        )

    return SkillDefinition(
        skill_id=str(skill_id).strip(),
        version=str(version).strip(),
        status=str(status),
        role=str(payload.get("role") or "").strip(),
        language=str(payload.get("language") or "es").strip(),
        tone=str(payload.get("tone") or "").strip(),
        allowed_tools=allowed_tools,
        instructions=instructions,
        suggested_questions=suggested_questions,
        answer_sections=answer_sections,
        must_cite_regulatory_claims=bool(constraints.get("must_cite_regulatory_claims", True)),
        cannot_make_legal_conclusions=bool(constraints.get("cannot_make_legal_conclusions", True)),
        forbidden_phrases=forbidden_phrases,
        missing_evidence_behavior=str(payload.get("missing_evidence_behavior") or "").strip(),
        retrieval_backend=str(retrieval_backend),
        retrieval_top_k=retrieval_top_k,
        retrieval_max_top_k=retrieval_max_top_k,
        retrieval_boost_tags=boost_tags,
        source_type=source_type,
        source_path=source_path,
        skill_hash=skill_hash,
    )


def _optional_positive_int(value: Any, field_name: str, errors: list[str]) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors.append(f"{field_name} debe ser un entero positivo.")
        return None
    if number < 1:
        errors.append(f"{field_name} debe ser mayor o igual a 1.")
        return None
    return number


def _parse_markdown_skill_payload(text: str) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, ("Markdown skill debe iniciar con YAML front matter delimitado por ---.",)

    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return None, ("Markdown skill debe cerrar el YAML front matter con ---.",)

    front_matter = "\n".join(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :]).strip()
    try:
        payload = yaml.safe_load(front_matter) or {}
    except yaml.YAMLError as exc:
        return None, (f"YAML front matter invalido: {exc}",)
    if not isinstance(payload, dict):
        return None, ("El YAML front matter debe contener un objeto.",)

    errors: list[str] = []
    if body:
        _validate_blocked_controls(body, "markdown.body", errors)
        existing_instructions = payload.get("instructions")
        if existing_instructions is None:
            payload["instructions"] = [body]
        elif isinstance(existing_instructions, list):
            payload["instructions"] = [*existing_instructions, body]
    return payload, tuple(errors)


def _load_skill_file(
    path: Path,
    *,
    file_name: str,
    source_type: str,
    text: str | None = None,
) -> tuple[SkillDefinition | None, SkillStatusItem | None]:
    if text is None:
        text = _read_skill_text(path)
    if text is None:
        return None, None
    skill_hash = _skill_hash(text)
    parse_errors: tuple[str, ...] = ()
    if path.suffix.lower() == ".md":
        payload, parse_errors = _parse_markdown_skill_payload(text)
        if payload is None:
            return None, SkillStatusItem(
                file_name=file_name,
                skill_id=None,
                version=None,
                status=None,
                source_type=source_type,
                source_path=str(path),
                skill_hash=skill_hash,
                errors=parse_errors,
            )
    else:
        try:
            payload = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            return None, SkillStatusItem(
                file_name=file_name,
                skill_id=None,
                version=None,
                status=None,
                source_type=source_type,
                source_path=str(path),
                skill_hash=skill_hash,
                errors=(f"YAML invalido: {exc}",),
            )
        if not isinstance(payload, dict):
            return None, SkillStatusItem(
                file_name=file_name,
                skill_id=None,
                version=None,
                status=None,
                source_type=source_type,
                source_path=str(path),
                skill_hash=skill_hash,
                errors=("El archivo debe contener un objeto YAML.",),
            )

    validated = _validate_skill_payload(
        payload,
        source_type=source_type,
        source_path=str(path),
        skill_hash=skill_hash,
    )
    if isinstance(validated, SkillDefinition):
        if parse_errors:
            return None, SkillStatusItem(
                file_name=file_name,
                skill_id=validated.skill_id,
                version=validated.version,
                status=validated.status,
                source_type=source_type,
                source_path=str(path),
                skill_hash=validated.skill_hash,
                errors=parse_errors,
            )
        return validated, SkillStatusItem(
            file_name=file_name,
            skill_id=validated.skill_id,
            version=validated.version,
            status=validated.status,
            source_type=source_type,
            source_path=str(path),
            skill_hash=validated.skill_hash,
        )
    skill_id, version, status, errors = validated
    return None, SkillStatusItem(
        file_name=file_name,
        skill_id=skill_id,
        version=version,
        status=status,
        source_type=source_type,
        source_path=str(path),
        skill_hash=skill_hash,
        errors=(*parse_errors, *errors),
    )


def _builtin_skill(skill_id: str) -> SkillDefinition:
    briefing_names = {
        "confiabilidad": "confiabilidad",
        "cumplimiento": "cumplimiento",
        "mantenimiento": "mantenimiento",
        "time_series_interpretability": "interpretabilidad de evolucion de impacto UITI",
        "global_policy": "politica global",
        "retrieval_policy": "politica de recuperacion",
        "free_form_chat": "chat libre",
    }
    return SkillDefinition(
        skill_id=skill_id,
        version="builtin-1.0",
        status="active",
        role=f"Asistente tecnico CHEC para {briefing_names.get(skill_id, skill_id)}.",
        language="es",
        tone="Tecnico, claro y prudente.",
        allowed_tools=(
            "get_dashboard_context",
            "get_timeseries_interpretability_context",
            "search_technical_documents",
        ),
        instructions=("Usar solo contexto disponible y documentos recuperados.",),
        suggested_questions=(),
        answer_sections=("Estado observado", "Datos faltantes", "Recomendaciones", "Citas"),
        must_cite_regulatory_claims=True,
        cannot_make_legal_conclusions=True,
        forbidden_phrases=("conclusion legal definitiva",),
        missing_evidence_behavior="Indicar datos faltantes antes de concluir.",
        retrieval_backend="local_jsonl",
        retrieval_top_k=None,
        retrieval_max_top_k=8 if skill_id == "retrieval_policy" else None,
        retrieval_boost_tags=(),
        source_type="builtin",
        source_path="builtin",
        skill_hash=f"builtin-{skill_id}",
    )


def load_skill_registry(settings: Settings | None = None) -> SkillRegistry:
    skills: dict[str, SkillDefinition] = {}
    status_items: list[SkillStatusItem] = []
    configured_dir = settings.chatbot_skills_dir if settings else None
    default_dir = _default_skills_dir()

    for skill_id, file_name in EXPECTED_SKILL_FILES.items():
        selected_skill: SkillDefinition | None = None
        if configured_dir is not None:
            configured_candidates = _configured_skill_candidates(configured_dir, skill_id)
            if len(configured_candidates) > 1:
                status_items.append(
                    SkillStatusItem(
                        file_name=", ".join(candidate[1] for candidate in configured_candidates),
                        skill_id=skill_id,
                        version=None,
                        status=None,
                        source_type="configured",
                        source_path=str(configured_dir),
                        skill_hash=None,
                        errors=(
                            "Multiples archivos configurados para el mismo skill; "
                            "deja solo uno de .yml, .yaml o .md.",
                        ),
                    )
                )
            elif configured_candidates:
                path, candidate_file_name, candidate_text = configured_candidates[0]
                configured_skill, configured_status = _load_skill_file(
                    path,
                    file_name=candidate_file_name,
                    source_type="configured",
                    text=candidate_text,
                )
                if configured_status is not None:
                    status_items.append(configured_status)
                if configured_skill is not None and configured_skill.status == "active":
                    selected_skill = configured_skill

        if selected_skill is None:
            default_skill, default_status = _load_skill_file(
                default_dir / file_name,
                file_name=file_name,
                source_type="default",
            )
            if default_status is not None:
                status_items.append(default_status)
            if default_skill is not None and default_skill.status == "active":
                selected_skill = default_skill

        if selected_skill is None:
            selected_skill = _builtin_skill(skill_id)
            status_items.append(
                SkillStatusItem(
                    file_name=file_name,
                    skill_id=selected_skill.skill_id,
                    version=selected_skill.version,
                    status=selected_skill.status,
                    source_type="builtin",
                    source_path="builtin",
                    skill_hash=selected_skill.skill_hash,
                )
            )
        skills[skill_id] = selected_skill

    return SkillRegistry(skills=skills, status_items=tuple(status_items))


def _configured_skill_candidates(configured_dir: Path, skill_id: str) -> list[tuple[Path, str, str]]:
    candidates: list[tuple[Path, str, str]] = []
    for suffix in SUPPORTED_SKILL_SUFFIXES:
        file_name = f"{skill_id}{suffix}"
        path = configured_dir / file_name
        text = _read_skill_text(path)
        if text is not None:
            candidates.append((path, file_name, text))
    return candidates


def resolve_skill(briefing_type: str, settings: Settings | None = None) -> SkillResolution:
    registry = load_skill_registry(settings)
    skill_id = GUIDED_SKILL_IDS.get(briefing_type, GUIDED_SKILL_IDS["reliability"])
    skill = registry.skills.get(skill_id) or _builtin_skill(skill_id)
    global_policy = registry.skills.get("global_policy") or _builtin_skill("global_policy")
    retrieval_policy = registry.skills.get("retrieval_policy") or _builtin_skill("retrieval_policy")
    validation_errors = tuple(error for item in registry.errors for error in item.errors)
    return SkillResolution(
        skill_id=skill.skill_id,
        skill_version=skill.version,
        skill_hash=skill.skill_hash,
        skill=skill,
        global_policy=global_policy,
        retrieval_policy=retrieval_policy,
        validation_errors=validation_errors,
    )


def get_skill_status(settings: Settings) -> dict[str, Any]:
    registry = load_skill_registry(settings)
    resolved_items = [
        {
            "skill_id": skill.skill_id,
            "version": skill.version,
            "status": skill.status,
            "source_type": skill.source_type,
            "source_path": skill.source_path,
            "skill_hash": skill.skill_hash,
            "errors": [],
        }
        for skill in registry.skills.values()
    ]
    validation_items = [item.to_payload() for item in registry.status_items if item.errors]
    errors_count = len(validation_items)
    return {
        "skills_available": bool(registry.skills),
        "skills_count": len(registry.skills),
        "skill_errors_count": errors_count,
        "supported_file_types": list(SUPPORTED_SKILL_SUFFIXES),
        "lifecycle_directories": _skill_lifecycle_directories(settings),
        "skills": resolved_items,
        "validation_errors": validation_items,
    }


def _skill_lifecycle_directories(settings: Settings) -> dict[str, dict[str, Any]]:
    active_dir = settings.chatbot_skills_dir or _default_skills_dir()
    root_dir = active_dir.parent if active_dir.name in SKILL_LIFECYCLE_DIRS else active_dir
    return {
        lifecycle: {
            "path": str(root_dir / lifecycle),
            "exists": (root_dir / lifecycle).exists(),
        }
        for lifecycle in SKILL_LIFECYCLE_DIRS
    }
