import os
import heapq
import re
from datetime import datetime
from functools import lru_cache
from itertools import chain
from pathlib import Path
from typing import Iterable

from src.base_utils import content_dir, setup_logger
from src.markdown_parser import parse_frontmatter
from src.revisions import get_entry_fingerprint

MEDIA_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".bmp")
MEDIA_VIDEO_EXTS = (".mp4",)
MEDIA_EXTS = set(MEDIA_IMAGE_EXTS + MEDIA_VIDEO_EXTS)
FIRST_MEDIA_RE = re.compile(r"!\[[^\]]*?\]\(([^)]+)\)")
CONTENT_PATH = Path(content_dir)
IMAGE_ROOT = CONTENT_PATH / "images"
VIDEO_ROOT = CONTENT_PATH / "videos"

logger = setup_logger(
    "media_helpers",
    os.path.join(os.path.dirname(__file__), "..", "logs", "media_helpers.log"),
)


def parse_first_media(content: str) -> str | None:
    if not content:
        return None

    match = FIRST_MEDIA_RE.search(content)
    return match.group(1) if match else None


def derive_header_image(frontmatter: dict, content: str) -> str | None:
    header = frontmatter.get("header_image")
    if header:
        return header

    media = parse_first_media(content or "")
    if not media:
        return None
    if media.startswith(("http://", "https://")):
        return media

    media_kind = _media_kind_from_suffix(Path(media).suffix)
    if not media_kind:
        return None
    base_dir = "videos" if media_kind == "video" else "images"
    return f"{base_dir}/{Path(media).name}"


def load_markdown_inventory(refresh: bool = False) -> list[dict]:
    if refresh:
        _cached_inventory.cache_clear()
    return _cached_inventory()


def get_recent_media(max_items: int = 12) -> list[dict]:
    try:
        inventory = load_markdown_inventory()
        media_index = _build_media_index(inventory)

        candidates = []
        for item in chain(
            _iter_media_files(IMAGE_ROOT, MEDIA_IMAGE_EXTS, "image"),
            _iter_media_files(VIDEO_ROOT, MEDIA_VIDEO_EXTS, "video"),
        ):
            articles = media_index.get(item["basename"], [])
            if not articles:
                continue
            item["articles"] = articles
            candidates.append(item)

        if not candidates:
            return []

        return heapq.nlargest(max_items, candidates, key=lambda x: x["timestamp"])
    except Exception:
        logger.exception("Error getting recent media")
        return []


def _media_kind_from_suffix(suffix: str) -> str | None:
    suffix = suffix.lower()
    if suffix in MEDIA_VIDEO_EXTS:
        return "video"
    if suffix in MEDIA_IMAGE_EXTS:
        return "image"
    return None


def _iter_media_files(
    root: Path, valid_exts: tuple[str, ...], kind: str
) -> Iterable[dict]:
    if not root.exists():
        return

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in valid_exts:
            continue
        try:
            ts = path.stat().st_mtime
        except OSError:
            logger.exception("Error stat-ing media file %s", path)
            continue

        dt = datetime.fromtimestamp(ts)
        rel = path.relative_to(root).as_posix()
        yield {
            "url": f"{'videos' if kind == 'video' else 'images'}/{rel}",
            "media_type": kind,
            "type": kind,
            "title": path.stem.replace("-", " ").title(),
            "timestamp": ts,
            "stamp": dt.strftime("%Y%m%d%H%M%S"),
            "basename": path.name,
        }


def _build_media_index(inventory: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for md in inventory:
        basenames = _extract_media_basenames(
            md.get("frontmatter", {}), md.get("content", "")
        )
        if not basenames:
            continue
        entry = {
            "title": md["title"],
            "url": md["url"],
            "slug": md["slug"],
            "hash": get_entry_fingerprint(md["slug"]),
        }
        for base in basenames:
            index.setdefault(base, []).append(entry)
    return index


def _extract_media_basenames(frontmatter: dict, content: str) -> set[str]:
    basenames = {Path(match).name for match in FIRST_MEDIA_RE.findall(content or "")}
    _collect_frontmatter_media(frontmatter, basenames)
    return basenames


def _collect_frontmatter_media(value, basenames: set[str]) -> None:
    if isinstance(value, dict):
        for sub_val in value.values():
            _collect_frontmatter_media(sub_val, basenames)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_frontmatter_media(item, basenames)
    elif isinstance(value, str):
        path = Path(value)
        if path.suffix.lower() in MEDIA_EXTS:
            basenames.add(path.name)


@lru_cache(maxsize=1)
def _cached_inventory() -> list[dict]:
    items = []
    for path in CONTENT_PATH.rglob("*.md"):
        try:
            parsed = parse_frontmatter(str(path))
        except Exception:
            logger.exception("Error parsing markdown %s", path)
            continue

        frontmatter = parsed.get("frontmatter", {}) or {}
        content = parsed.get("content", "") or ""
        rel = path.relative_to(CONTENT_PATH)
        url_path = rel.with_suffix(".html").as_posix()
        title = frontmatter.get("title") or path.stem.replace("-", " ").title()

        items.append(
            {
                "url": f"/{url_path}",
                "slug": rel.with_suffix("").as_posix(),
                "title": title,
                "frontmatter": frontmatter,
                "content": content,
            }
        )
    return items
