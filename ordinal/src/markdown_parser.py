import os
import re
import yaml
from datetime import datetime
from typing import List, Dict, Any
from src.base_utils import setup_logger, ensure_directory, content_dir

logger = setup_logger("markdown_parser", "logs/markdown_parser.log")


def parse_quotes(md_content: str) -> str:
    quote_pattern = re.compile(r"^> (.*)", re.MULTILINE)
    author_pattern = re.compile(r"^- (.*)", re.MULTILINE)

    def replace_quote(match):
        return f"<blockquote>{match.group(1)}</blockquote>"

    def replace_author(match):
        return f"<cite>{match.group(1)}</cite>"

    md_content = quote_pattern.sub(replace_quote, md_content)
    md_content = author_pattern.sub(replace_author, md_content)

    return md_content


def parse_tables(md_content: str) -> str:
    table_pattern = re.compile(
        r"^(\|(?:.*\|)+)\n(\|(?: *[-:]+[-| :]*)\|)\n((?:\|(?:.*\|)+\n?)*)",
        re.MULTILINE,
    )

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

    return table_pattern.sub(replace_table, md_content)


def parse_italics(md_content: str) -> str:
    italic_pattern = r"(?<!\w)_(.+?)_(?!\w)"
    return re.sub(italic_pattern, r"<em>\1</em>", md_content)


def parse_bold_text(md_content: str) -> str:
    bold_pattern = r"\*\*(.*?)\*\*"

    def replace_bold(match):
        bold_text = match.group(1)
        return f"<strong>{bold_text}</strong>"

    return re.sub(bold_pattern, replace_bold, md_content)


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

    image_pattern = re.compile(r"!\[(.*?)\]\((.*?)\)")

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

    return re.sub(image_pattern, replace_image, md_content)


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
        logger.error(f"Error parsing backlink from '{source}' to '{target}': {err}")


def parse_wikilinks(
    source_page: str, text: str, backlinks: Dict[str, List[str]]
) -> str:
    try:
        pattern = r"\[\[(.*?)\]\]"

        def replace_link(match):
            link_text = match.group(1)
            slug = link_text.replace(" ", "-").lower()

            category = "articles"
            for folder in ["notes", "articles"]:
                if os.path.exists(os.path.join(content_dir, folder, f"{slug}.md")):
                    category = folder
                    break

            logger.info(
                f"Backlinks source: {source_page}, link text: {link_text}, resolved to category: {category}"
            )
            parse_backlink(source_page, link_text, backlinks)

            return f'<a href="/{category}/{slug}.html">{link_text}</a>'

        return re.sub(pattern, replace_link, text)
    except Exception as err:
        logger.error(f"Error parsing wikilinks in text: {err}")
        return text


def parse_external_links(text: str) -> str:
    try:
        pattern = r"\[(.*?)\]\((https?://.*?)\)"

        def replace_link(match):
            link_text = match.group(1)
            url = match.group(2)
            return f'<a href="{url}" target="_blank">{link_text}</a>'

        return re.sub(pattern, replace_link, text)
    except Exception as err:
        logger.error(f"Error parsing external links in text: {err}")
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

        for line in processed_content.split("\n"):
            if line.startswith("## "):
                heading_text = line[3:].strip()
                anchor = heading_text.replace(" ", "-").lower()
                toc.append({"text": heading_text, "anchor": anchor, "level": 2})
                line = f'<h2 id="{anchor}">{heading_text}</h2>'

                if current_article:
                    articles.append(current_article)
                current_article = {"header": line, "sections": []}

            elif line.startswith("### "):
                heading_text = line[4:].strip()
                anchor = heading_text.replace(" ", "-").lower()
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
        logger.error(f"Error parsing articles: {err}")

    return {"articles": articles, "footnotes": footnotes, "toc": toc}


def parse_frontmatter(md_fp: str) -> Dict[str, Any]:
    try:
        with open(md_fp, "r", encoding="utf-8") as f:
            md_content = f.read()

        frontmatter_match = re.match(r"---\n(.*?)\n---\n(.*)", md_content, re.S)
        if frontmatter_match:
            frontmatter = yaml.safe_load(frontmatter_match.group(1))
            content = frontmatter_match.group(2).strip()
        else:
            frontmatter = {}
            content = md_content

        for key in ["created", "last_modified"]:
            if key in frontmatter and isinstance(frontmatter[key], (datetime, str)):
                frontmatter[key] = str(frontmatter[key])

        return {"frontmatter": frontmatter, "content": content}
    except Exception as err:
        logger.error(f"Error parsing frontmatter in file {md_fp}: {err}")
        return {"frontmatter": {}, "content": ""}


def parse_footnotes(content: str):
    try:
        logger.info("Starting to extract footnotes.")

        footnote_pattern = re.compile(r"\[\^(\d+)\]: (.+)")
        footnotes = {
            match.group(1): match.group(2)
            for match in footnote_pattern.finditer(content)
        }
        logger.info(f"Extracted footnotes: {footnotes}")

        content = footnote_pattern.sub("", content)

        footnote_ref_pattern = re.compile(r"\[\^(\d+)\]")

        def replace_ref(match):
            ref_id = match.group(1)
            return f'<a href="#footnote-{ref_id}" id="ref-{ref_id}" class="footnote-ref">[^{ref_id}]</a>'

        content = footnote_ref_pattern.sub(replace_ref, content)
        logger.info("Replaced inline footnote references.")

        return content.strip(), footnotes
    except Exception as err:
        logger.error(f"Error processing footnotes: {err}")
        return content, {}


def parse_related(frontmatter: dict) -> list[dict]:
    try:
        related = []
        domain = frontmatter.get("domain", "")

        if isinstance(domain, str):
            domain = [domain]
        elif not isinstance(domain, list):
            domain = []

        domain = [d.lower() for d in domain if isinstance(d, str)]

        logger.info(f"Looking for related articles with Domain: {domain}.")

        for root, _, files in os.walk(content_dir):
            for file in files:
                if file.endswith(".md"):
                    markdown_path = os.path.join(root, file)
                    try:
                        parsed_frontmatter = parse_frontmatter(markdown_path)
                        file_frontmatter = parsed_frontmatter.get("frontmatter", {})
                        file_domains = file_frontmatter.get("domain", "")

                        if isinstance(file_domains, str):
                            file_domains = [file_domains]
                        elif not isinstance(file_domains, list):
                            file_domains = []

                        file_domains = [
                            dom.lower() for dom in file_domains if isinstance(dom, str)
                        ]

                        if set(domain) & set(file_domains):
                            logger.info(
                                f"Match found for Domain in file: {markdown_path}"
                            )
                            related.append(
                                {
                                    "title": file_frontmatter.get("title", "Untitled"),
                                    "url": markdown_path.replace(
                                        content_dir, ""
                                    ).replace(".md", ".html"),
                                }
                            )
                    except Exception as parse_error:
                        logger.error(
                            f"Error parsing frontmatter for file {markdown_path}: {parse_error}"
                        )

        logger.info(f"Related articles found: {len(related)}")
        return related
    except Exception as general_error:
        logger.error(f"Error in parse_related: {general_error}", exc_info=True)
        return []
