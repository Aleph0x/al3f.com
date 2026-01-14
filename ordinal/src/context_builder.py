import json
import os
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, TypedDict, cast


from src.base_utils import content_dir
from src.revisions import (
    get_entry_guid,
    get_entry_fingerprint,
    get_changelog,
    get_global_changelog,
)
from src.seraph.api import get_latest_commit, get_previous_commit
from src.seraph.models import CommitRecord

from src.file_manager import get_categories
from src.media_helpers import derive_header_image, get_recent_media
from src.activity_helpers import get_commit_activity
from src.markdown_parser import (
    parse_articles,
    parse_footnotes,
    parse_related,
    parse_frontmatter,
)
from src.taxonomy import get_recent_articles, get_articles_list

from src.base_utils import setup_logger


logger = setup_logger("context_builder", "logs/context_builder.log")
CONTENT_PATH = Path(content_dir)
SERAPH_DB_PATH = str(CONTENT_PATH / ".revisions" / "revisions.db")


class PageMeta(TypedDict):
    created_val: str
    domain_val: str
    division_val: str
    last_modified: str
    worked: str
    worked_delta: str
    hash: str


class TocEntry(TypedDict):
    text: str
    anchor: str
    level: int


class ArticleEntry(TypedDict):
    header: str
    sections: list[str]


class BacklinkEntry(TypedDict):
    source: str
    url: str


class RelatedEntry(TypedDict):
    title: str
    url: str


class ConnectionEntry(TypedDict):
    slug: str
    title: str
    last_modified: str | None


class EntryContext(TypedDict, total=False):
    title: str
    description: str
    entry_fingerprint: str
    entry_revisions_url: str
    entry_drift: str
    entry_worked: float | None
    entry_worked_delta: float | None
    entry_word_count: int | None
    entry_guid: str
    revision_spark: list[dict[str, float]]
    outgoing_links: list[ConnectionEntry]
    outgoing_links_more: int
    backlinks_links: list[ConnectionEntry]
    backlinks_more: int
    page_meta: PageMeta
    content: str
    articles: list[ArticleEntry]
    footnotes: dict[str, str]
    toc: list[TocEntry]
    backlinks: list[BacklinkEntry] | list[Any]
    external_links: list[Any]
    related_articles: list[RelatedEntry]
    hero_image: str | None
    hero_video: str | None
    poster: str | None
    gallery: list
    tags: list
    series: Any
    location: Any
    reading_time: Any
    frontmatter: dict
    page_changelog: list[Any]
    recent_articles: list[Any]
    categorized_articles: dict[str, Any]
    entries_total: int
    domain_max: int
    categories: list[str]
    activity_graph: list[Any]
    changelog: list[Any]
    recent_media: list[Any]
    about_copy: str
    template_name: str
    slug: str


def normalize_tags(tags):
    if isinstance(tags, str):
        return [tags]
    return tags if isinstance(tags, list) else []


def compute_worked(
    latest_commit: CommitRecord | None,
    prev_commit: CommitRecord | None,
) -> tuple[float, float]:
    def _to_float(val):
        return _safe_float(val, default=0.0)

    try:
        latest_work = (
            _to_float(latest_commit.worked_hours)
            if latest_commit and latest_commit.worked_hours is not None
            else 0.0
        )
    except Exception as err:
        logger.error(
            f"Failed to parse worked_hours from latest commit: {err}", exc_info=True
        )
        latest_work = 0.0

    try:
        prev_work = (
            _to_float(prev_commit.worked_hours)
            if prev_commit and prev_commit.worked_hours is not None
            else 0.0
        )
    except Exception as err:
        logger.error(
            f"Failed to parse worked_hours from previous commit: {err}", exc_info=True
        )
        prev_work = 0.0

    worked_delta = latest_work - prev_work
    return latest_work, worked_delta


def build_revision_spark(slug: str) -> list[dict[str, float]]:
    commits = get_changelog(slug)
    day_counts: dict[date, int] = {}
    for entry in commits:
        ts = _parse_timestamp(entry.get("timestamp"))
        if ts is None:
            continue
        day = ts.date()
        day_counts[day] = day_counts.get(day, 0) + 1

    if not day_counts:
        return []

    days_sorted = sorted(day_counts.keys())
    total_days = len(days_sorted)
    max_count = max(day_counts.values()) if day_counts else 0

    output: list[dict[str, float]] = []
    for day in days_sorted:
        count = day_counts.get(day, 0)
        h_raw = (count / max_count) if max_count else 0.0
        h = min(1.0, max(0.35, h_raw))
        output.append({"h": h})

    return output


CONNECTIONS_OUTGOING_CAP = 25
CONNECTIONS_BACKLINKS_CAP = 25


@lru_cache(maxsize=1)
def _load_entry_index() -> dict[str, dict[str, str | None]]:
    entries: dict[str, dict[str, str | None]] = {}
    for md_path in CONTENT_PATH.rglob("*.md"):
        slug = md_path.relative_to(CONTENT_PATH).with_suffix("").as_posix()
        parsed = parse_frontmatter(str(md_path))
        frontmatter = parsed.get("frontmatter", {}) or {}
        title = frontmatter.get("title") or slug
        last_modified = frontmatter.get("last_modified")
        entries[slug] = {
            "title": str(title),
            "last_modified": str(last_modified) if last_modified else None,
        }
    return entries


def _build_connection_entries(
    slugs: list[str],
    entry_index: dict[str, dict[str, str | None]],
) -> list[ConnectionEntry]:
    entries: list[ConnectionEntry] = []
    for slug in slugs:
        meta = entry_index.get(slug, {})
        title = meta.get("title") or slug
        last_modified = meta.get("last_modified")
        entries.append(
            {
                "slug": slug,
                "title": str(title),
                "last_modified": str(last_modified) if last_modified else None,
            }
        )
    entries.sort(key=lambda e: e["title"].lower())
    return entries


def build_entry_context(
    md_fp: str,
    default_template: str,
    backlinks: dict,
    outgoing_links: dict,
    parsed_data: dict,
) -> EntryContext:
    logger.info(f"Building context for {md_fp}")
    try:
        frontmatter, raw_content = _load_markdown(Path(md_fp), parsed_data)
        frontmatter["last_modified"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        slug = _slug_from_path(md_fp)
        entry_fingerprint = get_entry_fingerprint(slug) or ""
        entry_guid = get_entry_guid(slug)
        latest_commit = get_latest_commit(SERAPH_DB_PATH, slug)
        prev_commit = get_previous_commit(SERAPH_DB_PATH, slug)

        entry_drift = "—"
        latest_cache_ts = latest_commit.timestamp if latest_commit else None
        if latest_cache_ts:
            try:
                last_dt = datetime.fromisoformat(str(latest_cache_ts))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                now_dt = datetime.now(timezone.utc)
                entry_drift = f"{max((now_dt - last_dt).days, 0)}d"
            except Exception as err:
                logger.error(f"Failed computing drift for {slug}: {err}", exc_info=True)
                entry_drift = "NULL"
        else:
            entry_drift = "NULL"

        footnotes_content, footnotes = parse_footnotes(raw_content)
        articles = parse_articles(footnotes_content, slug, backlinks, outgoing_links)
        related_raw = parse_related(frontmatter)
        related = cast(list[RelatedEntry], related_raw)
        template_name = frontmatter.get("template", default_template)
        gallery = frontmatter.get("gallery", [])
        if not isinstance(gallery, list):
            gallery = []

        tags = normalize_tags(frontmatter.get("tags", []))
        header_image = derive_header_image(frontmatter, raw_content)
        worked_val, worked_delta = compute_worked(latest_commit, prev_commit)

        meta = latest_commit.meta if latest_commit else {}
        word_count = None
        if latest_commit and latest_commit.word_count is not None:
            try:
                word_count = int(latest_commit.word_count)
            except Exception as err:
                logger.error(
                    f"Failed parsing word_count for {slug}: {err}", exc_info=True
                )
        domain_val = frontmatter.get("domain", meta.get("domain", "N/A"))
        division_val = frontmatter.get("division", meta.get("division", []))
        if isinstance(division_val, str):
            division_val = [division_val]
        created_val = str(
            _first_nonempty(
                frontmatter.get("created"),
                latest_commit.created if latest_commit else None,
                "N/A",
            )
        )
        domain_val = "N/A" if domain_val is None else domain_val

        entry_index = _load_entry_index()
        outgoing_slugs = sorted(set(outgoing_links.get(slug, [])))
        backlink_slugs = sorted(set(backlinks.get(slug, [])))
        outgoing_entries = _build_connection_entries(outgoing_slugs, entry_index)
        backlink_entries = _build_connection_entries(backlink_slugs, entry_index)
        outgoing_more = max(0, len(outgoing_entries) - CONNECTIONS_OUTGOING_CAP)
        backlink_more = max(0, len(backlink_entries) - CONNECTIONS_BACKLINKS_CAP)
        context: EntryContext = {
            "title": frontmatter.get("title", "Untitled"),
            "description": frontmatter.get("description", ""),
            "entry_fingerprint": entry_fingerprint,
            "entry_revisions_url": "/revisions/index.html",
            "entry_drift": entry_drift,
            "entry_worked": worked_val if worked_val is not None else None,
            "entry_worked_delta": worked_delta if worked_delta is not None else None,
            "entry_word_count": word_count,
            "entry_guid": entry_guid,
            "revision_spark": build_revision_spark(slug),
            "outgoing_links": outgoing_entries[:CONNECTIONS_OUTGOING_CAP],
            "outgoing_links_more": outgoing_more,
            "backlinks_links": backlink_entries[:CONNECTIONS_BACKLINKS_CAP],
            "backlinks_more": backlink_more,
            "page_meta": {
                "created_val": created_val or "N/A",
                "domain_val": domain_val or "N/A",
                "division_val": ", ".join(division_val) if division_val else "N/A",
                "last_modified": frontmatter.get("last_modified", "N/A").split(" ")[0],
                "worked": f"{worked_val}h",
                "worked_delta": f"{worked_delta:+.1f}h",
                "hash": entry_fingerprint or "N/A",
            },
            "content": footnotes_content,
            "articles": articles.get("articles", []),
            "footnotes": footnotes,
            "toc": articles["toc"],
            "backlinks": backlinks.get(slug, []),
            "external_links": parsed_data.get("external_links", []),
            "related_articles": related,
            "hero_image": header_image,
            "hero_video": frontmatter.get("hero_video"),
            "poster": frontmatter.get("poster"),
            "gallery": gallery,
            "tags": tags,
            "series": frontmatter.get("series"),
            "location": frontmatter.get("location"),
            "reading_time": frontmatter.get("reading_time"),
            "frontmatter": frontmatter,
            "page_changelog": get_changelog(slug),
            "template_name": template_name,
            "slug": slug,
        }
        return context
    except Exception as err:
        logger.error(f"Error building context for {md_fp}: {err}", exc_info=True)
        return cast(
            EntryContext,
            {
                "title": "Error",
                "description": "",
                "content": "",
                "articles": [],
                "footnotes": [],
                "toc": [],
                "backlinks": [],
                "external_links": [],
                "related_articles": [],
                "gallery": [],
                "tags": [],
                "frontmatter": {},
                "page_changelog": [],
                "template_name": default_template,
                "slug": Path(md_fp).name,
            },
        )


def attach_index_context(context: EntryContext | Dict[str, Any]) -> None:
    try:
        context["recent_articles"] = get_recent_articles(9)
        context["categorized_articles"] = get_articles_list()
        context["entries_total"] = sum(
            len(v) for v in context["categorized_articles"].values()
        )
        context["domain_max"] = max(
            (len(v) for v in context["categorized_articles"].values()), default=0
        )
        context["categories"] = get_categories()
        context["about_copy"] = render_about_copy()
        global_changes = get_global_changelog(limit=500)
        context["activity_graph"] = get_commit_activity(global_changes, days=365)
        context["changelog"] = global_changes[:30]
        context["recent_media"] = get_recent_media()
    except Exception as err:
        logger.error(f"Error attaching index context: {err}", exc_info=True)


def render_about_copy() -> str:
    about_fp = CONTENT_PATH / "about.md"
    if not about_fp.exists():
        return ""

    parsed = parse_frontmatter(str(about_fp))
    raw_content = parsed.get("content", "")
    if not raw_content.strip():
        return ""

    md_content = "## About\n" + raw_content
    parsed_articles = parse_articles(md_content, about_fp.name, {})
    sections: list[str] = []
    for article in parsed_articles.get("articles", []):
        sections.extend(article.get("sections", []))

    if not sections:
        return ""

    output: list[str] = []
    for section in sections:
        text = section.strip()
        if not text:
            continue
        if text.startswith(("<ul", "<ol", "<pre", "<blockquote", "<table", "<h")):
            output.append(text)
        else:
            output.append(f"<p>{text}</p>")

    return "\n".join(output)


def attach_section_context(context: EntryContext | Dict[str, Any]) -> None:
    try:
        context["categorized_articles"] = get_articles_list()
        context["entries_total"] = sum(
            len(v) for v in context["categorized_articles"].values()
        )
        context["domain_max"] = max(
            (len(v) for v in context["categorized_articles"].values()), default=0
        )
    except Exception as err:
        logger.error(f"Error attaching section context: {err}", exc_info=True)


def _slug_from_path(md_fp: str) -> str:
    return Path(md_fp).relative_to(CONTENT_PATH).with_suffix("").as_posix()


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if isinstance(val, str):
            val = val.strip().lower().rstrip("h")
        return float(val)
    except Exception:
        return default


def _first_nonempty(*values: Any) -> Any:
    for val in values:
        if val not in (None, "", "N/A"):
            return val
    return None


def _load_markdown(md_path: Path, parsed: dict | None) -> tuple[dict, str]:
    if parsed:
        return parsed.get("frontmatter", {}) or {}, parsed.get("content", "") or ""
    parsed_data = parse_frontmatter(str(md_path))
    return (
        parsed_data.get("frontmatter", {}) or {},
        parsed_data.get("content", "") or "",
    )
