import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict
from src.base_utils import setup_logger

logger = setup_logger("snapshot_manager", "logs/snapshot_manager.log")


def _load_json(fp: str, default):
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _level(count: int) -> int:
    if count == 0:
        return 0
    if count == 1:
        return 1
    if count <= 3:
        return 2
    if count <= 6:
        return 3
    return 4


def get_commit_activity(entries: List[Dict], days: int = 365) -> List[Dict]:
    """
    Build a contribution-style graph from commit timestamps.
    """
    today = datetime.now(timezone.utc).date()
    window = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    counts = {d.isoformat(): 0 for d in window}

    for entry in entries:
        ts = entry.get("timestamp")
        if not isinstance(ts, str):
            continue
        try:
            dt = datetime.fromisoformat(ts)
            day = dt.date().isoformat()
            if day in counts:
                counts[day] += 1
        except Exception as err:
            logger.warning(f"Error processing entry timestamp: {err}")
            continue

    return [{"date": d, "count": counts[d], "level": _level(counts[d])} for d in counts]


def get_activity_graph(log_fp: str, days: int = 365) -> List[Dict]:
    log = _load_json(log_fp, [])
    today = datetime.now(timezone.utc).date()
    window = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    counts = {d.isoformat(): 0 for d in window}

    for entry in log:
        ts = entry.get("timestamp")
        if not isinstance(ts, str):
            continue
        try:
            dt = datetime.fromisoformat(ts)
            day = dt.date().isoformat()
            if day in counts:
                counts[day] += 1
        except Exception as err:
            logger.warning(f"Error processing log entry timestamp: {err}")
            continue

    return [
        {"date": str(day), "count": counts[day], "level": _level(counts[day])}
        for day in counts
    ]


def get_recent_events(log_fp: str, limit: int = 20) -> List[Dict]:
    log = _load_json(log_fp, [])
    try:
        log.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    except Exception as err:
        logger.warning(f"Error sorting log entries: {err}")
        pass
    return log[:limit]
