from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class ArticleCacheRecord:
    # stub for now
    slug: str


@dataclass(frozen=True)
class WorkStats:
    worked_total: float
    worked_delta: float
