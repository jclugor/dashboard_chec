from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import folium
from folium.plugins import Fullscreen, MeasureControl, MiniMap
import pandas as pd


REQUIRED_MAP_FILES = [
    "TRAFOS.pkl",
    "APOYOS.pkl",
    "SWITCHES.pkl",
    "REDMT.pkl",
    "SuperEventos_Criticidad_AguasAbajo_CODEs.pkl",
]
ALL_CIRCUITS_LABEL = "Todos"


@dataclass(frozen=True)
class MapDataset:
    trafos: pd.DataFrame
    apoyos: pd.DataFrame
    switches: pd.DataFrame
    redmt: pd.DataFrame
    super_eventos: pd.DataFrame


@dataclass(frozen=True)
class FilteredMapDataset:
    trafos: pd.DataFrame
    apoyos: pd.DataFrame
    switches: pd.DataFrame
    redmt: pd.DataFrame
    events_by_day: list[pd.DataFrame]


def _validate_data_dir(data_dir: Path) -> None:
    missing = [name for name in REQUIRED_MAP_FILES if not (data_dir / name).exists()]
    if missing:
        message = (
            f"Missing required map data files in '{data_dir}'. Missing: {', '.join(missing)}"
        )
        raise FileNotFoundError(message)


@lru_cache(maxsize=1)
def load_map_dataset(data_dir_raw: str) -> MapDataset:
    # Cached once per Python process. Multi-worker deployments still duplicate
    # this memory per worker process.
    data_dir = Path(data_dir_raw)
    _validate_data_dir(data_dir)

    trafos = pd.read_pickle(data_dir / "TRAFOS.pkl")
    apoyos = pd.read_pickle(data_dir / "APOYOS.pkl")
    switches = pd.read_pickle(data_dir / "SWITCHES.pkl")
    redmt = pd.read_pickle(data_dir / "REDMT.pkl")
    super_eventos = pd.read_pickle(data_dir / "SuperEventos_Criticidad_AguasAbajo_CODEs.pkl")

    for frame in [trafos, apoyos, switches, redmt]:
        frame["FECHA"] = pd.to_datetime(frame["FECHA"], errors="coerce")
        if "CODE" in frame.columns:
            frame.rename(columns={"CODE": "equipo_ope"}, inplace=True)

    super_eventos["inicio"] = pd.to_datetime(super_eventos["inicio"], errors="coerce")

    return MapDataset(
        trafos=trafos,
        apoyos=apoyos,
        switches=switches,
        redmt=redmt,
        super_eventos=super_eventos,
    )


@lru_cache(maxsize=1)
def load_map_filter_options(data_dir_raw: str) -> tuple[list[str], list[str]]:
    # Metadata for dropdowns only needs TRAFOS.pkl. Avoid loading the full map
    # dataset during Azure cold start; full data still loads lazily on map render.
    data_dir = Path(data_dir_raw)
    missing = "TRAFOS.pkl"
    if not (data_dir / missing).exists():
        raise FileNotFoundError(f"Missing required map data file in '{data_dir}': {missing}")

    trafos = pd.read_pickle(data_dir / "TRAFOS.pkl")
    trafos["FECHA"] = pd.to_datetime(trafos["FECHA"], errors="coerce")

    periods = (
        trafos["FECHA"]
        .dropna()
        .dt.to_period("M")
        .drop_duplicates()
        .sort_values()
        .to_list()
    )
    dates = [period.strftime("%Y-%m") for period in periods]
    municipios = sorted(trafos["MUN"].dropna().astype(str).unique().tolist())
    return dates, municipios


def get_map_filter_options(dataset: MapDataset) -> tuple[list[str], list[str]]:
    periods = (
        dataset.trafos["FECHA"]
        .dropna()
        .dt.to_period("M")
        .drop_duplicates()
        .sort_values()
        .to_list()
    )
    dates = [period.strftime("%Y-%m") for period in periods]
    municipios = sorted(dataset.trafos["MUN"].dropna().astype(str).unique().tolist())
    return dates, municipios


def _parse_period(selected_period: str) -> tuple[int, int]:
    year, month = selected_period.split("-")
    return int(year), int(month)


def _asset_period_municipio_mask(
    frame: pd.DataFrame,
    *,
    target_year: int,
    target_month: int,
    selected_municipio: str,
) -> pd.Series:
    return (
        (frame["FECHA"].dt.year == target_year)
        & (frame["FECHA"].dt.month == target_month)
        & (frame["MUN"].astype(str) == selected_municipio)
    )


def _events_period_municipio_mask(
    frame: pd.DataFrame,
    *,
    target_year: int,
    target_month: int,
    selected_municipio: str,
) -> pd.Series:
    return (
        (frame["inicio"].dt.year == target_year)
        & (frame["inicio"].dt.month == target_month)
        & (frame["MUN"].astype(str) == selected_municipio)
    )


def _normalize_circuit_value(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _is_all_circuit(value: str | None) -> bool:
    normalized = _normalize_circuit_value(value)
    return normalized is None or normalized.casefold() == ALL_CIRCUITS_LABEL.casefold()


def get_map_circuit_options(
    dataset: MapDataset,
    *,
    selected_period: str,
    selected_municipio: str,
) -> list[str]:
    target_year, target_month = _parse_period(selected_period)
    circuit_values: set[str] = set()

    for frame in (dataset.trafos, dataset.switches, dataset.redmt):
        filtered = frame.loc[
            _asset_period_municipio_mask(
                frame,
                target_year=target_year,
                target_month=target_month,
                selected_municipio=selected_municipio,
            )
        ]
        if "FPARENT" in filtered.columns:
            circuit_values.update(
                value
                for value in filtered["FPARENT"].dropna().astype(str).str.strip().tolist()
                if value
            )

    filtered_events = dataset.super_eventos.loc[
        _events_period_municipio_mask(
            dataset.super_eventos,
            target_year=target_year,
            target_month=target_month,
            selected_municipio=selected_municipio,
        )
    ]
    if "cto_equi_ope" in filtered_events.columns:
        circuit_values.update(
            value
            for value in filtered_events["cto_equi_ope"].dropna().astype(str).str.strip().tolist()
            if value
        )

    return [ALL_CIRCUITS_LABEL, *sorted(circuit_values)]


def filter_map_dataset(
    dataset: MapDataset,
    selected_period: str,
    selected_municipio: str,
    selected_circuit: str | None = None,
    selected_output: str | None = None,
) -> FilteredMapDataset:
    if selected_output not in {None, "", "BASE"}:
        raise ValueError(f"Salida de mapa no soportada: {selected_output}")

    target_year, target_month = _parse_period(selected_period)
    selected_circuit = _normalize_circuit_value(selected_circuit)

    def _filter_asset(frame: pd.DataFrame) -> pd.DataFrame:
        filtered = frame.loc[
            _asset_period_municipio_mask(
                frame,
                target_year=target_year,
                target_month=target_month,
                selected_municipio=selected_municipio,
            )
        ]
        if _is_all_circuit(selected_circuit) or "FPARENT" not in filtered.columns:
            return filtered
        return filtered.loc[filtered["FPARENT"].astype(str).str.strip() == selected_circuit]

    filtered_events = dataset.super_eventos.loc[
        _events_period_municipio_mask(
            dataset.super_eventos,
            target_year=target_year,
            target_month=target_month,
            selected_municipio=selected_municipio,
        )
    ]
    if not _is_all_circuit(selected_circuit) and "cto_equi_ope" in filtered_events.columns:
        filtered_events = filtered_events.loc[
            filtered_events["cto_equi_ope"].astype(str).str.strip() == selected_circuit
        ]

    filtered_apoyos = _filter_asset(dataset.apoyos)
    if not _is_all_circuit(selected_circuit):
        filtered_apoyos = filtered_apoyos.iloc[0:0].copy()

    events_by_day: list[pd.DataFrame] = []
    for day in range(1, 32):
        events_by_day.append(filtered_events[filtered_events["inicio"].dt.day == day])

    return FilteredMapDataset(
        trafos=_filter_asset(dataset.trafos),
        apoyos=filtered_apoyos,
        switches=_filter_asset(dataset.switches),
        redmt=_filter_asset(dataset.redmt),
        events_by_day=events_by_day,
    )


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _safe_coordinates(row: pd.Series, lat_col: str, lon_col: str) -> tuple[float, float] | None:
    lat = row.get(lat_col)
    lon = row.get(lon_col)
    if pd.isna(lat) or pd.isna(lon):
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def _map_center(filtered: FilteredMapDataset, day_events: pd.DataFrame) -> list[float]:
    candidates = [
        (filtered.switches, "LATITUD", "LONGITUD"),
        (filtered.apoyos, "LATITUD", "LONGITUD"),
        (filtered.trafos, "LATITUD", "LONGITUD"),
        (day_events, "LATITUD", "LONGITUD"),
    ]
    for frame, lat_col, lon_col in candidates:
        if frame.empty:
            continue
        lat = pd.to_numeric(frame[lat_col], errors="coerce").dropna()
        lon = pd.to_numeric(frame[lon_col], errors="coerce").dropna()
        if not lat.empty and not lon.empty:
            return [float(lat.mean()), float(lon.mean())]
    return [5.0, -75.5]


def _append_bounds(bounds: list[tuple[float, float]], point: tuple[float, float] | None) -> None:
    if point is not None:
        bounds.append(point)


def render_base_map(filtered: FilteredMapDataset, day: int) -> str:
    safe_day = min(max(day, 1), 31)
    day_events = filtered.events_by_day[safe_day - 1]
    center = _map_center(filtered, day_events)
    map_view = folium.Map(
        location=center,
        zoom_start=13,
        width="100%",
        height="100%",
        tiles=None,
        control_scale=True,
    )
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", overlay=False).add_to(map_view)
    folium.TileLayer("CartoDB positron", name="Carto Positron", overlay=False).add_to(map_view)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Esri Topo",
        overlay=False,
    ).add_to(map_view)

    redmt_group = folium.FeatureGroup(name="Red MT", show=True).add_to(map_view)
    apoyos_group = folium.FeatureGroup(name="Apoyos", show=False).add_to(map_view)
    trafos_group = folium.FeatureGroup(name="Trafos", show=True).add_to(map_view)
    switches_group = folium.FeatureGroup(name="Seccionadores", show=True).add_to(map_view)
    eventos_group = folium.FeatureGroup(name="Eventos", show=True).add_to(map_view)

    bounds: list[tuple[float, float]] = []

    legend_html = """
    <div style="position: fixed;
                bottom: 14px; right: 14px; width: 116px;
                background-color: rgba(255, 255, 255, 0.92);
                border: 1px solid #0b5d25; border-radius: 8px;
                z-index: 9999; font-size: 11px; line-height: 1.3;
                padding: 8px 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.18);">
        <div style="font-weight:700; margin-bottom:4px;">Capas</div>
        <div><i style="background-color:blue; width: 10px; height: 10px; display: inline-block; border-radius: 50%;"></i> Apoyos</div>
        <div><i style="background-color:green; width: 10px; height: 10px; display: inline-block; border-radius: 50%;"></i> Trafos</div>
        <div><i style="background-color:brown; width: 10px; height: 10px; display: inline-block; border-radius: 50%;"></i> Seccionadores</div>
        <div><i style="background-color:black; width: 10px; height: 10px; display: inline-block;"></i> Red MT</div>
        <div><i style="background-color:red; width: 10px; height: 10px; display: inline-block; border-radius: 50%;"></i> Eventos</div>
    </div>
    """
    map_view.get_root().html.add_child(folium.Element(legend_html))

    for _, row in filtered.redmt.iterrows():
        p1 = _safe_coordinates(row, "LATITUD", "LONGITUD")
        p2 = _safe_coordinates(row, "LATITUD2", "LONGITUD2")
        if p1 is None or p2 is None:
            continue
        _append_bounds(bounds, p1)
        _append_bounds(bounds, p2)
        popup_text = (
            "Tramo de linea\n"
            f"Material conductor: {_format_value(row.get('MATERIALCONDUCTOR'))}\n"
            f"Tipo conductor: {_format_value(row.get('TIPOCONDUCTOR'))}\n"
            f"Largo: {_format_value(row.get('LENGTH'))}\n"
            f"Calibre conductor: {_format_value(row.get('CALIBRECONDUCTOR'))}\n"
            f"Guarda conductor: {_format_value(row.get('GUARDACONDUCTOR'))}\n"
            f"Neutro conductor: {_format_value(row.get('NEUTROCONDUCTOR'))}\n"
            f"Calibre neutro: {_format_value(row.get('CALIBRENEUTRO'))}\n"
            f"Capacidad: {_format_value(row.get('CAPACITY'))}\n"
            f"Resistencia: {_format_value(row.get('RESISTANCE'))}\n"
            f"Acometida conductor: {_format_value(row.get('ACOMETIDACONDUCTOR'))}"
        )
        line = folium.PolyLine(locations=[p1, p2], color="black", weight=1.3, opacity=0.82)
        line.add_child(folium.Popup(popup_text))
        line.add_to(redmt_group)

    for _, row in filtered.apoyos.iterrows():
        point = _safe_coordinates(row, "LATITUD", "LONGITUD")
        if point is None:
            continue
        _append_bounds(bounds, point)
        folium.CircleMarker(
            location=point,
            radius=1.6,
            color="blue",
            fill=True,
            fill_color="cyan",
            fill_opacity=0.45,
            popup=(
                f"Apoyo Propietario: {_format_value(row.get('TOWNER'))}\n"
                f"Tipo: {_format_value(row.get('TIPO'))}\n"
                f"Clase: {_format_value(row.get('CLASE'))}\n"
                f"Material: {_format_value(row.get('MATERIAL'))}\n"
                f"Longitud: {_format_value(row.get('LONG_APOYO'))}\n"
                f"Tierra pie: {_format_value(row.get('TIERRA_PIE'))}\n"
                f"Vientos: {_format_value(row.get('VIENTOS'))}"
            ),
        ).add_to(apoyos_group)

    for _, row in filtered.trafos.iterrows():
        point = _safe_coordinates(row, "LATITUD", "LONGITUD")
        if point is None:
            continue
        _append_bounds(bounds, point)
        date_fab = _format_value(row.get("DATE_FAB"))[:10]
        folium.CircleMarker(
            location=point,
            radius=2.4,
            color="green",
            fill=True,
            fill_color="green",
            fill_opacity=0.55,
            popup=(
                f"Trafo Fase: {_format_value(row.get('PHASES'))}\n"
                f"Propietario: {_format_value(row.get('OWNER1'))}\n"
                f"Impedancia: {_format_value(row.get('IMPEDANCE'))}\n"
                f"Marca: {_format_value(row.get('MARCA'))}\n"
                f"Fecha de fabricación: {date_fab}\n"
                f"Tipo de subestación: {_format_value(row.get('TIPO_SUB'))}\n"
                f"KVA: {_format_value(row.get('KVA'))}\n"
                f"KV1: {_format_value(row.get('KV1'))}\n"
                f"FPARENT: {_format_value(row.get('FPARENT'))}"
            ),
        ).add_to(trafos_group)

    for _, row in filtered.switches.iterrows():
        point = _safe_coordinates(row, "LATITUD", "LONGITUD")
        if point is None:
            continue
        _append_bounds(bounds, point)
        folium.CircleMarker(
            location=point,
            radius=2.3,
            color="brown",
            fill=True,
            fill_color="brown",
            fill_opacity=0.55,
            popup=(
                f"Seccionador - Fase: {_format_value(row.get('PHASES'))}\n"
                f"Código de ensamble: {_format_value(row.get('ASSEMBLY'))}\n"
                f"KV: {_format_value(row.get('KV'))}\n"
                f"Estado: {_format_value(row.get('STATE'))}"
            ),
        ).add_to(switches_group)

    for _, row in day_events.iterrows():
        point = _safe_coordinates(row, "LATITUD", "LONGITUD")
        if point is None:
            continue
        _append_bounds(bounds, point)
        popup_text = (
            "Evento\n"
            f"Equipo operó: {_format_value(row.get('equipo_ope'))}\n"
            f"Tipo equipo: {_format_value(row.get('tipo_equi_ope'))}\n"
            f"Circuito operó: {_format_value(row.get('cto_equi_ope'))}\n"
            f"Tipo elemento: {_format_value(row.get('tipo_elemento'))}\n"
            f"Duración: {_format_value(row.get('duracion_h'))}\n"
            f"Causa: {_format_value(row.get('causa'))}\n"
            f"Usuarios afectados: {_format_value(row.get('cnt_usus'))}\n"
            f"SAIDI: {_format_value(row.get('SAIDI'))}\n"
            f"Inicio: {_format_value(row.get('inicio'))}\n"
            f"Fin: {_format_value(row.get('fin'))}"
        )
        folium.CircleMarker(
            location=point,
            popup=popup_text,
            radius=5,
            color="#bf0d0d",
            fill=True,
            fill_color="#ff4d4d",
            fill_opacity=0.75,
        ).add_to(eventos_group)

    if bounds:
        min_lat = min(point[0] for point in bounds)
        max_lat = max(point[0] for point in bounds)
        min_lon = min(point[1] for point in bounds)
        max_lon = max(point[1] for point in bounds)
        map_view.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

    Fullscreen(position="topleft", title="Pantalla completa", title_cancel="Salir").add_to(map_view)
    MiniMap(toggle_display=True, minimized=True, position="bottomleft").add_to(map_view)
    MeasureControl(
        position="topright",
        primary_length_unit="kilometers",
        secondary_length_unit="meters",
    ).add_to(map_view)
    folium.LayerControl(collapsed=True).add_to(map_view)

    return map_view._repr_html_()
