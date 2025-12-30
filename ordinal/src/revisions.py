import os
import sqlite3
import json
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from src.base_utils import content_dir, setup_logger, ensure_directory
from src.markdown_parser import parse_frontmatter

logger = setup_logger("revisions", "logs/revisions.log")

DB_DIR = os.path.join(content_dir, ".revisions")
DB_PATH = os.path.join(DB_DIR, "revisions.db")


def get_connection() -> sqlite3.Connection:
    ensure_directory(DB_DIR)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS commits (
                id INTEGER PRIMARY KEY,
                hash TEXT NOT NULL,
                slug TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                summary TEXT NOT NULL,
                parent_hash TEXT,
                title TEXT,
                created TEXT,
                word_count INTEGER,
                worked_hours REAL,
                meta_json TEXT,
                UNIQUE(slug, hash)
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_commits_slug ON commits(slug);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_commits_timestamp ON commits(timestamp);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                slug TEXT PRIMARY KEY,
                title TEXT,
                created TEXT,
                last_hash TEXT,
                last_timestamp TEXT
            );
            """
        )
        conn.commit()
        conn.close()
        logger.info("Initialized revisions database.")
    except Exception as err:
        logger.error(f"Error initializing revisions database: {err}")


def compute_fingerprint(md_fp: str) -> str:
    try:
        parsed = parse_frontmatter(md_fp)
        frontmatter = parsed.get("frontmatter", {})
        content = parsed.get("content", "")
        created = str(frontmatter.get("created", ""))
        title = str(frontmatter.get("title", ""))
        normalized_body = "\n".join([line.strip() for line in content.splitlines() if line.strip()])
        raw = f"{created}|{title}|{normalized_body}"
        sha = hashlib.sha1(raw.encode("utf-8")).hexdigest()
        return sha[:7]
    except Exception as err:
        logger.error(f"Error computing fingerprint for {md_fp}: {err}")
        return "unknown"


def get_latest_commit(slug: str) -> Optional[sqlite3.Row]:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM commits WHERE slug = ? ORDER BY timestamp DESC LIMIT 1",
            (slug,),
        )
        row = cur.fetchone()
        conn.close()
        return row
    except Exception as err:
        logger.error(f"Error fetching latest commit for {slug}: {err}")
        return None


def get_article_cache(slug: str) -> Optional[sqlite3.Row]:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM articles WHERE slug = ?", (slug,))
        row = cur.fetchone()
        conn.close()
        return row
    except Exception as err:
        logger.error(f"Error fetching article cache for {slug}: {err}")
        return None


def insert_commit(
    slug: str,
    hash_val: str,
    summary: str,
    frontmatter: dict,
    word_count: int,
    worked_hours: float,
    parent_hash: Optional[str] = None,
) -> None:
    try:
        conn = get_connection()
        cur = conn.cursor()
        now_ts = datetime.utcnow().isoformat()
        meta = {
            "division": frontmatter.get("division", []),
            "domain": frontmatter.get("domain", ""),
            "template": frontmatter.get("template", ""),
        }
        cur.execute(
            """
            INSERT OR IGNORE INTO commits
            (hash, slug, timestamp, summary, parent_hash, title, created, word_count, worked_hours, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hash_val,
                slug,
                now_ts,
                summary,
                parent_hash,
                frontmatter.get("title"),
                str(frontmatter.get("created", "")),
                word_count,
                worked_hours,
                json.dumps(meta),
            ),
        )
        cur.execute(
            """
            INSERT INTO articles (slug, title, created, last_hash, last_timestamp)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                title=excluded.title,
                created=excluded.created,
                last_hash=excluded.last_hash,
                last_timestamp=excluded.last_timestamp
            """,
            (
                slug,
                frontmatter.get("title"),
                str(frontmatter.get("created", "")),
                hash_val,
                now_ts,
            ),
        )
        conn.commit()
        conn.close()
        logger.info(f"Inserted commit for {slug} hash {hash_val}")
    except Exception as err:
        logger.error(f"Error inserting commit for {slug}: {err}")


def get_changelog(slug: str) -> List[Dict[str, Any]]:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT hash, timestamp, summary, parent_hash, title, created, word_count, worked_hours, meta_json
            FROM commits WHERE slug = ? ORDER BY timestamp DESC
            """,
            (slug,),
        )
        rows = cur.fetchall()
        conn.close()
        results = []
        for r in rows:
            results.append(
                {
                    "hash": r["hash"],
                    "timestamp": r["timestamp"],
                    "summary": r["summary"],
                    "parent_hash": r["parent_hash"],
                    "title": r["title"],
                    "created": r["created"],
                    "word_count": r["word_count"],
                    "worked_hours": r["worked_hours"],
                    "meta": json.loads(r["meta_json"]) if r["meta_json"] else {},
                }
            )
        return results
    except Exception as err:
        logger.error(f"Error loading changelog for {slug}: {err}")
        return []


def get_global_changelog(limit: int = 200) -> List[Dict[str, Any]]:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT slug, hash, timestamp, summary, title, word_count, worked_hours
            FROM commits ORDER BY timestamp DESC LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "slug": r["slug"],
                "hash": r["hash"],
                "timestamp": r["timestamp"],
                "summary": r["summary"],
                "title": r["title"],
                "word_count": r["word_count"],
                "worked_hours": r["worked_hours"],
            }
            for r in rows
        ]
    except Exception as err:
        logger.error(f"Error loading global changelog: {err}")
        return []


def get_entry_fingerprint(slug: str) -> Optional[str]:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT last_hash FROM articles WHERE slug = ?", (slug,))
        row = cur.fetchone()
        conn.close()
        if row:
            return row["last_hash"]
        return None
    except Exception as err:
        logger.error(f"Error fetching fingerprint for {slug}: {err}")
        return None


def list_articles() -> List[Dict[str, Any]]:
    """
    Return cached articles with their latest known hash and timestamps.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT slug, title, created, last_hash, last_timestamp
            FROM articles
            ORDER BY slug
            """
        )
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "slug": r["slug"],
                "title": r["title"],
                "created": r["created"],
                "last_hash": r["last_hash"],
                "last_timestamp": r["last_timestamp"],
            }
            for r in rows
        ]
    except Exception as err:
        logger.error(f"Error listing articles: {err}")
        return []
