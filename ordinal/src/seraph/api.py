from __future__ import annotations
from dataclasses import dataclass

from typing import Any

from .models import ArticleCacheRecord, CommitRecord, WorkStats


@dataclass
class Seraph:
    db_path: str

    def init_db(self) -> None:
        """Ensure the revisions database exists and has the correct schema."""
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def get_article_cache(self, slug: str) -> ArticleCacheRecord | None:
        raise NotImplementedError

    def list_articles(self, slug: str) -> list[ArticleCacheRecord]:
        raise NotImplementedError

    def get_latest_commit(self, slug: str) -> CommitRecord | None:
        raise NotImplementedError

    def get_previous_commit(self, slug: str) -> CommitRecord | None:
        raise NotImplementedError

    def get_changelog(self, slug: str, limit: int | None = 20) -> list[CommitRecord]:
        raise NotImplementedError

    def get_global_changelog(self, limit: int | None = 200) -> list[CommitRecord]:
        raise NotImplementedError

    def get_worked_stats(self, slug: str) -> WorkStats | None:
        raise NotImplementedError

    def get_drift_days(self, slug: str) -> int | None:
        raise NotImplementedError

    def get_parsed_meta(self, slug: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def record_commit(
        self,
        slug: str,
        fingerprint: str,
        frontmatter: dict[str, Any],
        raw_content: str,
        parent_hash: str | None,
        commit_context: dict[str, Any] | None = None,
    ) -> CommitRecord | None:
        raise NotImplementedError
