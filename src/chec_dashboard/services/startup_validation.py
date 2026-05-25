from __future__ import annotations

from pathlib import Path


REQUIRED_DATA_FILES = [
    "TRAFOS.pkl",
    "APOYOS.pkl",
    "SWITCHES.pkl",
    "REDMT.pkl",
    "SuperEventos_Criticidad_AguasAbajo_CODEs.pkl",
    "Eventos_interruptor.pkl",
    "Eventos_tramo_linea.pkl",
    "Eventos_transformador.pkl",
]


def find_missing_required_files(data_dir: Path) -> list[str]:
    return [name for name in REQUIRED_DATA_FILES if not (data_dir / name).exists()]


def build_missing_files_message(data_dir: Path, missing_files: list[str]) -> str:
    return (
        f"Data directory '{data_dir}' is missing required files: "
        f"{', '.join(sorted(missing_files))}. "
        "Upload/mount the required .pkl files before using data-driven dashboards."
    )
