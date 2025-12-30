import os
import shutil
from src.base_utils import content_dir, public_dir, setup_logger, ensure_directory
from src.file_manager import get_categories, generate_missing, merge_image_dir, merge_video_dir
from src.markdown_parser import parse_frontmatter, parse_related, parse_footnotes, parse_articles
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
import subprocess
from collections import defaultdict


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

        for root, _, files in os.walk(static_src):
            for file in files:
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

                title = frontmatter.get("title", file.replace(".md", "").replace("-", " ").title())
                last_modified = frontmatter.get("last_modified", "Unknown")
                domain = frontmatter.get("domain", "Miscellaneous")
                division = frontmatter.get("division", [])
                url = f"/articles/{file.replace('.md', '.html')}"

                categorized_articles[domain].append(
                    {"title": title, "url": url, "last_modified": last_modified, "domain": domain, "division": division}
                )

    return {
        domain: sorted(articles, key=lambda x: x["last_modified"], reverse=True)
        for domain, articles in sorted(categorized_articles.items())
    }


def process_file(md_fp: str, output_fp: str, default_template: str, backlinks: dict) -> None:
    try:
        logger.info(f"Processing file: {md_fp}")

        if os.path.exists(output_fp):
            os.remove(output_fp)
            logger.info(f"Deleted old file: {output_fp}")

        parsed_data = parse_frontmatter(md_fp)
        frontmatter = parsed_data.get("frontmatter", {})
        raw_content = parsed_data.get("content", "")

        logger.info("Parsing footnotes.")
        footnotes_content, footnotes = parse_footnotes(raw_content)

        logger.info("Parsing articles.")
        articles = parse_articles(footnotes_content, os.path.basename(md_fp), backlinks)

        logger.info("Looking for related articles.")
        related = parse_related(frontmatter)

        template_name = frontmatter.get("template", default_template)
        logger.info(f"Using template: {template_name} for {md_fp}")

        context = {
            "title": frontmatter.get("title", "Untitled"),
            "description": frontmatter.get("description", ""),
            "page_meta": [
                {"label": "Domain", "value": frontmatter.get("domain", "N/A")},
                {"label": "Modified", "value": frontmatter.get("last_modified", "N/A")},
                {
                    "label": "Worked",
                    "value": (
                        f"{float(frontmatter['worked'])}h"
                        if "worked" in frontmatter and str(frontmatter["worked"]).replace(".", "", 1).isdigit()
                        else "N/A"
                    ),
                },
                {"label": "Division", "value": ", ".join(frontmatter.get("division", []))},
            ],
            "content": footnotes_content,
            "articles": articles.get("articles", []),
            "footnotes": footnotes,
            "toc": articles["toc"],
            "backlinks": backlinks.get(os.path.splitext(os.path.basename(md_fp))[0], []),
            "external_links": parsed_data.get("external_links", []),
            "related_articles": related,
        }

        if template_name == "section.html":
            context["categorized_articles"] = get_articles_list()

        rendered_html = render_template_context(template_name, context)
        ensure_directory(os.path.dirname(output_fp))
        # logger.info(f"Rendering template with context:\n{json.dumps(context, indent=4)}")
        with open(output_fp, "w", encoding="utf-8") as f:
            f.write(rendered_html)

        logger.info(f"Generated: {output_fp} using template {template_name}")
    except Exception as err:
        logger.error(f"Error processing file {md_fp}: {err}")


def generate_static_site(category="all"):
    try:
        logger.info("Starting site generation.")
        categories = get_categories()
        backlinks = {}

        logger.info("Checking and generating missing markdown files.")
        generate_missing()

        process_index(content_dir, public_dir, backlinks)

        if category == "all":
            for cat in categories:
                process_category(cat, content_dir, public_dir, backlinks)
        else:
            if category in categories:
                process_category(category, content_dir, public_dir, backlinks)
            else:
                logger.error(f"Invalid category: {category}")
        logger.info("Copying all necessary static files.")
        copy_static_files()
        merge_image_dir()
        merge_video_dir()
        compile_scss()

    except Exception as err:
        logger.error(f"Error generating static site: {err}", exc_info=True)


def process_category(category: str, content_dir: str, public_dir: str, backlinks: dict) -> None:
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
                process_file(md_fp, output_fp, default_template, backlinks)
    except Exception as err:
        logger.error(f"Error processing category `{category}`: {err}", exc_info=True)


def process_index(content_dir: str, public_dir: str, backlinks: dict) -> None:
    try:
        logger.info("Processing `index.md`.")
        index_md_fp = os.path.join(content_dir, "index.md")
        index_output_fp = os.path.join(public_dir, "index.html")

        if not os.path.exists(index_md_fp):
            logger.error(f"`index.md` file does not exist at: {index_md_fp}")
            return

        process_file(index_md_fp, index_output_fp, "index.html", backlinks)
        logger.info(f"Processed `index.md` into {index_output_fp}")
    except Exception as err:
        logger.error(f"Error processing `index.md`: {err}")
