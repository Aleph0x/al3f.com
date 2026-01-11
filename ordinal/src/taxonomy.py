import os
from collections import defaultdict
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any

from src.base_utils import content_dir, setup_logger
from src.markdown_parser import parse_frontmatter
from src.media_helpers import derive_header_image
from src.revisions import (
    compute_fingerprint,
    get_global_changelog,
    get_latest_commit,
    list_articles,
)


logger = setup_logger("taxonomy", os.path.join(os.path.dirname(__file__), "..", "logs", "taxonomy.log"))
ARTICLES_PATH = Path(content_dir) / "articles"


def get_articles_list() -> dict:
    categorized_articles = defaultdict(list)
    cache_lookup = {row["slug"]: row for row in list_articles()}

    if not ARTICLES_PATH.exists():
        return {}

    for md_path in ARTICLES_PATH.iterdir():
        if not md_path.is_file() or md_path.suffix != ".md":
            continue
        try:
            parsed_data = parse_frontmatter(str(md_path))
        except Exception as err:
            logger.error(f"Error parsing frontmatter for {md_path}: {err}", exc_info=True)
            continue

        frontmatter = parsed_data.get("frontmatter", {}) or {}
        content = parsed_data.get("content", "") or ""

        title = frontmatter.get("title", md_path.stem.replace("-", " ").title())
        description = frontmatter.get("description", "")
        slug = md_path.stem
        cache = cache_lookup.get(slug, {})
        domain = frontmatter.get("domain", "Miscellaneous")
        division_val = frontmatter.get("division", [])
        if isinstance(division_val, str):
            division_val = [division_val]
        division = division_val
        url = f"/articles/{md_path.with_suffix('.html').name}"
        header_image = derive_header_image(frontmatter, content)
        fingerprint = cache.get("last_hash")
        worked_hours = None
        word_count = None

        latest_commit = None
        try:
            latest_commit = get_latest_commit(slug)
            if latest_commit:
                worked_hours = _safe_float(latest_commit["worked_hours"], default=0.0)
                if latest_commit["word_count"] is not None:
                    word_count = int(latest_commit["word_count"])
        except Exception as err:
            logger.error(f"Error getting latest commit data for {slug}: {err}")

        last_modified = _first_nonempty(
            latest_commit["timestamp"] if latest_commit else None,
            cache.get("last_timestamp"),
            cache.get("created"),
            frontmatter.get("last_modified"),
            frontmatter.get("created"),
            "",
        )
        if isinstance(last_modified, (datetime, date)):
            last_modified = last_modified.isoformat()
        elif last_modified is None:
            last_modified = ""
        entry_drift = _compute_drift(last_modified)

        if worked_hours is None:
            worked_hours = _safe_float(frontmatter.get("worked"), default=None)
        if word_count is None:
            word_count = _safe_int(frontmatter.get("word_count"), default=None)

        if not fingerprint:
            try:
                fingerprint = compute_fingerprint(str(md_path))
            except Exception as err:
                logger.error(f"Error computing fallback fingerprint for {slug}: {err}", exc_info=True)

        is_recent_entry = _frontmatter_flag(frontmatter, "is_recent_entry", default=True)

        categorized_articles[domain].append(
            {
                "title": title,
                "description": description,
                "url": url,
                "last_modified": last_modified,
                "domain": domain,
                "division": division,
                "header_image": header_image,
                "slug": slug,
                "entry_fingerprint": fingerprint,
                "fingerprint": fingerprint,
                "entry_drift": entry_drift,
                "drift": cache.get("last_timestamp"),
                "worked_hours": worked_hours,
                "word_count": word_count,
                "is_recent_entry": is_recent_entry,
            }
        )

    return {
        domain: sorted(articles, key=lambda x: x["last_modified"] or "", reverse=True)
        for domain, articles in sorted(categorized_articles.items())
    }


def get_recent_articles(max_items: int = 12) -> list[dict]:
    articles = [art for articles in get_articles_list().values() for art in articles]
    articles = [art for art in articles if art.get("is_recent_entry", True)]
    articles.sort(key=lambda x: x.get("last_modified") or "", reverse=True)
    return articles[:max_items]


def _compute_drift(last_ts: Any) -> str | None:
    if not last_ts:
        return None
    try:
        last_dt = datetime.fromisoformat(str(last_ts))
        now_dt = datetime.utcnow() if last_dt.tzinfo is None else datetime.now(timezone.utc)
        return f"{max((now_dt - last_dt).days, 0)}d"
    except Exception as err:
        logger.error(f"Error computing drift for timestamp {last_ts}: {err}", exc_info=True)
        return None


def _first_nonempty(*values: Any) -> Any:
    for val in values:
        if val not in (None, "", "N/A"):
            return val
    return None


def _safe_float(val: Any, default: float | None = 0.0) -> float | None:
    try:
        if isinstance(val, str):
            val = val.strip().lower().rstrip("h")
        return float(val)
    except Exception:
        return default


def _safe_int(val: Any, default: int | None = 0) -> int | None:
    try:
        return int(val)
    except Exception:
        return default


def _frontmatter_flag(frontmatter: dict, key: str, default: bool = True) -> bool:
    if key in frontmatter:
        value = frontmatter.get(key)
    else:
        dashed_key = key.replace("_", "-")
        value = frontmatter.get(dashed_key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y", "on")
    return bool(value) if value is not None else default
