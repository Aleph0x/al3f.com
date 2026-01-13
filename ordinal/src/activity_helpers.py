import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict
from src.base_utils import setup_logger

ACTIVITY_LEVEL_THRESHOLDS = (0, 1, 3, 6)

logger = setup_logger("snapshot_manager", "logs/snapshot_manager.log")


def _load_json(fp: str, default):
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _level(count: int) -> int:
    """
    Map a daily change count to a 0-4 intensity bucket used by the activity graph.
    """
    if count <= ACTIVITY_LEVEL_THRESHOLDS[0]:
        return 0
    if count <= ACTIVITY_LEVEL_THRESHOLDS[1]:
        return 1
    if count <= ACTIVITY_LEVEL_THRESHOLDS[2]:
        return 2
    if count <= ACTIVITY_LEVEL_THRESHOLDS[3]:
        return 3
    return 4


def _build_activity_graph(entries: List[Dict], days: int = 365) -> List[Dict]:
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


def get_commit_activity(entries: List[Dict], days: int = 365) -> List[Dict]:
    """
    Build a contribution-style graph from commit timestamps.
    """
    return _build_activity_graph(entries, days)


def get_activity_graph(log_fp: str, days: int = 365) -> List[Dict]:
    log = _load_json(log_fp, [])
    return _build_activity_graph(log, days)


def get_recent_events(log_fp: str, limit: int = 20) -> List[Dict]:
    log = _load_json(log_fp, [])
    try:
        log.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    except Exception as err:
        logger.warning(f"Error sorting log entries: {err}", exc_info=True)
    return log[:limit]
