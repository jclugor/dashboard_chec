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


class ProbabilityDataResponse(APIResponseModel):
    probability_text: str
    status_text: str
    graph_name: str | None = None
    graph_data_uri: str | None = None


class DataResponse(APIResponseModel):
    mode: Literal["map", "map_metadata", "summary", "probability", "probability_metadata"]
    map: MapDataResponse | None = None
    map_metadata: MapMetadataResponse | None = None
    summary: SummaryDataResponse | None = None
    probability: ProbabilityDataResponse | None = None
    probability_metadata: ProbabilityMetadataResponse | None = None


class InferenceResponse(APIResponseModel):
    request_id: str
    backend: str
    prediction: float
    label: str
    model_version: str
    raw_response: dict[str, Any]
