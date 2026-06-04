from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class APIResponseModel(BaseModel):
    # Keep safety for actual BaseModel method collisions while allowing
    # response fields like model_backend/model_version across Pydantic versions.
    model_config = ConfigDict(protected_namespaces=("model_validate", "model_dump"))


class ErrorResponse(APIResponseModel):
    detail: str
    error_type: str | None = None


class HealthResponse(APIResponseModel):
    status: str
    environment: str
    model_backend: str
    cache_enabled: bool


class ReadinessCheck(APIResponseModel):
    ok: bool
    message: str


class ReadinessResponse(APIResponseModel):
    status: str
    ready: bool
    environment: str
    model_backend: str
    checks: dict[str, ReadinessCheck]


class MapMetadataResponse(APIResponseModel):
    action: str | None = None
    dates: list[str] = Field(default_factory=list)
    municipios: list[str] = Field(default_factory=list)
    default_date: str | None = None
    default_municipio: str | None = None
    circuits: list[str] = Field(default_factory=list)
    default_circuit: str | None = None
    outputs: list[str] = Field(default_factory=list)
    default_output: str | None = None


class SummaryMetadataResponse(APIResponseModel):
    circuits: list[str] = Field(default_factory=list)
    default_circuit: str | None = None
    min_date: str | None = None
    max_date: str | None = None
    default_start: str | None = None
    default_end: str | None = None


class ProbabilityMetadataResponse(APIResponseModel):
    action: str = "criteria"
    criteria_options: list[dict[str, str]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    filter_kind: str | None = None
    value_options: list[str] = Field(default_factory=list)
    is_empty: bool = False
    message: str | None = None


class DataMetadataResponse(APIResponseModel):
    map: MapMetadataResponse
    summary: SummaryMetadataResponse
    probability: ProbabilityMetadataResponse


class SummaryDailyPoint(APIResponseModel):
    fecha_dia: str
    SAIDI: float
    SAIFI: float


class MapDataResponse(APIResponseModel):
    map_html: str
    current_day: int
    status_text: str


class SummaryDataResponse(APIResponseModel):
    start_date: str
    end_date: str
    circuit_label: str
    metric_mode: str
    saidi_total: float
    saifi_total: float
    event_count: int
    daily_data: list[SummaryDailyPoint]
    status_text: str


class CriticalityReason(APIResponseModel):
    reason_type: str
    metric: Literal["SAIDI", "SAIFI", "BOTH", "DATA_QUALITY"]
    score: float
    value: float | None = None
    baseline: float | None = None
    threshold: float | None = None
    detail: str


class AttributionItem(APIResponseModel):
    label: str
    event_count: int = 0
    saidi_total: float = 0.0
    saifi_total: float = 0.0
    duration_total_h: float = 0.0
    users_affected_total: float = 0.0
    contribution_pct: float | None = None


class CriticalEvent(APIResponseModel):
    event_id: str | None = None
    evento: str | None = None
    inicio_ts: str | None = None
    fin_ts: str | None = None
    causa: str | None = None
    event_family: str | None = None
    circuito: str | None = None
    municipio: str | None = None
    equipo_ope: str | None = None
    tipo_equi_ope: str | None = None
    tipo_elemento: str | None = None
    duration_hours: float = 0.0
    severity_saidi: float = 0.0
    severity_saifi: float = 0.0
    cnt_usus: float = 0.0


class CriticalPoint(APIResponseModel):
    fecha_dia: str
    rank: int
    criticality_score: float
    criticality_types: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    reasons: list[CriticalityReason] = Field(default_factory=list)
    daily_aggregates: dict[str, Any] = Field(default_factory=dict)
    top_causes: list[AttributionItem] = Field(default_factory=list)
    top_event_families: list[AttributionItem] = Field(default_factory=list)
    top_equipment: list[AttributionItem] = Field(default_factory=list)
    top_circuits: list[AttributionItem] = Field(default_factory=list)
    top_events: list[CriticalEvent] = Field(default_factory=list)
    external_signals: dict[str, Any] = Field(default_factory=dict)
    data_quality_flags: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


class CriticalPeriod(APIResponseModel):
    start_date: str
    end_date: str
    metric: Literal["SAIDI", "SAIFI"]
    period_type: str
    score: float
    days: int
    summary: str


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


class ProbabilityDataResponse(APIResponseModel):
    probability_text: str
    status_text: str
    graph_name: str | None = None
    graph_data_uri: str | None = None


class DataResponse(APIResponseModel):
    mode: Literal[
        "map",
        "map_metadata",
        "summary",
        "summary_interpretability",
        "probability",
        "probability_metadata",
    ]
    map: MapDataResponse | None = None
    map_metadata: MapMetadataResponse | None = None
    summary: SummaryDataResponse | None = None
    summary_interpretability: SummaryInterpretabilityResponse | None = None
    probability: ProbabilityDataResponse | None = None
    probability_metadata: ProbabilityMetadataResponse | None = None


class InferenceResponse(APIResponseModel):
    request_id: str
    backend: str
    prediction: float
    label: str
    model_version: str
    raw_response: dict[str, Any]
