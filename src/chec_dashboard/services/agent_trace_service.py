from __future__ import annotations

import uuid


def create_trace_id() -> str:
    return f"trace-{uuid.uuid4().hex}"
