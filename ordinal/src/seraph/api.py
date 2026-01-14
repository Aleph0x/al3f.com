from __future__ import annotations

from typing import Any

from .db import connect
from .queries import fetch_latest_commit, fetch_previous_commit
from .convert import row_to_commit
from .models import ArticleCacheRecord, CommitRecord, WorkStats


def get_latest_commit(db_path: str, slug: str) -> CommitRecord | None:
    with connect(db_path) as conn:
        row = fetch_latest_commit(conn, slug)
        return row_to_commit(row) if row else None


def init_db(db_path: str) -> None:
    raise NotImplementedError


def get_article_cache(db_path: str, slug: str) -> ArticleCacheRecord | None:
    raise NotImplementedError


def list_articles(db_path: str) -> list[ArticleCacheRecord]:
    return []


def get_previous_commit(db_path: str, slug: str) -> CommitRecord | None:
    with connect(db_path) as conn:
        row = fetch_previous_commit(conn, slug)
        return row_to_commit(row) if row else None


def get_changelog(
    db_path: str, slug: str, limit: int | None = 20
) -> list[CommitRecord]:
    return []


def get_global_changelog(db_path: str, limit: int | None = 200) -> list[CommitRecord]:
    return []


def get_worked_stats(db_path: str, slug: str) -> WorkStats | None:
    raise NotImplementedError


def get_drift_days(db_path: str, slug: str) -> int | None:
    raise NotImplementedError


def get_parsed_meta(db_path: str, slug: str) -> dict[str, Any] | None:
    raise NotImplementedError


def record_commit(
    db_path: str,
    *,
    slug: str,
    fingerprint: str,
    frontmatter: dict[str, Any],
    raw_content: str,
    parent_hash: str | None,
    commit_context: dict[str, Any] | None = None,
) -> CommitRecord | None:
    raise NotImplementedError
