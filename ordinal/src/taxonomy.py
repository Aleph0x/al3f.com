import os
from collections import defaultdict
from datetime import datetime, timezone
from src.base_utils import content_dir, setup_logger
from src.markdown_parser import parse_frontmatter
from src.media_helpers import derive_header_image
from src.revisions import (
    list_articles,
    get_latest_commit,
    compute_fingerprint,
    get_global_changelog,
)


logger = setup_logger("taxonomy", os.path.join(os.path.dirname(__file__), "..", "logs", "taxonomy.log"))


def get_articles_list() -> dict:
    articles_dir = os.path.join(content_dir, "articles")
    categorized_articles = defaultdict(list)
    cache_lookup = {row["slug"]: row for row in list_articles()}

    if os.path.exists(articles_dir):
        for file in os.listdir(articles_dir):
            if file.endswith(".md"):
                md_fp = os.path.join(articles_dir, file)
                parsed_data = parse_frontmatter(md_fp)
                frontmatter = parsed_data.get("frontmatter", {})
                content = parsed_data.get("content", "")

                title = frontmatter.get(
                    "title", file.replace(".md", "").replace("-", " ").title()
                )
                slug = file.replace(".md", "")
                cache = cache_lookup.get(slug, {})
                last_modified = ""
                domain = frontmatter.get("domain", "Miscellaneous")
                division = frontmatter.get("division", [])
                url = f"/articles/{file.replace('.md', '.html')}"
                header_image = derive_header_image(frontmatter, content)
                fingerprint = cache.get("last_hash")
                worked_hours = None
                word_count = None
                entry_drift = None

                try:
                    latest_commit = get_latest_commit(slug)
                    if latest_commit:
                        last_modified = latest_commit["timestamp"]
                        if latest_commit["worked_hours"] is not None:
                            worked_hours = float(latest_commit["worked_hours"])
                        if latest_commit["word_count"] is not None:
                            word_count = int(latest_commit["word_count"])
                except Exception as err:
                    logger.error(f"Error getting latest commit data for {slug}: {err}")

                if not last_modified:
                    last_modified = (
                        cache.get("last_timestamp")
                        or cache.get("created")
                        or frontmatter.get("last_modified")
                        or frontmatter.get("created")
                        or ""
                    )

                last_ts = (
                    last_modified
                    or cache.get("last_timestamp")
                    or cache.get("created")
                    or frontmatter.get("last_modified")
                    or frontmatter.get("created")
                )
                if last_ts:
                    try:
                        last_dt = datetime.fromisoformat(str(last_ts))
                        if last_dt.tzinfo is None:
                            now_dt = datetime.utcnow()
                        else:
                            now_dt = datetime.now(timezone.utc)
                        entry_drift = f"{max((now_dt - last_dt).days, 0)}d"
                    except Exception as err:
                        logger.error(f"Error computing drift for {slug}: {err}", exc_info=True)

                if worked_hours is None:
                    try:
                        worked_hours = float(frontmatter.get("worked", 0))
                    except Exception:
                        worked_hours = None
                if word_count is None:
                    try:
                        word_count = int(frontmatter.get("word_count", 0))
                    except Exception:
                        word_count = None

                if not fingerprint:
                    try:
                        fingerprint = compute_fingerprint(md_fp)
                    except Exception as err:
                        logger.error(f"Error computing fallback fingerprint for {slug}: {err}", exc_info=True)

                categorized_articles[domain].append(
                    {
                        "title": title,
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
                    }
                )

    return {
        domain: sorted(articles, key=lambda x: x["last_modified"], reverse=True)
        for domain, articles in sorted(categorized_articles.items())
    }


def get_recent_articles(max_items: int = 12) -> list[dict]:
    articles = [art for articles in get_articles_list().values() for art in articles]
    articles.sort(key=lambda x: x.get("last_modified") or "", reverse=True)
    return articles[:max_items]
