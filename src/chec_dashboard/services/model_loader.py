from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any


@dataclass
class LocalMockModel:
    model_name: str = "local-mock-model"
    model_version: str = "0.1.0"

    def predict(self, features: dict[str, Any]) -> float:
        numeric_values: list[float] = []
        for value in features.values():
            if isinstance(value, bool):
                numeric_values.append(float(int(value)))
            elif isinstance(value, (int, float)):
                numeric_values.append(float(value))
        if not numeric_values:
            return 0.5
        return max(0.0, min(1.0, sum(numeric_values) / (len(numeric_values) * 100.0)))


@lru_cache(maxsize=1)
def load_local_model() -> LocalMockModel:
    """Lazy-load a local model once per process.

    Note: each Gunicorn/Uvicorn worker loads its own model instance and memory.
    Keep worker counts conservative when large models are used.
    """

    return LocalMockModel()
