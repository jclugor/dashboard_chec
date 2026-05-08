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


def filter_map_dataset(
    dataset: MapDataset,
    selected_period: str,
    selected_municipio: str,
) -> FilteredMapDataset:
    year, month = selected_period.split("-")
    target_year = int(year)
    target_month = int(month)

    def _filter_asset(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.loc[
            (frame["FECHA"].dt.year == target_year)
            & (frame["FECHA"].dt.month == target_month)
            & (frame["MUN"] == selected_municipio)
        ]

    filtered_events = dataset.super_eventos.loc[
        (dataset.super_eventos["inicio"].dt.year == target_year)
        & (dataset.super_eventos["inicio"].dt.month == target_month)
        & (dataset.super_eventos["MUN"] == selected_municipio)
    ]
    events_by_day: list[pd.DataFrame] = []
    for day in range(1, 32):
        events_by_day.append(filtered_events[filtered_events["inicio"].dt.day == day])

    return FilteredMapDataset(
        trafos=_filter_asset(dataset.trafos),
        apoyos=_filter_asset(dataset.apoyos),
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
    apoyos_group = folium.FeatureGroup(name="Apoyos", show=True).add_to(map_view)
    trafos_group = folium.FeatureGroup(name="Trafos", show=True).add_to(map_view)
    switches_group = folium.FeatureGroup(name="Switches", show=True).add_to(map_view)
    eventos_group = folium.FeatureGroup(name="Eventos", show=True).add_to(map_view)

    bounds: list[tuple[float, float]] = []

    legend_html = """
    <div style="position: fixed;
                top: 10px; right: 10px; width: 95px; height: 120px;
                background-color: white; border: 2px solid black;
                z-index: 9999; font-size: 12px; padding: 8px; opacity: 0.7;">
        <i style="background-color:blue; width: 15px; height: 15px; display: inline-block;"></i> Apoyos<br>
        <i style="background-color:green; width: 15px; height: 15px; display: inline-block;"></i> Trafos<br>
        <i style="background-color:brown; width: 15px; height: 15px; display: inline-block;"></i> Switches<br>
        <i style="background-color:black; width: 15px; height: 15px; display: inline-block;"></i> Red MT<br>
        <i style="background-color:red; width: 15px; height: 15px; display: inline-block;"></i> Eventos<br>
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
        line = folium.PolyLine(locations=[p1, p2], color="black", weight=1.5, opacity=1)
        line.add_child(folium.Popup(popup_text))
        line.add_to(redmt_group)

    for _, row in filtered.apoyos.iterrows():
        point = _safe_coordinates(row, "LATITUD", "LONGITUD")
        if point is None:
            continue
        _append_bounds(bounds, point)
        folium.CircleMarker(
            location=point,
            radius=2,
            color="blue",
            fill=True,
            fill_color="cyan",
            fill_opacity=0.6,
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
            radius=2,
            color="green",
            fill=True,
            fill_color="green",
            fill_opacity=0.6,
            popup=(
                f"Trafo Fase: {_format_value(row.get('PHASES'))}\n"
                f"Propietario: {_format_value(row.get('OWNER1'))}\n"
                f"Impedancia: {_format_value(row.get('IMPEDANCE'))}\n"
                f"Marca: {_format_value(row.get('MARCA'))}\n"
                f"Fecha fabricacion: {date_fab}\n"
                f"Tipo subestacion: {_format_value(row.get('TIPO_SUB'))}\n"
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
            radius=2,
            color="brown",
            fill=True,
            fill_color="brown",
            fill_opacity=0.6,
            popup=(
                f"Switche Fase: {_format_value(row.get('PHASES'))}\n"
                f"Codigo assembly: {_format_value(row.get('ASSEMBLY'))}\n"
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
            f"Equipo opero: {_format_value(row.get('equipo_ope'))}\n"
            f"Tipo equipo: {_format_value(row.get('tipo_equi_ope'))}\n"
            f"Circuito opero: {_format_value(row.get('cto_equi_ope'))}\n"
            f"Tipo elemento: {_format_value(row.get('tipo_elemento'))}\n"
            f"Duracion: {_format_value(row.get('duracion_h'))}\n"
            f"Causa: {_format_value(row.get('causa'))}\n"
            f"Cantidad usuarios: {_format_value(row.get('cnt_usus'))}\n"
            f"SAIDI: {_format_value(row.get('SAIDI'))}\n"
            f"Inicio: {_format_value(row.get('inicio'))}\n"
            f"Fin: {_format_value(row.get('fin'))}"
        )
        folium.Marker(
            location=point,
            popup=popup_text,
            icon=folium.Icon(icon="exclamation-triangle", prefix="fa", color="red"),
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
        position="topleft",
        primary_length_unit="kilometers",
        secondary_length_unit="meters",
    ).add_to(map_view)
    folium.LayerControl(collapsed=False).add_to(map_view)

    return map_view._repr_html_()
