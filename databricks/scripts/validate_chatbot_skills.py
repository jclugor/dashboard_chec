#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from chec_dashboard.core.config import settings as base_settings  # noqa: E402
from chec_dashboard.services.skill_service import get_skill_status  # noqa: E402


def main(argv: list[str]) -> int:
    skills_dir = Path(argv[1]).resolve() if len(argv) > 1 else ROOT / "src" / "chec_dashboard" / "agent_skills" / "active"
    status = get_skill_status(replace(base_settings, chatbot_skills_dir=skills_dir))
    errors = status.get("validation_errors") or []

    print(f"Validating governed chatbot skills in {skills_dir}")
    print(f"Resolved skills: {status.get('skills_count', 0)}")
    print(f"Supported file types: {', '.join(status.get('supported_file_types') or [])}")
    if not errors:
        print("Skill validation passed.")
        return 0

    print("Skill validation failed:", file=sys.stderr)
    for item in errors:
        file_name = item.get("file_name") or item.get("source_path") or "unknown"
        for error in item.get("errors") or []:
            print(f"- {file_name}: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
