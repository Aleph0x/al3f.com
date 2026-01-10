import os
import re
import yaml
import html
from datetime import datetime, date
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
FENCED_CODE_RE = re.compile(r"```([^\n`]*)\n(.*?)```", re.S)
INLINE_CODE_RE = re.compile(r"`([^`]+)`")


def parse_quotes(md_content: str) -> str:
    try:
        lines = md_content.splitlines()
        output = []
        last_was_quote = False

        for line in lines:
            if line.startswith("> "):
                output.append(f"<blockquote>{line[2:]}</blockquote>")
                last_was_quote = True
                continue

            if last_was_quote and line.startswith("- "):
                output.append(f"<cite>{line[2:]}</cite>")
                last_was_quote = False
                continue

            output.append(line)
            last_was_quote = False

        return "\n".join(output)
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
        logger.error(
            f"Error parsing backlink from '{source}' to '{target}': {err}",
            exc_info=True,
        )


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

        # Do not replace wikilinks inside inline code spans!
        segments = re.split(r"(`[^`]*`)", text)
        processed = []
        for seg in segments:
            if seg.startswith("`") and seg.endswith("`"):
                processed.append(seg)
            else:
                processed.append(WIKILINK_RE.sub(replace_link, seg))
        return "".join(processed)
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
    anchor_counts: Dict[str, int] = {}
    list_mode = None
    list_items: List[str] = []

    try:
        processed_content, footnotes = parse_footnotes(md_content)

        # Protect code blocks and inline code so they are not altered by other parsers.
        code_placeholders: Dict[str, str] = {}

        def replace_fenced(match):
            idx = len(code_placeholders)
            placeholder = f"@@CODE_BLOCK_{idx}@@"
            lang = match.group(1).strip() if match.group(1) else ""
            code_html = f'<pre><code class="lang-{lang}">{html.escape(match.group(2))}</code></pre>'
            code_placeholders[placeholder] = code_html
            return placeholder

        def replace_inline(match):
            idx = len(code_placeholders)
            placeholder = f"@@CODE_INLINE_{idx}@@"
            code_html = f"<code>{html.escape(match.group(1))}</code>"
            code_placeholders[placeholder] = code_html
            return placeholder

        processed_content = FENCED_CODE_RE.sub(replace_fenced, processed_content)
        processed_content = INLINE_CODE_RE.sub(replace_inline, processed_content)

        processed_content = parse_quotes(processed_content)
        processed_content = parse_images(processed_content)
        processed_content = parse_bold_text(processed_content)
        processed_content = parse_italics(processed_content)
        processed_content = parse_tables(processed_content)

        def render_inline(text_line: str) -> str:
            processed_line = parse_wikilinks(page_name, text_line, backlinks)
            processed_line = parse_external_links(processed_line)
            for placeholder, html_snippet in code_placeholders.items():
                processed_line = processed_line.replace(placeholder, html_snippet)
            return processed_line

        def flush_list() -> None:
            nonlocal list_mode, list_items
            if not current_article or not list_mode or not list_items:
                list_mode = None
                list_items = []
                return
            items_html = "".join(f"<li>{item}</li>" for item in list_items)
            current_article["sections"].append(f"<{list_mode}>{items_html}</{list_mode}>")
            list_mode = None
            list_items = []

        def unique_anchor(heading_text: str) -> str:
            base = _anchor(heading_text)
            count = anchor_counts.get(base, 0) + 1
            anchor_counts[base] = count
            return base if count == 1 else f"{base}-{count}"

        for line in processed_content.splitlines():
            if line.startswith("## "):
                flush_list()
                heading_text = line[3:].strip()
                anchor = unique_anchor(heading_text)
                toc.append({"text": heading_text, "anchor": anchor, "level": 2})
                line = f'<h2 id="{anchor}">{heading_text}</h2>'

                if current_article:
                    articles.append(current_article)
                current_article = {"header": line, "sections": []}

            elif line.startswith("### "):
                flush_list()
                heading_text = line[4:].strip()
                anchor = unique_anchor(heading_text)
                toc.append({"text": heading_text, "anchor": anchor, "level": 3})
                line = f'<h3 id="{anchor}">{heading_text}</h3>'

                if current_article:
                    current_article["sections"].append(line)

            elif current_article:
                ordered_match = re.match(r"^\s*\d+\.\s+(.*)", line)
                unordered_match = re.match(r"^\s*[-*+]\s+(.*)", line)
                if ordered_match or unordered_match:
                    match = ordered_match or unordered_match
                    if not match:
                        continue
                    item_text = match.group(1).strip()
                    rendered_item = render_inline(item_text)
                    mode = "ol" if ordered_match else "ul"
                    if list_mode and list_mode != mode:
                        flush_list()
                    list_mode = mode
                    list_items.append(rendered_item)
                else:
                    if not line.strip():
                        flush_list()
                        continue
                    if list_mode:
                        flush_list()
                    current_article["sections"].append(render_inline(line.strip()))

            elif current_article and line.strip():
                current_article["sections"].append(render_inline(line.strip()))

        if current_article:
            flush_list()
            articles.append(current_article)

        # Restore any remaining placeholders in headers/sections
        for article in articles:
            if "header" in article:
                for placeholder, html_snippet in code_placeholders.items():
                    article["header"] = article["header"].replace(
                        placeholder, html_snippet
                    )
            if article.get("sections"):
                restored = []
                for sec in article["sections"]:
                    for placeholder, html_snippet in code_placeholders.items():
                        sec = sec.replace(placeholder, html_snippet)
                    restored.append(sec)
                article["sections"] = restored

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
        if key in frontmatter and isinstance(frontmatter[key], (datetime, date, str)):
            frontmatter[key] = str(frontmatter[key])


def parse_frontmatter(md_fp: str) -> Dict[str, Any]:
    try:
        with open(md_fp, "r", encoding="utf-8") as f:
            md_content = f.read()

        frontmatter_match = FRONTMATTER_RE.match(md_content)
        if frontmatter_match:
            try:
                frontmatter = yaml.safe_load(frontmatter_match.group(1)) or {}
            except Exception as load_err:
                logger.error(
                    f"Error loading YAML frontmatter in {md_fp}: {load_err}",
                    exc_info=True,
                )
                frontmatter = {}
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
            match.group(1): match.group(2) for match in FOOTNOTE_RE.finditer(content)
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
                            f"Error parsing frontmatter for file {markdown_path}: {parse_error}",
                            exc_info=True,
                        )

        logger.info(f"Related articles found: {len(related)}")
        return related
    except Exception as general_error:
        logger.error(f"Error in parse_related: {general_error}", exc_info=True)
        return []
