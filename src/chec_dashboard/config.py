from dataclasses import dataclass
import os
from pathlib import Path


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _to_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    output_dir: Path
    host: str
    port: int
    debug: bool


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[2]
    default_data_dir = (project_root / ".." / "data").resolve()
    data_dir = Path(os.getenv("DATA_DIR", str(default_data_dir))).resolve()
    output_dir = Path(os.getenv("OUTPUT_DIR", str(project_root / "outputs"))).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        project_root=project_root,
        data_dir=data_dir,
        output_dir=output_dir,
        host=os.getenv("HOST", "0.0.0.0"),
        port=_to_int(os.getenv("PORT"), 8050),
        debug=_to_bool(os.getenv("DEBUG"), False),
    )


settings = load_settings()
