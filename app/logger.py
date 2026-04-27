from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from app.models import DecisionResult


PARIS_TZ = ZoneInfo("Europe/Paris")


def now_paris_iso() -> str:
    return datetime.now(PARIS_TZ).isoformat()


def result_to_log_record(result: DecisionResult, source: str = "decision-latest") -> dict[str, Any]:
    record = result.model_dump()
    record["decision_id"] = str(uuid.uuid4())
    record["timestamp_europe_paris"] = now_paris_iso()
    record["source"] = source
    return record


def append_jsonl(result: DecisionResult, log_path: str | None = None) -> dict[str, Any]:
    path = Path(log_path or os.getenv("LOG_PATH", "/tmp/trading_log.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)

    record = result_to_log_record(result)

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    return record
