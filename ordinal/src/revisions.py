import json
import hashlib
import uuid
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.base_utils import content_dir, ensure_directory, setup_logger
from src.markdown_parser import parse_frontmatter

logger = setup_logger("revisions", "logs/revisions.log")

CONTENT_PATH = Path(content_dir)
DB_DIR = CONTENT_PATH / ".revisions"
DB_PATH = DB_DIR / "revisions.db"


def get_connection() -> sqlite3.Connection:
    ensure_directory(str(DB_DIR))
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    try:
        with get_connection() as conn:
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
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_commits_slug ON commits(slug);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_commits_timestamp ON commits(timestamp);"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS articles (
                    slug TEXT PRIMARY KEY,
                    title TEXT,
                    created TEXT,
                    last_hash TEXT,
                    last_timestamp TEXT,
                    guid TEXT
                );
                """
            )
            _ensure_schema(cur)
        logger.info("Initialized revisions database.")
    except Exception:
        logger.exception("Error initializing revisions database")


def _ensure_schema(cur: sqlite3.Cursor) -> None:
    """
    Apply lightweight schema migrations when new columns are introduced.
    """
    cur.execute("PRAGMA table_info(commits);")
    cols = {row["name"] for row in cur.fetchall()}
    if "word_delta" not in cols:
        cur.execute("ALTER TABLE commits ADD COLUMN word_delta INTEGER;")

    cur.execute("PRAGMA table_info(articles);")
    article_cols = {row["name"] for row in cur.fetchall()}
    if "guid" not in article_cols:
        cur.execute("ALTER TABLE articles ADD COLUMN guid TEXT;")


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None

    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        pass
    try:
        return datetime.strptime(str(value), "%Y-%m-%d")
    except Exception:
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _file_created(path: Path) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except Exception:
        logger.exception("Error reading file times for %s", path)
        return datetime.utcnow()


def compute_fingerprint(md_fp: str) -> str:
    try:
        parsed = parse_frontmatter(md_fp)
        frontmatter = parsed.get("frontmatter", {})
        content = parsed.get("content", "")
        created = str(frontmatter.get("created", ""))
        title = str(frontmatter.get("title", ""))
        normalized_body = "\n".join(
            line.strip() for line in content.splitlines() if line.strip()
        )
        raw = f"{created}|{title}|{normalized_body}"
        sha = hashlib.sha1(raw.encode("utf-8")).hexdigest()
        return sha[:7]
    except Exception:
        logger.exception("Error computing fingerprint for %s", md_fp)
        return "unknown"


def get_latest_commit(slug: str) -> Optional[sqlite3.Row]:
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM commits WHERE slug = ? ORDER BY timestamp DESC LIMIT 1",
                (slug,),
            )
            return cur.fetchone()
    except Exception:
        logger.exception("Error fetching latest commit for %s", slug)
        return None


def get_article_cache(slug: str) -> Optional[sqlite3.Row]:
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM articles WHERE slug = ?", (slug,))
            return cur.fetchone()
    except Exception:
        logger.exception("Error fetching article cache for %s", slug)
        return None


def get_entry_guid(slug: str) -> str:
    """
    Fetch or create a stable GUID for an entry.
    """
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT guid FROM articles WHERE slug = ?", (slug,))
            row = cur.fetchone()
            if row and row["guid"]:
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
            return guid
    except Exception:
        logger.exception("Error ensuring GUID for %s", slug)
        return uuid.uuid4().hex


def get_previous_commit(slug: str) -> Optional[sqlite3.Row]:
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM commits WHERE slug = ? ORDER BY timestamp DESC LIMIT 1 OFFSET 1",
                (slug,),
            )
            return cur.fetchone()
    except Exception:
        logger.exception("Error fetching previous commit for %s", slug)
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

        now_ts = timestamp_override or datetime.utcnow().isoformat()
        meta = {
            "division": frontmatter.get("division", []),
            "domain": frontmatter.get("domain", ""),
            "template": frontmatter.get("template", ""),
        }
        with get_connection() as conn:
            cur = conn.cursor()
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
        logger.info(f"Inserted commit for {slug} hash {hash_val}")
    except Exception:
        logger.exception("Error inserting commit for %s", slug)


def get_changelog(slug: str) -> List[Dict[str, Any]]:
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT hash, timestamp, summary, parent_hash, title, created, word_count, word_delta, worked_hours, meta_json
                FROM commits WHERE slug = ? ORDER BY timestamp DESC
                """,
                (slug,),
            )
            rows = cur.fetchall()
        results = []
        for r in rows:
            results.append(
                {
                    "hash": r["hash"],
                    "fingerprint": r["hash"],  # compatibility alias
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
    except Exception:
        logger.exception("Error loading changelog for %s", slug)
        return []


def get_global_changelog(limit: Optional[int] = 200) -> List[Dict[str, Any]]:
    try:
        with get_connection() as conn:
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
        return [
            {
                "slug": r["slug"],
                "hash": r["hash"],
                "fingerprint": r["hash"],  # compatibility alias
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
    except Exception:
        logger.exception("Error loading global changelog")
        return []


def get_entry_fingerprint(slug: str) -> Optional[str]:
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT last_hash FROM articles WHERE slug = ?", (slug,))
            row = cur.fetchone()
        if row:
            return row["last_hash"]
        return None
    except Exception:
        logger.exception("Error fetching fingerprint for %s", slug)
        return None


def list_articles() -> List[Dict[str, Any]]:
    """
    Return cached articles with their latest known hash and timestamps.
    """
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT slug, title, created, last_hash, last_timestamp, guid
                FROM articles
                ORDER BY slug
                """
            )
            rows = cur.fetchall()
        return [
            {
                # TODO: remove compatibility aliases
                "slug": r["slug"],
                "title": r["title"],
                "created": r["created"],
                "last_hash": r["last_hash"],
                "hash": r["last_hash"],  # alias
                "fingerprint": r["last_hash"],  # alias
                "last_timestamp": r["last_timestamp"],
                "timestamp": r["last_timestamp"],  # alias
                "guid": r["guid"],
            }
            for r in rows
        ]
    except Exception:
        logger.exception("Error listing articles")
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
        for md_path in CONTENT_PATH.rglob("*.md"):
            try:
                slug = md_path.relative_to(CONTENT_PATH).with_suffix("").as_posix()

                parsed = parse_frontmatter(str(md_path))
                fm = parsed.get("frontmatter", {}) or {}
                content = parsed.get("content", "") or ""
                hash_val = compute_fingerprint(str(md_path))
                latest = get_latest_commit(slug)

                created_dt = _parse_datetime(fm.get("created")) or _file_created(
                    md_path
                )

                ts = created_dt.isoformat()
                word_count = len([w for w in content.split() if w.strip()])
                worked_hours = _safe_float(fm.get("worked", 0), default=0.0)
                guid_val = get_entry_guid(slug)

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
            except Exception as err_file:
                skipped += 1
                logger.error(
                    f"Error seeding file {md_path}: {err_file}", exc_info=True
                )

        logger.info(f"Seed complete. Seeded: {seeded}, skipped: {skipped}")
    except Exception as err:
        logger.error(f"Error seeding database: {err}", exc_info=True)
