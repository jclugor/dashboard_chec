from __future__ import annotations

from typing import Literal

from fastapi import APIRouter

from chec_dashboard.api.schemas.requests import DataRequest
from chec_dashboard.api.schemas.responses import (
    DataMetadataResponse,
    DataResponse,
    MapMetadataResponse,
    ProbabilityMetadataResponse,
    SummaryMetadataResponse,
)
from chec_dashboard.core.config import settings
from chec_dashboard.services.data_service import (
    get_dashboard_metadata,
    get_map_filter_metadata,
    get_map_payload,
    get_map_metadata,
    get_probability_columns_metadata,
    get_probability_filter_options_metadata,
    get_probability_metadata,
    get_probability_payload,
    get_summary_metadata,
    get_summary_payload,
)


router = APIRouter(tags=["data"])


@router.get("/data", response_model=DataMetadataResponse)
def get_data_metadata(
    section: Literal["all", "map", "summary", "probability"] = "all",
) -> DataMetadataResponse:
    if section == "all":
        metadata = get_dashboard_metadata(settings)
        return DataMetadataResponse(**metadata)

    map_payload = {
        "action": None,
        "dates": [],
        "municipios": [],
        "default_date": None,
        "default_municipio": None,
        "circuits": [],
        "default_circuit": None,
        "outputs": [],
        "default_output": None,
    }
    summary_payload = {
        "circuits": [],
        "default_circuit": None,
        "min_date": None,
        "max_date": None,
        "default_start": None,
        "default_end": None,
    }
    probability_payload = {"criteria_options": []}

    if section == "map":
        map_payload = get_map_metadata(settings)
    elif section == "summary":
        summary_payload = get_summary_metadata(settings)
    elif section == "probability":
        probability_payload = get_probability_metadata(settings)

    return DataMetadataResponse(
        map=MapMetadataResponse(**map_payload),
        summary=SummaryMetadataResponse(**summary_payload),
        probability=ProbabilityMetadataResponse(**probability_payload),
    )


@router.post("/data", response_model=DataResponse)
def post_data(request: DataRequest) -> DataResponse:
    if request.mode == "map":
        if request.map is None:
            raise ValueError("map payload is required when mode='map'")
        payload = get_map_payload(
            settings=settings,
            selected_period=request.map.selected_period,
            selected_municipio=request.map.selected_municipio,
            selected_circuit=request.map.selected_circuit,
            selected_circuits=request.map.selected_circuits,
            selected_output=request.map.selected_output,
            day=request.map.day,
        )
        return DataResponse(mode="map", map=payload)

    if request.mode == "map_metadata":
        if request.map_metadata is None:
            raise ValueError("map_metadata payload is required when mode='map_metadata'")
        payload = get_map_filter_metadata(
            settings=settings,
            action=request.map_metadata.action,
            selected_period=request.map_metadata.selected_period,
            selected_municipio=request.map_metadata.selected_municipio,
        )
        return DataResponse(mode="map_metadata", map_metadata=payload)

    if request.mode == "summary":
        if request.summary is None:
            raise ValueError("summary payload is required when mode='summary'")
        payload = get_summary_payload(
            settings=settings,
            start_date_raw=request.summary.start_date,
            end_date_raw=request.summary.end_date,
            circuito=request.summary.circuito,
            metric_mode=request.summary.metric_mode,
        )
        return DataResponse(mode="summary", summary=payload)

    if request.mode == "probability":
        if request.probability is None:
            raise ValueError("probability payload is required when mode='probability'")
        payload = get_probability_payload(
            settings=settings,
            criteria=request.probability.criteria,
            target_column=request.probability.target_column,
            filters=request.probability.filters,
        )
        return DataResponse(mode="probability", probability=payload)

    if request.mode == "probability_metadata":
        if request.probability_metadata is None:
            raise ValueError("probability_metadata payload is required when mode='probability_metadata'")

        metadata = request.probability_metadata
        if metadata.action == "criteria":
            payload = get_probability_metadata(settings)
        elif metadata.action == "columns":
            payload = get_probability_columns_metadata(
                settings=settings,
                criteria=metadata.criteria or "",
            )
        elif metadata.action == "filter_options":
            payload = get_probability_filter_options_metadata(
                settings=settings,
                criteria=metadata.criteria or "",
                selected_column=metadata.selected_column or "",
                previous_filters=metadata.previous_filters,
            )
        else:
            raise ValueError(f"Unsupported probability metadata action: {metadata.action}")

        return DataResponse(mode="probability_metadata", probability_metadata=payload)

    raise ValueError(f"Unsupported mode: {request.mode}")
