from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


NARRATIVE_SCHEMA_VERSION = "1"

Confidence = Literal["high", "medium", "low"]
StatusSeverity = Literal["ok", "warning", "error"]
NarrativeSource = Literal["llm", "deterministic", "validated_repair"]


class InterpretabilityModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=("model_validate", "model_dump"))


class EvidenceReference(InterpretabilityModel):
    citation_index: int | None = None
    title: str | None = None
    source_type: str | None = None
    supports: str


class PointNarrative(InterpretabilityModel):
    fecha_dia: str
    rank: int
    headline: str
    confidence: Confidence = "medium"
    why_marked: list[str] = Field(default_factory=list)
    observed_values: list[str] = Field(default_factory=list)
    likely_drivers: list[str] = Field(default_factory=list)
    domain_support: list[str] = Field(default_factory=list)
    documentary_support: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)
    citations_used: list[int] = Field(default_factory=list)


class ReferencedEvent(InterpretabilityModel):
    date: str | None = None
    indicator_value: float | int | None = None
    selection_reason: str | None = None


class PeriodFinding(InterpretabilityModel):
    title: str
    text: str
    referenced_events: list[ReferencedEvent] = Field(default_factory=list)
    variable_groups_used: list[str] = Field(default_factory=list)


class EvidenceMatrixRow(InterpretabilityModel):
    fecha_dia: str | None = None
    signal: str
    structured_evidence: str
    domain_evidence: str | None = None
    documentary_evidence: str | None = None
    confidence: Confidence = "medium"
    citations_used: list[int] = Field(default_factory=list)


class TimeseriesInterpretabilityNarrative(InterpretabilityModel):
    source: NarrativeSource = "llm"
    headline: str
    section_title: str = "Hallazgos del periodo"
    executive_summary: list[str] = Field(default_factory=list)
    key_findings: list[PeriodFinding] = Field(default_factory=list)
    period_synthesis: str | None = None
    point_narratives: list[PointNarrative] = Field(default_factory=list)
    period_narratives: list[str] = Field(default_factory=list)
    evidence_matrix: list[EvidenceMatrixRow] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    citations_used: list[int] = Field(default_factory=list)

    @field_validator("key_findings", mode="before")
    @classmethod
    def _coerce_key_findings(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        raw_items = value if isinstance(value, list) else [value]
        findings: list[Any] = []
        for index, item in enumerate(raw_items, start=1):
            if isinstance(item, PeriodFinding):
                findings.append(item)
                continue
            if isinstance(item, str):
                text = item.strip()
                if text:
                    findings.append({"title": f"Hallazgo {index}", "text": text})
                continue
            if isinstance(item, dict):
                cleaned = dict(item)
                text = str(
                    cleaned.get("text")
                    or cleaned.get("description")
                    or cleaned.get("summary")
                    or cleaned.get("finding")
                    or ""
                ).strip()
                title = str(cleaned.get("title") or f"Hallazgo {index}").strip()
                if text:
                    cleaned["title"] = title
                    cleaned["text"] = text
                    findings.append(cleaned)
                continue
            text = str(item or "").strip()
            if text:
                findings.append({"title": f"Hallazgo {index}", "text": text})
        return findings


class InterpretabilityStatus(InterpretabilityModel):
    text: str
    severity: StatusSeverity = "ok"
    data_quality_flags: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: str | None = None


class InterpretabilityTrace(InterpretabilityModel):
    mode: str
    narrative_schema_version: str = NARRATIVE_SCHEMA_VERSION
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
