import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from src.base_utils import (
    content_dir,
    ensure_directory,
    public_dir,
    setup_logger,
    snapshots_dir,
    templates_dir,
)
from src.markdown_parser import parse_frontmatter

logger = setup_logger("file_manager", "logs/file_manager.log")
CONTENT_PATH = Path(content_dir)
PUBLIC_PATH = Path(public_dir)
TEMPLATES_PATH = Path(templates_dir)
SNAPSHOTS_PATH = Path(snapshots_dir)
LOGS_PATH = Path(os.path.dirname(os.path.abspath(__file__))) / ".." / "logs"


def get_categories() -> list[str]:
    try:
        logger.info("Fetching categories from content directory.")
        if not CONTENT_PATH.exists():
            logger.warning(f"Content directory does not exist: {CONTENT_PATH}")
            return []

        categories = []
        for item in CONTENT_PATH.iterdir():
            if item.is_dir():
                category_md_file = item / f"{item.name}.md"
                if category_md_file.is_file():
                    categories.append(item.name)
        logger.info(f"Categories found: {categories}")
        return categories
    except Exception as err:
        logger.error(f"Error fetching categories: {err}", exc_info=True)
        return []


def setup_project() -> None:
    try:
        logger.info("Setting up project directories.")
        required_dirs = [
            CONTENT_PATH,
            TEMPLATES_PATH,
            PUBLIC_PATH,
            SNAPSHOTS_PATH,
            LOGS_PATH,
        ]

        try:
            categories = get_categories()
            for category in categories:
                required_dirs.append(CONTENT_PATH / category)
                required_dirs.append(PUBLIC_PATH / category)
        except Exception as err:
            logger.error(f"Error retrieving categories: {err}", exc_info=True)

        for directory in required_dirs:
            try:
                ensure_directory(str(directory))
                logger.info(f"Verified or created directory: {directory}")
            except Exception as err:
                logger.error(
                    f"Error creating or verifying directory {directory}: {err}",
                    exc_info=True,
                )
    except Exception as err:
        logger.error(f"Unexpected error in setup_project: {err}", exc_info=True)


def generate_section() -> None:
    logger.info("Regenerating section markdown files.")
    try:
        categories = get_categories()
    except Exception as err:
        logger.error(
            f"Error fetching categories for section generation: {err}", exc_info=True
        )
        return

    for category in categories:
        try:
            section_md_fp = CONTENT_PATH / category / f"{category}.md"
            articles = []
            category_root = CONTENT_PATH / category

            for md_path in category_root.rglob("*.md"):
                if md_path.name == f"{category}.md":
                    continue
                try:
                    frontmatter_data = parse_frontmatter(str(md_path))
                    frontmatter = frontmatter_data.get("frontmatter", {}) or {}
                    title = frontmatter.get("title", md_path.stem)
                    created = frontmatter.get("created", "Unknown")
                    domain = frontmatter.get("domain", "Uncategorized")
                    wikilink = f"[[{title}]]"
                    articles.append(
                        {
                            "title": title,
                            "wikilink": wikilink,
                            "created": created,
                            "domain": domain,
                            "url": f"/{category}/{md_path.with_suffix('.html').name}",
                        }
                    )
                except Exception as parse_err:
                    logger.error(
                        f"Error parsing article frontmatter {md_path}: {parse_err}",
                        exc_info=True,
                    )
                    continue

            articles.sort(key=lambda x: x["created"], reverse=True)

            articles_by_domain: dict[str, list[dict]] = {}
            for article in articles:
                articles_by_domain.setdefault(article["domain"], []).append(article)

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_content_lines = [
                "---",
                f"title: {category.title()}",
                f'description: "This section contains all {category}."',
                f"created: {now_str}",
                f"last_modified: {now_str}",
                "---",
                "",
                f"# {category.title()}",
                "",
                "## Latest Articles",
            ]
            new_content_lines.extend(
                [
                    f"- {article['wikilink']} - {article['created']}"
                    for article in articles[:5]
                ]
            )
            new_content_lines.append("")
            new_content_lines.append("## All Articles by Domain")
            for domain, domain_articles in articles_by_domain.items():
                new_content_lines.append(f"\n### {domain.title()}")
                new_content_lines.extend(
                    [f"- {article['wikilink']}" for article in domain_articles]
                )

            new_content = "\n".join(new_content_lines)
            try:
                with section_md_fp.open("w", encoding="utf-8") as f:
                    f.write(new_content)
                logger.info(f"Updated section markdown: {section_md_fp}")
            except Exception as write_err:
                logger.error(
                    f"Error writing section markdown {section_md_fp}: {write_err}",
                    exc_info=True,
                )
        except Exception as err:
            logger.error(f"Error processing category {category}: {err}", exc_info=True)


def generate_missing() -> None:
    template_fp = CONTENT_PATH.parent / "src" / "templates" / "template.md"

    try:
        if not template_fp.exists():
            logger.error(f"Template file not found: {template_fp}")
            return

        with template_fp.open("r", encoding="utf-8") as template_file:
            template_content = template_file.read()
        # please god ignore fenced code
        fenced_re = re.compile(r"```.*?```", re.S)
        inline_code_re = re.compile(r"`[^`]*`")

        for md_path in CONTENT_PATH.rglob("*.md"):
            try:
                markdown_content = md_path.read_text(encoding="utf-8")

                scrubbed = fenced_re.sub("", markdown_content)
                scrubbed = inline_code_re.sub("", scrubbed)

                pattern = r"\[\[(.*?)\]\]"
                wikilinks = re.findall(pattern, scrubbed)

                for link in wikilinks:
                    slug = link.replace(" ", "-").lower()
                    filename = f"{slug}.md"

                    file_found = any(
                        path.name == filename for path in CONTENT_PATH.rglob(filename)
                    )

                    if file_found:
                        logger.info(f"File already exists for wikilink: {link}")
                        continue

                    category = (
                        md_path.parent.name
                        if md_path.parent != CONTENT_PATH
                        else "articles"
                    )
                    category_dir = CONTENT_PATH / category
                    ensure_directory(str(category_dir))

                    filepath = category_dir / filename

                    frontmatter = template_content.format(
                        title=link.title(),
                        created=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        last_modified=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    )

                    filepath.write_text(frontmatter, encoding="utf-8")
                    logger.info(f"Created missing file: {filepath}")
            except Exception as md_err:
                logger.error(
                    f"Error processing markdown file {md_path}: {md_err}",
                    exc_info=True,
                )

    except Exception as err:
        logger.error(f"Error during generate_missing: {err}", exc_info=True)


def cleanup_orphans() -> None:
    """
    Deletes HTML files in the public directory if their corresponding Markdown files
    no longer exist in the content directory.
    """
    try:
        logger.info("Starting orphan cleanup process.")
        md_files = {path.stem for path in CONTENT_PATH.rglob("*.md")}

        for html_path in PUBLIC_PATH.rglob("*.html"):
            if html_path.stem not in md_files:
                html_path.unlink()
                logger.info(f"Deleted orphaned HTML file: {html_path}")
    except Exception as err:
        logger.error(
            f"Error during cleanup of orphaned HTML files: {err}", exc_info=True
        )


def merge_image_dir() -> None:
    _copy_dir(CONTENT_PATH / "images", PUBLIC_PATH / "images", label="image")


def merge_video_dir() -> None:
    _copy_dir(CONTENT_PATH / "videos", PUBLIC_PATH / "videos", label="video")


def _copy_dir(source_dir: Path, dest_dir: Path, label: str) -> None:
    if not source_dir.exists():
        logger.info(
            f"Source {label}s directory does not exist: {source_dir}. Skipping."
        )
        return

    ensure_directory(str(dest_dir))

    try:
        for root, _, files in os.walk(source_dir):
            for file in files:
                source_file = Path(root) / file
                rel_path = source_file.relative_to(source_dir)
                destination_file = dest_dir / rel_path

                ensure_directory(str(destination_file.parent))

                shutil.copy2(source_file, destination_file)
                logger.info(f"Copied {label}: {source_file} -> {destination_file}")
    except Exception as err:
        logger.error(f"Error merging {label}s directory: {err}", exc_info=True)
