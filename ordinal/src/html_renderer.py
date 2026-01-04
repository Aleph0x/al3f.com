import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from src.activity_helpers import (
    get_activity_graph,
    get_commit_activity,
    get_recent_events,
)
from src.base_utils import (
    content_dir,
    ensure_directory,
    logs_dir,
    public_dir,
    setup_logger,
)
from src.commit_flow import record_commit, should_commit
from src.context_builder import (
    attach_index_context,
    attach_section_context,
    build_entry_context,
)
from src.file_manager import (
    generate_missing,
    get_categories,
    merge_image_dir,
    merge_video_dir,
)
from src.markdown_parser import (
    parse_articles,
    parse_footnotes,
    parse_frontmatter,
    parse_related,
)
from src.revisions import (
    compute_fingerprint,
    get_article_cache,
    get_global_changelog,
    init_db,
    list_articles,
)
from src.taxonomy import get_articles_list, get_recent_articles

logger = setup_logger("html_renderer", "logs/html_renderer.log")

CONTENT_PATH = Path(content_dir)
PUBLIC_PATH = Path(public_dir)
STATIC_SRC = Path("src/static")
TEMPLATES_PATH = Path("src/templates")
ACTIVITY_STATE_FP = Path(logs_dir) / "activity_state.json"
ACTIVITY_LOG_FP = Path(logs_dir) / "activity_log.json"
VALID_ASSETS = {
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
}

env = Environment(loader=FileSystemLoader(TEMPLATES_PATH))


def compile_scss():
    try:
        scss_path = STATIC_SRC / "styles" / "main.scss"
        css_output = PUBLIC_PATH / "styles" / "main.css"
        ensure_directory(str(css_output.parent))
        subprocess.run(["sass", str(scss_path), str(css_output)], check=True)
        logger.info(f"Compiled SCSS: {scss_path} -> {css_output}")
    except Exception as err:
        logger.error(f"Error compiling SCSS: {err}")


def copy_static_files():
    try:
        static_dest = PUBLIC_PATH
        ensure_directory(str(static_dest))

        _remove_scss(static_dest)

        for root, _, files in os.walk(STATIC_SRC):
            for file in files:
                if file.endswith(".scss"):
                    # Skip copying source SCSS only compiled CSS belongs in public
                    continue
                src_fp = Path(root) / file
                rel_fp = src_fp.relative_to(STATIC_SRC)
                dest_fp = static_dest / rel_fp
                ensure_directory(str(dest_fp.parent))
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


def load_json(fp: Path, default):
    try:
        with fp.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as err:
        logger.error(f"Error loading json from {fp}: {err}")
        return default


def save_json(fp: Path, data) -> None:
    try:
        ensure_directory(str(fp.parent))
        with fp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as err:
        logger.error(f"Error writing json to {fp}: {err}")


def _render_to_file(template_name: str, context: dict, dest: Path) -> None:
    rendered_html = render_template_context(template_name, context)
    ensure_directory(str(dest.parent))
    with dest.open("w", encoding="utf-8") as f:
        f.write(rendered_html)


def scan_content_files() -> dict:
    content_files = {}
    for fp in _walk_files(CONTENT_PATH, suffixes=(".md",)):
        rel = fp.relative_to(CONTENT_PATH)
        content_files[rel.as_posix()] = fp.stat().st_mtime
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
    for fp in _walk_files(PUBLIC_PATH, suffixes=valid_assets):
        rel = fp.relative_to(PUBLIC_PATH)
        public_files[rel.as_posix()] = fp.stat().st_mtime
    return public_files


def update_activity_log() -> tuple[list[dict], list[dict]]:
    """
    Track created/modified/deleted generated HTML files and record events.
    Returns (activity_graph_data, changelog) for convenience.
    """
    previous = load_json(ACTIVITY_STATE_FP, {})
    current = scan_public_files()

    events = []

    for path, mtime in current.items():
        if path not in previous:
            ts = datetime.fromtimestamp(mtime).isoformat()
            events.append(
                {
                    "path": path,
                    "url": f"/{path}",
                    "action": "created",
                    "timestamp": ts,
                }
            )
        elif previous[path] != mtime:
            ts = datetime.fromtimestamp(mtime).isoformat()
            events.append(
                {
                    "path": path,
                    "url": f"/{path}",
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
                    "url": f"/{path}",
                    "action": "deleted",
                    "timestamp": ts,
                }
            )

    if events:
        existing_log = load_json(ACTIVITY_LOG_FP, [])
        existing_log.extend(events)
        save_json(ACTIVITY_LOG_FP, existing_log)

    save_json(ACTIVITY_STATE_FP, current)

    return get_activity_graph(str(ACTIVITY_LOG_FP)), get_recent_events(
        str(ACTIVITY_LOG_FP)
    )


def load_markdown_inventory() -> list[dict]:
    from src.media_helpers import load_markdown_inventory as load_md

    return load_md()


def get_page_changelog(log_fp: str, page_path: str, limit: int = 20) -> list[dict]:
    """
    Filter activity log entries for a specific generated HTML path (public-relative).
    """
    log = load_json(Path(log_fp), [])
    normalized = page_path.lstrip("/").replace("\\", "/")
    filtered = [
        entry for entry in log if entry.get("path", "").replace("\\", "/") == normalized
    ]
    try:
        filtered.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    except Exception as err:
        logger.warning(f"Error sorting changelog for {page_path}: {err}")
        pass
    return filtered[:limit]


def get_recent_articles(max_items: int = 6) -> list[dict]:
    try:
        from src.taxonomy import get_recent_articles as _recent

        return _recent(max_items)
    except Exception as err:
        logger.error(f"Error getting recent articles: {err}")
        return []


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
        out_path = Path(output_fp)

        if out_path.exists():
            out_path.unlink()
            logger.info(f"Deleted old file: {output_fp}")

        parsed_data = parse_frontmatter(md_fp)
        context = build_entry_context(
            md_fp,
            default_template,
            backlinks,
            commit,
            commit_context,
            parsed_data,
        )
        frontmatter = context["frontmatter"]
        raw_content = parsed_data.get("content", "")
        slug = context["slug"]
        entry_fingerprint = context["entry_fingerprint"]

        if commit and should_commit(slug, entry_fingerprint):
            worked_hours = (
                float(frontmatter["worked"])
                if "worked" in frontmatter
                and str(frontmatter["worked"]).replace(".", "", 1).isdigit()
                else 0.0
            )
            latest = get_article_cache(slug)
            parent_hash = latest["last_hash"] if latest else None
            try:
                entry_fingerprint, entry_drift = record_commit(
                    slug,
                    compute_fingerprint(md_fp),
                    frontmatter,
                    raw_content,
                    worked_hours,
                    parent_hash,
                    commit_context,
                )
                context["entry_fingerprint"] = entry_fingerprint
                context["entry_drift"] = entry_drift
            except Exception as err:
                logger.error(f"Error during commit flow for {md_fp}: {err}")

        template_name = context.pop("template_name", default_template)
        if (
            output_fp.endswith("index.html")
            and default_template == "index.html"
            and template_name != "index.html"
        ):
            logger.warning(
                f"Index output {output_fp} attempted to use template '{template_name}', forcing 'index.html'."
            )
            template_name = "index.html"

        if template_name == "section.html":
            try:
                attach_section_context(context)
            except Exception as err:
                logger.error(
                    f"Error attaching section context for {md_fp}: {err}", exc_info=True
                )
        if template_name == "index.html":
            try:
                attach_index_context(context)
            except Exception as err:
                logger.error(
                    f"Error attaching index context for {md_fp}: {err}", exc_info=True
                )

        _render_to_file(template_name, context, out_path)
        logger.info(f"Generated: {output_fp} using template {template_name}")
    except Exception as err:
        logger.error(f"Error processing file {md_fp}: {err}", exc_info=True)


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

        if category != "all" and category not in categories:
            logger.error(f"Invalid category: {category}")
            return

        cats = categories if category == "all" else [category]
        for cat in cats:
            process_category(
                cat, content_dir, public_dir, backlinks, commit, commit_context
            )

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
        category_dir = Path(content_dir) / category
        output_dir = Path(public_dir) / category

        if not os.path.isdir(category_dir):
            logger.error(f"Category directory `{category_dir}` does not exist.")
            return

        for file in category_dir.iterdir():
            if file.is_file() and file.suffix == ".md":
                md_fp = str(file)
                output_fp = str(output_dir / f"{file.stem}.html")

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
        index_md_fp = Path(content_dir) / "index.md"
        index_output_fp = Path(public_dir) / "index.html"

        if not index_md_fp.exists():
            logger.error(f"`index.md` file does not exist at: {index_md_fp}")
            return

        process_file(
            str(index_md_fp),
            str(index_output_fp),
            "index.html",
            backlinks,
            commit,
            commit_context,
        )
        logger.info(f"Processed `index.md` into {index_output_fp}")
    except Exception as err:
        logger.error(f"Error processing `index.md`: {err}", exc_info=True)


def generate_revision_pages() -> None:
    """
    Render global and per-article revision pages from the revisions database.
    """
    try:
        logger.info("Generating revision pages.")
        revisions_dir = PUBLIC_PATH / "revisions"
        ensure_directory(str(revisions_dir))

        global_changelog = get_global_changelog(limit=None)
        _render_to_file(
            "revisions_index.html",
            {"global_changelog": global_changelog},
            revisions_dir / "index.html",
        )
        logger.info("Finished generating global revision page.")
    except Exception as err:
        logger.error(f"Error in generate_revision_pages: {err}", exc_info=True)


def generate_domain_pages() -> None:
    """
    Generate per-domain listing pages under /public/domains.
    """
    try:
        logger.info("Generating domain pages.")
        domain_dir = PUBLIC_PATH / "domains"
        ensure_directory(str(domain_dir))

        categorized = get_articles_list()
        for domain, articles in categorized.items():
            slug = domain.lower().replace(" ", "-")
            context = {
                "domain": domain,
                "articles": articles,
                "title": f"{domain} — Domain entries",
                "description": f"Entries for {domain}",
            }
            _render_to_file("domain_listing.html", context, domain_dir / f"{slug}.html")
        logger.info("Finished generating domain pages.")
    except Exception as err:
        logger.error(f"Error generating domain pages: {err}", exc_info=True)


def _remove_scss(target_dir: Path) -> None:
    for root, _, files in os.walk(target_dir):
        for file in files:
            if file.endswith(".scss"):
                try:
                    stray = Path(root) / file
                    stray.unlink()
                    logger.info(f"Removed stray SCSS from public: {stray}")
                except Exception as err:
                    logger.error(f"Error removing stray SCSS from public: {err}")


def _walk_files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if suffixes and not name.lower().endswith(suffixes):
                continue
            files.append(Path(dirpath) / name)
    return files
