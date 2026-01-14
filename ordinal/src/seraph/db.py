from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("seraph.db")


def connect(db_path: str) -> sqlite3.Connection:
    logger.info("Connecting to database as %s", db_path)
    try:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error("Failed to connect to database: %s", e)
        raise
