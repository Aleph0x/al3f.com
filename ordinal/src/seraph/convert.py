from __future__ import annotations

import json
import sqlite3
from typing import Any

from .models import CommitRecord


def _to_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except Exception:
        return None


def _parse_meta(meta_json: Any) -> dict[str, Any]:
    if not meta_json:
        return {}
    try:
        return json.loads(str(meta_json))
    except Exception:
        return {}


def row_to_commit(row: sqlite3.Row) -> CommitRecord:
    return CommitRecord(
        id=int(row["id"]),
        hash=str(row["hash"]),
        slug=str(row["slug"]),
        timestamp=str(row["timestamp"]),
        parent_hash=row["parent_hash"],
        title=row["title"],
        created=row["created"],
        word_count=row["word_count"],
        word_delta=row["word_delta"],
        worked_hours=_to_float(row["worked_hours"]),
        meta=_parse_meta(row["meta_json"]),
    )
