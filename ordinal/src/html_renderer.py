import os
import shutil
import json
from datetime import datetime, timedelta
from src.base_utils import (
    content_dir,
    public_dir,
    setup_logger,
    ensure_directory,
    logs_dir,
)
from src.file_manager import (
    get_categories,
    generate_missing,
    merge_image_dir,
    merge_video_dir,
)
from src.markdown_parser import (
    parse_frontmatter,
    parse_related,
    parse_footnotes,
    parse_articles,
)
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
import subprocess
from collections import defaultdict
from src.revisions import (
    init_db,
    compute_fingerprint,
    insert_commit,
    get_entry_fingerprint,
    get_changelog,
    get_global_changelog,
    get_article_cache,
    get_latest_commit,
    get_previous_commit,
    get_entry_guid,
    list_articles,
)
from urllib.parse import quote


logger = setup_logger("html_renderer", "logs/html_renderer.log")

env = Environment(loader=FileSystemLoader("src/templates"))


def compile_scss():
    try:
        scss_path = "src/static/styles/main.scss"
        css_output = os.path.join(public_dir, "styles", "main.css")
        ensure_directory(os.path.dirname(css_output))
        subprocess.run(["sass", scss_path, css_output], check=True)
        logger.info(f"Compiled SCSS: {scss_path} -> {css_output}")
    except Exception as err:
        logger.error(f"Error compiling SCSS: {err}")


def copy_static_files():
    try:
        static_src = os.path.join("src", "static")
        static_dest = os.path.join(public_dir)
        ensure_directory(static_dest)

        # Remove any previously copied SCSS from public
        for root, _, files in os.walk(static_dest):
            for file in files:
                if file.endswith(".scss"):
                    try:
                        os.remove(os.path.join(root, file))
                        logger.info(
                            f"Removed stray SCSS from public: {os.path.join(root, file)}"
                        )
                    except Exception:
                        pass

        for root, _, files in os.walk(static_src):
            for file in files:
                if file.endswith(".scss"):
                    # Skip copying source SCSS only compiled CSS belongs in public
                    continue
                src_fp = os.path.join(root, file)
                rel_fp = os.path.relpath(src_fp, static_src)
                dest_fp = os.path.join(static_dest, rel_fp)
                ensure_directory(os.path.dirname(dest_fp))
                shutil.copy2(src_fp, dest_fp)
                logger.info(f"Copied static file: {src_fp} -> {dest_fp}")
    except Exception as err:
        logger.error(f"Error copying static files: {err}")


def render_template_context(template_name: str, context: dict) -> str:
    try:
        template = env.get_template(template_name)
        return template.render(**context)
    except TemplateNotFound as err:
        logger.error(f"Template not found: {err}")
    except Exception as err:
        logger.error(f"Error rendering template {template_name}: {err}")
    return ""


def get_articles_list() -> dict:
    articles_dir = os.path.join(content_dir, "articles")
    categorized_articles = defaultdict(list)

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
                last_modified = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                domain = frontmatter.get("domain", "Miscellaneous")
                division = frontmatter.get("division", [])
                url = f"/articles/{file.replace('.md', '.html')}"
                header_image = derive_header_image(frontmatter, content)
                slug = file.replace(".md", "")

                categorized_articles[domain].append(
                    {
                        "title": title,
                        "url": url,
                        "last_modified": last_modified,
                        "domain": domain,
                        "division": division,
                        "header_image": header_image,
                        "slug": slug,
                    }
                )

    return {
        domain: sorted(articles, key=lambda x: x["last_modified"], reverse=True)
        for domain, articles in sorted(categorized_articles.items())
    }


def load_json(fp: str, default):
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(fp: str, data) -> None:
    try:
        ensure_directory(os.path.dirname(fp))
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as err:
        logger.error(f"Error writing json to {fp}: {err}")


def scan_content_files() -> dict:
    content_files = {}
    for root, _, files in os.walk(content_dir):
        for file in files:
            if file.endswith(".md"):
                fp = os.path.join(root, file)
                rel = os.path.relpath(fp, content_dir)
                content_files[rel] = os.path.getmtime(fp)
    return content_files


def scan_public_files() -> dict:
    public_files = {}
    valid_assets = (
        ".html",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
        ".mp4",
        ".avif",
        ".bmp",
    )
    for root, _, files in os.walk(public_dir):
        for file in files:
            if file.endswith(valid_assets):
                fp = os.path.join(root, file)
                rel = os.path.relpath(fp, public_dir)
                public_files[rel] = os.path.getmtime(fp)
    return public_files


def update_activity_log() -> tuple[list[dict], list[dict]]:
    """
    Track created/modified/deleted generated HTML files and record events.
    Returns (activity_graph_data, changelog) for convenience.
    """
    state_fp = os.path.join(logs_dir, "activity_state.json")
    log_fp = os.path.join(logs_dir, "activity_log.json")

    previous = load_json(state_fp, {})
    current = scan_public_files()

    events = []

    for path, mtime in current.items():
        if path not in previous:
            ts = datetime.fromtimestamp(mtime).isoformat()
            events.append(
                {
                    "path": path,
                    "url": f"/{path.replace(os.sep, '/')}",
                    "action": "created",
                    "timestamp": ts,
                }
            )
        elif previous[path] != mtime:
            ts = datetime.fromtimestamp(mtime).isoformat()
            events.append(
                {
                    "path": path,
                    "url": f"/{path.replace(os.sep, '/')}",
                    "action": "modified",
                    "timestamp": ts,
                }
            )

    for path in previous:
        if path not in current:
            ts = datetime.utcnow().isoformat()
            events.append(
                {
                    "path": path,
                    "url": f"/{path.replace(os.sep, '/')}",
                    "action": "deleted",
                    "timestamp": ts,
                }
            )

    if events:
        existing_log = load_json(log_fp, [])
        existing_log.extend(events)
        save_json(log_fp, existing_log)

    save_json(state_fp, current)

    return get_activity_graph(log_fp), get_recent_events(log_fp)


def get_activity_graph(log_fp: str, days: int = 365) -> list[dict]:
    log = load_json(log_fp, [])
    today = datetime.utcnow().date()
    window = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    counts = {d.isoformat(): 0 for d in window}

    for entry in log:
        ts = entry.get("timestamp")
        try:
            dt = datetime.fromisoformat(ts)
            day = dt.date().isoformat()
            if day in counts:
                counts[day] += 1
        except Exception:
            continue

    def level(count: int) -> int:
        if count == 0:
            return 0
        if count == 1:
            return 1
        if count <= 3:
            return 2
        if count <= 6:
            return 3
        return 4

    return [
        {"date": str(day), "count": counts[day], "level": level(counts[day])}
        for day in counts
    ]


def get_commit_activity(entries: list[dict], days: int = 365) -> list[dict]:
    """
    Build a contribution-style graph from commit timestamps.
    """
    today = datetime.utcnow().date()
    window = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    counts = {d.isoformat(): 0 for d in window}

    for entry in entries:
        ts = entry.get("timestamp")
        try:
            dt = datetime.fromisoformat(ts)
            day = dt.date().isoformat()
            if day in counts:
                counts[day] += 1
        except Exception:
            continue

    def level(count: int) -> int:
        if count == 0:
            return 0
        if count == 1:
            return 1
        if count <= 3:
            return 2
        if count <= 6:
            return 3
        return 4

    return [{"date": d, "count": counts[d], "level": level(counts[d])} for d in counts]


def get_recent_events(log_fp: str, limit: int = 20) -> list[dict]:
    log = load_json(log_fp, [])
    try:
        log.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    except Exception:
        pass
    return log[:limit]


def load_markdown_inventory() -> list[dict]:
    inventory = []
    for root, _, files in os.walk(content_dir):
        for file in files:
            if file.endswith(".md"):
                fp = os.path.join(root, file)
                try:
                    parsed = parse_frontmatter(fp)
                    frontmatter = parsed.get("frontmatter", {})
                    for k, v in list(frontmatter.items()):
                        if isinstance(v, (datetime,)):
                            frontmatter[k] = v.isoformat()
                        else:
                            try:
                                import datetime as _dt

                                if isinstance(v, (_dt.date, _dt.datetime)):
                                    frontmatter[k] = str(v)
                            except Exception:
                                pass
                    content = parsed.get("content", "")
                    rel = os.path.relpath(fp, content_dir)
                    parts = rel.split(os.sep)
                    url = "/" + "/".join(parts).replace(".md", ".html")
                    inventory.append(
                        {
                            "title": frontmatter.get(
                                "title", os.path.splitext(file)[0]
                            ),
                            "url": url,
                            "frontmatter": frontmatter,
                            "content": content,
                        }
                    )
                except Exception:
                    continue
    return inventory


def get_page_changelog(log_fp: str, page_path: str, limit: int = 20) -> list[dict]:
    """
    Filter activity log entries for a specific generated HTML path (public-relative).
    """
    log = load_json(log_fp, [])
    normalized = page_path.lstrip("/").replace("\\", "/")
    filtered = [
        entry for entry in log if entry.get("path", "").replace("\\", "/") == normalized
    ]
    try:
        filtered.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    except Exception:
        pass
    return filtered[:limit]


def get_recent_articles(max_items: int = 6) -> list[dict]:
    """
    Flatten articles across domains and return the latest items by last_modified.
    """
    flattened = []
    categorized = get_articles_list()
    cache_lookup = {}
    try:
        for row in list_articles():
            cache_lookup[row["slug"]] = row
    except Exception:
        cache_lookup = {}

    for _, articles in categorized.items():
        flattened.extend(articles)

    try:
        flattened.sort(
            key=lambda x: datetime.fromisoformat(
                str(x.get("last_modified", "1970-01-01"))
            ),
            reverse=True,
        )
    except Exception:
        flattened.sort(key=lambda x: x.get("last_modified", ""), reverse=True)

    enriched = []
    for item in flattened[:max_items]:
        slug = item.get("url", "").lstrip("/").replace(".html", "")
        cache = cache_lookup.get(slug, {})
        drift = "—"
        if cache.get("last_timestamp"):
            try:
                dt = datetime.fromisoformat(str(cache["last_timestamp"]))
                drift = f"{max((datetime.utcnow() - dt).days, 0)}d"
            except Exception:
                drift = "—"
        item["entry_fingerprint"] = cache.get("last_hash")
        item["entry_drift"] = drift
        enriched.append(item)

    return enriched


def get_recent_media(max_items: int = 12) -> list[dict]:
    media_items = []
    image_root = os.path.join(content_dir, "images")
    video_root = os.path.join(content_dir, "videos")
    valid_images = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".bmp")
    valid_videos = (".mp4",)

    for root, _, files in os.walk(image_root):
        for file in files:
            if file.lower().endswith(valid_images):
                fp = os.path.join(root, file)
                rel = os.path.relpath(fp, image_root)
                ts = os.path.getmtime(fp)
                media_items.append(
                    {
                        "url": f"images/{rel}".replace("\\", "/"),
                        "type": "image",
                        "title": os.path.splitext(file)[0].replace("-", " ").title(),
                        "timestamp": ts,
                        "stamp": datetime.fromtimestamp(ts).strftime("%Y%m%d%H%M%S"),
                        "basename": file,
                    }
                )

    for root, _, files in os.walk(video_root):
        for file in files:
            if file.lower().endswith(valid_videos):
                fp = os.path.join(root, file)
                rel = os.path.relpath(fp, video_root)
                ts = os.path.getmtime(fp)
                media_items.append(
                    {
                        "url": f"videos/{rel}".replace("\\", "/"),
                        "type": "video",
                        "title": os.path.splitext(file)[0].replace("-", " ").title(),
                        "timestamp": ts,
                        "stamp": datetime.fromtimestamp(ts).strftime("%Y%m%d%H%M%S"),
                        "basename": file,
                    }
                )

    media_items.sort(key=lambda x: x["timestamp"], reverse=True)
    inventory = load_markdown_inventory()

    for item in media_items:
        item["articles"] = []
        base = item.get("basename", "")
        for md in inventory:
            text = (md.get("content", "") or "") + json.dumps(md.get("frontmatter", {}))
            if base and base in text:
                url = md.get("url", "")
                slug = url.lstrip("/").replace(".html", "")
                item["articles"].append(
                    {
                        "title": md.get("title"),
                        "url": url,
                        "hash": get_entry_fingerprint(slug),
                        "slug": slug,
                    }
                )
        if not item["articles"]:
            # fallback: not found, leave empty
            item["articles"] = []

    media_items = [m for m in media_items if m.get("articles")]
    return media_items[:max_items]


def derive_header_image(frontmatter: dict, content: str) -> str | None:
    if "header_image" in frontmatter and frontmatter.get("header_image"):
        return frontmatter.get("header_image")

    media = parse_first_media(content)
    if not media:
        return None
    path = media
    if path.startswith("http://") or path.startswith("https://"):
        return path
    ext = os.path.splitext(path)[1].lower()
    if ext in [".mp4"]:
        return f"videos/{os.path.basename(path)}"
    return f"images/{os.path.basename(path)}"


def parse_first_media(content: str) -> str | None:
    import re

    match = re.search(r"!\[[^\]]*?\]\(([^)]+)\)", content)
    if match:
        return match.group(1)
    return None


def process_file(
    md_fp: str,
    output_fp: str,
    default_template: str,
    backlinks: dict,
    commit: bool = False,
    commit_context: dict | None = None,
) -> None:
    try:
        logger.info(f"Processing file: {md_fp}")

        if os.path.exists(output_fp):
            os.remove(output_fp)
            logger.info(f"Deleted old file: {output_fp}")

        parsed_data = parse_frontmatter(md_fp)
        frontmatter = parsed_data.get("frontmatter", {})
        raw_content = parsed_data.get("content", "")

        # Overwrite last_modified to current UTC time for accurate surface
        frontmatter["last_modified"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        slug = (
            os.path.relpath(md_fp, content_dir).replace(os.sep, "/").replace(".md", "")
        )
        fingerprint = compute_fingerprint(md_fp)
        entry_fingerprint = get_entry_fingerprint(slug) or fingerprint
        entry_guid = get_entry_guid(slug)
        latest_cache_row = get_article_cache(slug)
        latest_cache = dict(latest_cache_row) if latest_cache_row else None
        latest_commit_row = get_latest_commit(slug)
        prev_commit_row = get_previous_commit(slug)
        latest_meta_raw = (
            latest_commit_row["meta_json"]
            if latest_commit_row and latest_commit_row["meta_json"]
            else None
        )
        latest_meta = json.loads(latest_meta_raw) if latest_meta_raw else {}
        entry_drift = "—"
        if latest_cache and latest_cache.get("last_timestamp"):
            try:
                last_dt = datetime.fromisoformat(str(latest_cache["last_timestamp"]))
                entry_drift = f"{max((datetime.utcnow() - last_dt).days, 0)}d"
            except Exception:
                entry_drift = "—"

        if commit:
            try:
                latest = latest_cache
                latest_hash = latest["last_hash"] if latest else None
                if latest_hash != fingerprint:
                    summary_val = None
                    if commit_context and commit_context.get("bundle"):
                        summary_val = commit_context.get("shared_summary")
                        if not summary_val:
                            prompt = (
                                commit_context.get("summary_prompt")
                                or f"Summary for bundle ({fingerprint}): "
                            )
                            summary_val = ""
                            while not summary_val.strip():
                                summary_val = input(prompt).strip()
                            commit_context["shared_summary"] = summary_val
                    else:
                        summary_val = ""
                        while not summary_val.strip():
                            summary_val = input(
                                f"Summary for {slug} ({fingerprint}): "
                            ).strip()
                    parent_hash = latest_hash
                    word_count = len(raw_content.split())
                    worked_hours = (
                        float(frontmatter["worked"])
                        if "worked" in frontmatter
                        and str(frontmatter["worked"]).replace(".", "", 1).isdigit()
                        else 0.0
                    )
                    insert_commit(
                        slug=slug,
                        hash_val=fingerprint,
                        summary=summary_val,
                        frontmatter=frontmatter,
                        word_count=word_count,
                        worked_hours=worked_hours,
                        parent_hash=parent_hash,
                    )
                    if commit_context is not None:
                        commit_context["commits"] = commit_context.get("commits", 0) + 1
                    entry_fingerprint = fingerprint
                    entry_drift = "0d"
            except Exception as err:
                logger.error(f"Error during commit flow for {md_fp}: {err}")

        logger.info("Parsing footnotes.")
        footnotes_content, footnotes = parse_footnotes(raw_content)

        logger.info("Parsing articles.")
        articles = parse_articles(footnotes_content, os.path.basename(md_fp), backlinks)

        logger.info("Looking for related articles.")
        related = parse_related(frontmatter)

        template_name = frontmatter.get("template", default_template)
        logger.info(f"Using template: {template_name} for {md_fp}")

        gallery = frontmatter.get("gallery", [])
        if not isinstance(gallery, list):
            gallery = []

        tags = frontmatter.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        elif not isinstance(tags, list):
            tags = []

        header_image = derive_header_image(frontmatter, raw_content)

        worked_val = frontmatter.get("worked", 0)
        try:
            worked_val = float(worked_val)
        except Exception:
            worked_val = 0.0

        if (
            latest_commit_row is not None
            and latest_commit_row["worked_hours"] is not None
        ):
            try:
                worked_val = float(latest_commit_row["worked_hours"])
            except Exception:
                pass

        worked_delta = 0.0
        if latest_commit_row and prev_commit_row:
            try:
                latest_work = float(latest_commit_row["worked_hours"] or 0)
                prev_work = float(prev_commit_row["worked_hours"] or 0)
                worked_delta = latest_work - prev_work
            except Exception:
                worked_delta = 0.0

        domain_val = frontmatter.get("domain", latest_meta.get("domain", "N/A"))
        division_val = frontmatter.get("division", latest_meta.get("division", []))
        if isinstance(division_val, str):
            division_val = [division_val]
        created_val = frontmatter.get(
            "created", latest_commit_row["created"] if latest_commit_row else "N/A"
        )
        if created_val is None:
            created_val = "N/A"
        else:
            created_val = str(created_val)
        if domain_val is None:
            domain_val = "N/A"

        context = {
            "title": frontmatter.get("title", "Untitled"),
            "description": frontmatter.get("description", ""),
            "entry_fingerprint": entry_fingerprint,
            "entry_revisions_url": "/revisions/index.html",
            "entry_drift": entry_drift,
            "entry_worked": worked_val if worked_val is not None else None,
            "entry_guid": entry_guid,
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
            "backlinks": backlinks.get(
                os.path.splitext(os.path.basename(md_fp))[0], []
            ),
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
        }

        if template_name == "section.html":
            context["categorized_articles"] = get_articles_list()
        if template_name == "index.html":
            context["recent_articles"] = get_recent_articles()
            context["categorized_articles"] = get_articles_list()
            try:
                context["domain_max"] = (
                    max(len(v) for v in context["categorized_articles"].values())
                    if context["categorized_articles"]
                    else 0
                )
            except Exception:
                context["domain_max"] = 0
            context["categories"] = get_categories()
            global_changes = get_global_changelog(limit=500)
            context["activity_graph"] = get_commit_activity(global_changes, days=365)
            context["changelog"] = global_changes[:30]
            context["recent_media"] = get_recent_media()

        rendered_html = render_template_context(template_name, context)
        ensure_directory(os.path.dirname(output_fp))
        # logger.info(f"Rendering template with context:\n{json.dumps(context, indent=4)}")
        with open(output_fp, "w", encoding="utf-8") as f:
            f.write(rendered_html)

        logger.info(f"Generated: {output_fp} using template {template_name}")
    except Exception as err:
        logger.error(f"Error processing file {md_fp}: {err}")


def generate_static_site(
    category="all",
    commit: bool = False,
    commit_all: bool = False,
    summary: str | None = None,
):
    try:
        logger.info("Starting site generation.")
        categories = get_categories()
        backlinks = {}
        init_db()
        commit_context = {"bundle": commit_all, "shared_summary": summary, "commits": 0}

        logger.info("Checking and generating missing markdown files.")
        generate_missing()

        process_index(content_dir, public_dir, backlinks, commit, commit_context)

        if category == "all":
            for cat in categories:
                process_category(
                    cat, content_dir, public_dir, backlinks, commit, commit_context
                )
        else:
            if category in categories:
                process_category(
                    category, content_dir, public_dir, backlinks, commit, commit_context
                )
            else:
                logger.error(f"Invalid category: {category}")
        logger.info("Copying all necessary static files.")
        copy_static_files()
        merge_image_dir()
        merge_video_dir()
        compile_scss()
        logger.info("Updating activity log based on generated HTML changes.")
        update_activity_log()
        try:
            generate_revision_pages()
            generate_domain_pages()
        except Exception as err:
            logger.error(f"Error generating revision pages: {err}")

        if commit and commit_context.get("commits", 0) == 0:
            msg = "No content changes detected; no commits recorded."
            print(msg)
            logger.info(msg)

    except Exception as err:
        logger.error(f"Error generating static site: {err}", exc_info=True)


def process_category(
    category: str,
    content_dir: str,
    public_dir: str,
    backlinks: dict,
    commit: bool = False,
    commit_context: dict | None = None,
) -> None:
    try:
        logger.info(f"Processing category: {category}")
        category_dir = os.path.join(content_dir, category)
        output_dir = os.path.join(public_dir, category)

        if not os.path.isdir(category_dir):
            logger.error(f"Category directory `{category_dir}` does not exist.")
            return

        for file in os.listdir(category_dir):
            if file.endswith(".md"):
                md_fp = os.path.join(category_dir, file)
                output_fp = os.path.join(output_dir, file.replace(".md", ".html"))

                default_template = f"{category}.html"
                process_file(
                    md_fp,
                    output_fp,
                    default_template,
                    backlinks,
                    commit,
                    commit_context,
                )
    except Exception as err:
        logger.error(f"Error processing category `{category}`: {err}", exc_info=True)


def process_index(
    content_dir: str,
    public_dir: str,
    backlinks: dict,
    commit: bool = False,
    commit_context: dict | None = None,
) -> None:
    try:
        logger.info("Processing `index.md`.")
        index_md_fp = os.path.join(content_dir, "index.md")
        index_output_fp = os.path.join(public_dir, "index.html")

        if not os.path.exists(index_md_fp):
            logger.error(f"`index.md` file does not exist at: {index_md_fp}")
            return

        process_file(
            index_md_fp,
            index_output_fp,
            "index.html",
            backlinks,
            commit,
            commit_context,
        )
        logger.info(f"Processed `index.md` into {index_output_fp}")
    except Exception as err:
        logger.error(f"Error processing `index.md`: {err}")


def generate_revision_pages() -> None:
    """
    Render global and per-article revision pages from the revisions database.
    """
    try:
        logger.info("Generating revision pages.")
        revisions_dir = os.path.join(public_dir, "revisions")
        ensure_directory(revisions_dir)

        global_changelog = get_global_changelog(limit=None)
        rendered_global = render_template_context(
            "revisions_index.html",
            {
                "global_changelog": global_changelog,
            },
        )
        with open(
            os.path.join(revisions_dir, "index.html"), "w", encoding="utf-8"
        ) as f:
            f.write(rendered_global)
        logger.info("Finished generating global revision page.")
    except Exception as err:
        logger.error(f"Error in generate_revision_pages: {err}", exc_info=True)


def generate_domain_pages() -> None:
    """
    Generate per-domain listing pages under /public/domains.
    """
    try:
        logger.info("Generating domain pages.")
        domain_dir = os.path.join(public_dir, "domains")
        ensure_directory(domain_dir)

        categorized = get_articles_list()
        for domain, articles in categorized.items():
            slug = domain.lower().replace(" ", "-")
            context = {
                "domain": domain,
                "articles": articles,
                "title": f"{domain} — Domain entries",
                "description": f"Entries for {domain}",
            }
            rendered = render_template_context("domain_listing.html", context)
            dest_fp = os.path.join(domain_dir, f"{slug}.html")
            ensure_directory(os.path.dirname(dest_fp))
            with open(dest_fp, "w", encoding="utf-8") as f:
                f.write(rendered)
        logger.info("Finished generating domain pages.")
    except Exception as err:
        logger.error(f"Error generating domain pages: {err}", exc_info=True)
