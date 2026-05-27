from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class APIRequestModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=("model_validate", "model_dump"))


class MapDataPayload(APIRequestModel):
    selected_period: str
    selected_municipio: str
    selected_circuit: str | None = None
    selected_circuits: list[str] | None = None
    selected_output: str | None = None
    day: int = Field(default=1, ge=1, le=31)


class MapMetadataPayload(APIRequestModel):
    action: Literal["circuits"]
    selected_period: str
    selected_municipio: str


class SummaryDataPayload(APIRequestModel):
    start_date: str | None = None
    end_date: str | None = None
    circuito: str | None = None
    metric_mode: Literal["SAIDI", "SAIFI", "BOTH"] = "BOTH"


class ProbabilityDataPayload(APIRequestModel):
    criteria: str
    target_column: str
    filters: list[list[Any]] = Field(default_factory=list)


class ProbabilityMetadataPayload(APIRequestModel):
    action: Literal["criteria", "columns", "filter_options"]
    criteria: str | None = None
    selected_column: str | None = None
    previous_filters: list[list[Any]] = Field(default_factory=list)


class DataRequest(APIRequestModel):
    mode: Literal["map", "map_metadata", "summary", "probability", "probability_metadata"]
    map: MapDataPayload | None = None
    map_metadata: MapMetadataPayload | None = None
    summary: SummaryDataPayload | None = None
    probability: ProbabilityDataPayload | None = None
    probability_metadata: ProbabilityMetadataPayload | None = None


class InferenceRequest(APIRequestModel):
    features: dict[str, Any]
    context: dict[str, Any] = Field(default_factory=dict)
