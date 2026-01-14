from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger("seraph.queries")


def fetch_latest_commit(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    logger.info("Fetching latest commit for slug: %s", slug)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM commits WHERE slug = ? ORDER BY timestamp DESC LIMIT 1",
            (slug,),
        )
        return cur.fetchone()
    except Exception as e:
        logger.error("Failed to fetch latest commit for slug %s: %s", slug, e)
        return None
