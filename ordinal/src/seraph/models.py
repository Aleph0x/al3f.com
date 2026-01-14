from typing import Any


class CommitRecord:
    id: int
    hash: str
    slug: str
    timestamp: str
    parent_hash: str | None
    title: str | None
    created: str | None
    word_count: int | None
    word_delta: int | None
    worked_hours: float | None
    meta: dict[str, Any]


class ArticleCacheRecord:
    pass


class WorkStats:
    pass
