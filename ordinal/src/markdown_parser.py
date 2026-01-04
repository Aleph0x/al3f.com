import os
import re
import yaml
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from src.base_utils import content_dir, ensure_directory, setup_logger

logger = setup_logger("markdown_parser", "logs/markdown_parser.log")
CONTENT_PATH = Path(content_dir)

TABLE_RE = re.compile(
    r"^(\|(?:.*\|)+)\n(\|(?: *[-:]+[-| :]*)\|)\n((?:\|(?:.*\|)+\n?)*)",
    re.MULTILINE,
)
ITALIC_RE = re.compile(r"(?<!\w)_(.+?)_(?!\w)")
BOLD_RE = re.compile(r"\*\*(.*?)\*\*")
IMAGE_RE = re.compile(r"!\[(.*?)\]\((.*?)\)")
WIKILINK_RE = re.compile(r"\[\[(.*?)\]\]")
EXTERNAL_RE = re.compile(r"\[(.*?)\]\((https?://.*?)\)")
FOOTNOTE_RE = re.compile(r"\[\^(\d+)\]: (.+)")
FOOTNOTE_REF_RE = re.compile(r"\[\^(\d+)\]")
FRONTMATTER_RE = re.compile(r"---\n(.*?)\n---\n(.*)", re.S)


def parse_quotes(md_content: str) -> str:
    try:
        quote_pattern = re.compile(r"^> (.*)", re.MULTILINE)
        author_pattern = re.compile(r"^- (.*)", re.MULTILINE)

        def replace_quote(match):
            return f"<blockquote>{match.group(1)}</blockquote>"

        def replace_author(match):
            return f"<cite>{match.group(1)}</cite>"

        md_content = quote_pattern.sub(replace_quote, md_content)
        md_content = author_pattern.sub(replace_author, md_content)
        return md_content
    except Exception as err:
        logger.error(f"Error parsing quotes: {err}", exc_info=True)
        return md_content


def parse_tables(md_content: str) -> str:
    try:
        def replace_table(match):
            headers = match.group(1).strip().split("|")[1:-1]
            rows = match.group(3).strip().split("\n")
            header_html = "".join(f"<th>{h.strip()}</th>" for h in headers)

            row_html = ""
            for row in rows:
                cells = row.strip().split("|")[1:-1]
                row_html += (
                    "<tr>" + "".join(f"<td>{c.strip()}</td>" for c in cells) + "</tr>"
                )

            return f"""
            <table>
                <thead><tr>{header_html}</tr></thead>
                <tbody>{row_html}</tbody>
            </table>
            """

        return TABLE_RE.sub(replace_table, md_content)
    except Exception as err:
        logger.error(f"Error parsing tables: {err}", exc_info=True)
        return md_content


def parse_italics(md_content: str) -> str:
    try:
        return ITALIC_RE.sub(r"<em>\1</em>", md_content)
    except Exception as err:
        logger.error(f"Error parsing italics: {err}", exc_info=True)
        return md_content


def parse_bold_text(md_content: str) -> str:
    try:
        return BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", md_content)
    except Exception as err:
        logger.error(f"Error parsing bold text: {err}", exc_info=True)
        return md_content


VALID_IMAGE_EXTENSIONS = (
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".webp",
)
VALID_VIDEO_EXTENSIONS = (".mp4",)


def parse_images(
    md_content: str, base_path: str = "../images/", video_base_path: str = "../videos/"
) -> str:
    """
    - `![Alt Text](image.jpg)` for standard images
    - `![Alt Text|100x200](image.jpg)` for resized image (100px width, 200px height)
    - `![Alt Text](video.mp4)` for videos (renders a <video> tag with controls)
    """

    try:
        def replace_image(match):
            alt_text, src = match.groups()

            resize_match = re.search(r"(.*?)\|(\d+)x(\d+)", alt_text)

            if resize_match:
                alt_text = resize_match.group(1).strip()
                width = resize_match.group(2)
                height = resize_match.group(3)
                size_attr = f' width="{width}" height="{height}"'
            else:
                size_attr = ""

            file_ext = os.path.splitext(src)[1].lower()
            return _render_media(
                alt_text=alt_text,
                src=src,
                file_ext=file_ext,
                size_attr=size_attr,
                base_path=base_path,
                video_base_path=video_base_path,
            )

        return IMAGE_RE.sub(replace_image, md_content)
    except Exception as err:
        logger.error(f"Error parsing images: {err}", exc_info=True)
        return md_content


def parse_backlink(source: str, target: str, backlinks: Dict[str, List[str]]) -> None:
    try:
        source_key = (
            os.path.splitext(os.path.basename(source))[0].replace(" ", "-").lower()
        )
        target_key = target.replace(" ", "-").lower()

        if source_key == "index":
            if target_key not in backlinks:
                backlinks[target_key] = []
            if source_key not in backlinks[target_key]:
                backlinks[target_key].append(source_key)
        else:
            if target_key not in backlinks:
                backlinks[target_key] = []
            if source_key not in backlinks[target_key]:
                backlinks[target_key].append(source_key)

        logger.info(f"Backlinks for '{target_key}': {backlinks[target_key]}")
    except Exception as err:
        logger.error(f"Error parsing backlink from '{source}' to '{target}': {err}", exc_info=True)


def parse_wikilinks(
    source_page: str, text: str, backlinks: Dict[str, List[str]]
) -> str:
    try:
        category_cache: Dict[str, str] = {}

        def resolve_category(slug: str) -> str:
            if slug in category_cache:
                return category_cache[slug]
            for folder in ("notes", "articles"):
                if (CONTENT_PATH / folder / f"{slug}.md").exists():
                    category_cache[slug] = folder
                    return folder
            category_cache[slug] = "articles"
            return "articles"

        def replace_link(match):
            link_text = match.group(1)
            slug = link_text.replace(" ", "-").lower()
            category = resolve_category(slug)
            parse_backlink(source_page, link_text, backlinks)
            return f'<a href="/{category}/{slug}.html">{link_text}</a>'

        return WIKILINK_RE.sub(replace_link, text)
    except Exception as err:
        logger.error(f"Error parsing wikilinks in text: {err}", exc_info=True)
        return text


def parse_external_links(text: str) -> str:
    try:
        return EXTERNAL_RE.sub(
            lambda m: f'<a href="{m.group(2)}" target="_blank">{m.group(1)}</a>',
            text,
        )
    except Exception as err:
        logger.error(f"Error parsing external links in text: {err}", exc_info=True)
        return text


def parse_articles(
    md_content: str, page_name: str, backlinks: Dict[str, List[str]]
) -> dict:
    articles = []
    current_article = None
    footnotes = {}
    toc = []

    try:
        processed_content, footnotes = parse_footnotes(md_content)
        processed_content = parse_quotes(processed_content)
        processed_content = parse_images(processed_content)
        processed_content = parse_bold_text(processed_content)
        processed_content = parse_italics(processed_content)
        processed_content = parse_tables(processed_content)

        for line in processed_content.splitlines():
            if line.startswith("## "):
                heading_text = line[3:].strip()
                anchor = _anchor(heading_text)
                toc.append({"text": heading_text, "anchor": anchor, "level": 2})
                line = f'<h2 id="{anchor}">{heading_text}</h2>'

                if current_article:
                    articles.append(current_article)
                current_article = {"header": line, "sections": []}

            elif line.startswith("### "):
                heading_text = line[4:].strip()
                anchor = _anchor(heading_text)
                toc.append({"text": heading_text, "anchor": anchor, "level": 3})
                line = f'<h3 id="{anchor}">{heading_text}</h3>'

                if current_article:
                    current_article["sections"].append(line)

            elif current_article and line.strip():
                processed_line = parse_wikilinks(page_name, line.strip(), backlinks)
                processed_line = parse_external_links(processed_line)
                current_article["sections"].append(processed_line)

        if current_article:
            articles.append(current_article)

    except Exception as err:
        logger.error(f"Error parsing articles: {err}", exc_info=True)

    return {"articles": articles, "footnotes": footnotes, "toc": toc}


def _anchor(text: str) -> str:
    return text.replace(" ", "-").lower()


def _coerce_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value.lower()]
    if isinstance(value, list):
        return [str(v).lower() for v in value if isinstance(v, str)]
    return []


def _render_media(
    alt_text: str,
    src: str,
    file_ext: str,
    size_attr: str,
    base_path: str,
    video_base_path: str,
) -> str:
    if file_ext in VALID_VIDEO_EXTENSIONS:
        video_path = os.path.join(video_base_path, os.path.basename(src))
        return f"""
                <figure class="media-video">
                    <video src="{video_path}" controls{size_attr} aria-label="{alt_text}"></video>
                    <figcaption>{alt_text}</figcaption>
                </figure>
                """

    if file_ext not in VALID_IMAGE_EXTENSIONS:
        return f"<p>[Invalid media format: {src}]</p>"

    image_path = os.path.join(base_path, os.path.basename(src))

    return f"""
            <figure>
                <img src="{image_path}" alt="{alt_text}"{size_attr}>
                <figcaption>{alt_text}</figcaption>
            </figure>
            """


def _stringify_dates(frontmatter: dict, keys: tuple[str, ...]) -> None:
    for key in keys:
        if key in frontmatter and isinstance(frontmatter[key], (datetime, str)):
            frontmatter[key] = str(frontmatter[key])


def parse_frontmatter(md_fp: str) -> Dict[str, Any]:
    try:
        with open(md_fp, "r", encoding="utf-8") as f:
            md_content = f.read()

        frontmatter_match = FRONTMATTER_RE.match(md_content)
        if frontmatter_match:
            frontmatter = yaml.safe_load(frontmatter_match.group(1))
            content = frontmatter_match.group(2).strip()
        else:
            frontmatter = {}
            content = md_content

        _stringify_dates(frontmatter, keys=("created", "last_modified"))

        return {"frontmatter": frontmatter, "content": content}
    except Exception as err:
        logger.error(f"Error parsing frontmatter in file {md_fp}: {err}", exc_info=True)
        return {"frontmatter": {}, "content": ""}


def parse_footnotes(content: str):
    try:
        footnotes = {
            match.group(1): match.group(2)
            for match in FOOTNOTE_RE.finditer(content)
        }
        content = FOOTNOTE_RE.sub("", content)

        def replace_ref(match):
            ref_id = match.group(1)
            return f'<a href="#footnote-{ref_id}" id="ref-{ref_id}" class="footnote-ref">[^{ref_id}]</a>'

        content = FOOTNOTE_REF_RE.sub(replace_ref, content)
        return content.strip(), footnotes
    except Exception as err:
        logger.error(f"Error processing footnotes: {err}", exc_info=True)
        return content, {}


def parse_related(frontmatter: dict) -> list[dict]:
    try:
        related = []
        domain = _coerce_list(frontmatter.get("domain", ""))
        if not domain:
            return related

        logger.info(f"Looking for related articles with Domain: {domain}.")

        for root, _, files in os.walk(content_dir):
            for file in files:
                if file.endswith(".md"):
                    markdown_path = Path(root) / file
                    try:
                        parsed_frontmatter = parse_frontmatter(str(markdown_path))
                        file_frontmatter = parsed_frontmatter.get("frontmatter", {})
                        file_domains = _coerce_list(file_frontmatter.get("domain", ""))

                        if set(domain) & set(file_domains):
                            logger.info(
                                f"Match found for Domain in file: {markdown_path}"
                            )
                            related.append(
                                {
                                    "title": file_frontmatter.get("title", "Untitled"),
                                    "url": markdown_path.relative_to(
                                        CONTENT_PATH
                                    ).with_suffix(".html"),
                                }
                            )
                    except Exception as parse_error:
                        logger.error(
                            f"Error parsing frontmatter for file {markdown_path}: {parse_error}", exc_info=True
                        )

        logger.info(f"Related articles found: {len(related)}")
        return related
    except Exception as general_error:
        logger.error(f"Error in parse_related: {general_error}", exc_info=True)
        return []
