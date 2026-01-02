import os
import sqlite3
import json
import hashlib
import uuid
from datetime import datetime, timedelta
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
                word_delta INTEGER,
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
        # Schema migrations for added columns
        cur.execute("PRAGMA table_info(commits);")
        cols = [row["name"] for row in cur.fetchall()]
        if "word_delta" not in cols:
            cur.execute("ALTER TABLE commits ADD COLUMN word_delta INTEGER;")
            conn.commit()
        cur.execute("PRAGMA table_info(articles);")
        article_cols = [row["name"] for row in cur.fetchall()]
        if "guid" not in article_cols:
            cur.execute("ALTER TABLE articles ADD COLUMN guid TEXT;")
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


def get_entry_guid(slug: str) -> str:
    """
    Fetch or create a stable GUID for an entry.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT guid FROM articles WHERE slug = ?", (slug,))
        row = cur.fetchone()
        if row and row["guid"]:
            conn.close()
            return row["guid"]

        guid = uuid.uuid4().hex
        cur.execute(
            """
            INSERT INTO articles (slug, guid)
            VALUES (?, ?)
            ON CONFLICT(slug) DO UPDATE SET guid=excluded.guid
            """,
            (slug, guid),
        )
        conn.commit()
        conn.close()
        return guid
    except Exception as err:
        logger.error(f"Error ensuring GUID for {slug}: {err}")
        return uuid.uuid4().hex


def get_previous_commit(slug: str) -> Optional[sqlite3.Row]:
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM commits WHERE slug = ? ORDER BY timestamp DESC LIMIT 1 OFFSET 1",
            (slug,),
        )
        row = cur.fetchone()
        conn.close()
        return row
    except Exception as err:
        logger.error(f"Error fetching previous commit for {slug}: {err}")
        return None


def insert_commit(
    slug: str,
    hash_val: str,
    summary: str,
    frontmatter: dict,
    word_count: int,
    worked_hours: float,
    parent_hash: Optional[str] = None,
    timestamp_override: Optional[str] = None,
    guid: Optional[str] = None,
    update_article: bool = True,
) -> None:
    try:
        prev = get_latest_commit(slug)
        prev_wc = prev["word_count"] if prev and prev["word_count"] is not None else 0
        word_delta = word_count - prev_wc
        guid_val = guid or get_entry_guid(slug)

        conn = get_connection()
        cur = conn.cursor()
        now_ts = timestamp_override or datetime.utcnow().isoformat()
        meta = {
            "division": frontmatter.get("division", []),
            "domain": frontmatter.get("domain", ""),
            "template": frontmatter.get("template", ""),
        }
        cur.execute(
            """
            INSERT OR IGNORE INTO commits
            (hash, slug, timestamp, summary, parent_hash, title, created, word_count, word_delta, worked_hours, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                word_delta,
                worked_hours,
                json.dumps(meta),
            ),
        )
        if update_article:
            cur.execute(
                """
                INSERT INTO articles (slug, title, created, last_hash, last_timestamp, guid)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    title=excluded.title,
                    created=excluded.created,
                    last_hash=excluded.last_hash,
                    last_timestamp=excluded.last_timestamp,
                    guid=COALESCE(articles.guid, excluded.guid)
                """,
                (
                    slug,
                    frontmatter.get("title"),
                    str(frontmatter.get("created", "")),
                    hash_val,
                    now_ts,
                    guid_val,
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
            SELECT hash, timestamp, summary, parent_hash, title, created, word_count, word_delta, worked_hours, meta_json
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
                    "word_delta": r["word_delta"],
                    "worked_hours": r["worked_hours"],
                    "meta": json.loads(r["meta_json"]) if r["meta_json"] else {},
                }
            )
        return results
    except Exception as err:
        logger.error(f"Error loading changelog for {slug}: {err}")
        return []


def get_global_changelog(limit: Optional[int] = 200) -> List[Dict[str, Any]]:
    try:
        conn = get_connection()
        cur = conn.cursor()
        if limit is None:
            cur.execute(
                """
                SELECT slug, hash, timestamp, summary, title, word_count, word_delta, worked_hours, meta_json
                FROM commits ORDER BY timestamp DESC
                """
            )
        else:
            cur.execute(
                """
                SELECT slug, hash, timestamp, summary, title, word_count, word_delta, worked_hours, meta_json
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
                "word_delta": r["word_delta"],
                "worked_hours": r["worked_hours"],
                "meta": json.loads(r["meta_json"]) if r["meta_json"] else {},
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
            SELECT slug, title, created, last_hash, last_timestamp, guid
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
                "guid": r["guid"],
            }
            for r in rows
        ]
    except Exception as err:
        logger.error(f"Error listing articles: {err}")
        return []


def seed_database() -> None:
    """
    Seed the revisions database with initial commits derived from markdown frontmatter.
    Uses the frontmatter `created` date as the commit timestamp for every markdown entry.
    """
    try:
        init_db()
        seeded = 0
        skipped = 0
        for root, _, files in os.walk(content_dir):
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                md_fp = os.path.join(root, fname)
                slug = os.path.relpath(md_fp, content_dir).replace(os.sep, "/").replace(".md", "")

                parsed = parse_frontmatter(md_fp)
                fm = parsed.get("frontmatter", {}) or {}
                content = parsed.get("content", "") or ""
                hash_val = compute_fingerprint(md_fp)
                latest = get_latest_commit(slug)

                created_raw = fm.get("created")
                created_dt: Optional[datetime] = None
                if created_raw:
                    try:
                        created_dt = datetime.fromisoformat(str(created_raw))
                    except Exception:
                        try:
                            created_dt = datetime.strptime(str(created_raw), "%Y-%m-%d")
                        except Exception:
                            created_dt = None
                if created_dt is None:
                    try:
                        stat = os.stat(md_fp)
                        created_dt = datetime.fromtimestamp(stat.st_mtime)
                    except Exception:
                        created_dt = datetime.utcnow()

                ts = created_dt.isoformat()
                word_count = len([w for w in content.split() if w.strip()])
                worked_val = fm.get("worked", 0)
                try:
                    worked_hours = float(worked_val)
                except Exception:
                    worked_hours = 0.0
                guid_val = get_entry_guid(slug)

                # If commits already exist, avoid overwriting article cache and ensure unique hash
                seed_hash = hash_val
                update_article_cache = True
                if latest:
                    seed_hash = f"{hash_val}-seed"
                    update_article_cache = False

                insert_commit(
                    slug=slug,
                    hash_val=seed_hash,
                    summary="initial seed",
                    frontmatter=fm,
                    word_count=word_count,
                    worked_hours=worked_hours,
                    parent_hash=None,
                    timestamp_override=ts,
                    guid=guid_val,
                    update_article=update_article_cache,
                )
                seeded += 1

        logger.info(f"Seed complete. Seeded: {seeded}, skipped: {skipped}")
    except Exception as err:
        logger.error(f"Error seeding database: {err}")
