from datetime import datetime
from typing import Tuple
from src.revisions import insert_commit, get_entry_fingerprint, get_latest_commit
from src.markdown_parser import count_body_words
from src.base_utils import setup_logger

logger = setup_logger("commit_flow", "logs/commit_flow.log")


def should_commit(slug: str, fingerprint: str) -> bool:
    try:
        logger.info(
            f"Checking if commit is needed for {slug} with fingerprint {fingerprint}"
        )
        latest_hash = get_entry_fingerprint(slug)
        return latest_hash != fingerprint
    except Exception as err:
        logger.error(f"Error checking commit necessity for {slug}: {err}")
        return False


def _short_hash(fingerprint: str, length: int = 7) -> str:
    return fingerprint[:length] if fingerprint else ""


def prompt_summary(slug: str, fingerprint: str, title: str | None = None) -> str:
    display_hash = _short_hash(fingerprint)
    label = title or slug
    logger.info(f"Prompting summary for {slug} with fingerprint {fingerprint}")
    try:
        summary_val = ""
        while not summary_val.strip():
            summary_val = input(f"Summary for {label} ({display_hash}): ").strip()
        return summary_val
    except Exception as err:
        logger.error(f"Error prompting summary for {slug}: {err}")
        return "update"


def get_summary(
    commit_context: dict | None,
    slug: str,
    fingerprint: str,
    title: str | None = None,
) -> str:
    logger.info(f"Getting summary for {slug} with fingerprint {fingerprint}")
    try:
        if commit_context and commit_context.get("bundle"):
            shared = commit_context.get("shared_summary")
            if shared:
                return shared
            prompt = (
                commit_context.get("summary_prompt")
                or f"Summary for bundle ({fingerprint}): "
            )
            summary_val = ""
            while not summary_val.strip():
                summary_val = input(prompt).strip()
            commit_context["shared_summary"] = summary_val
            return summary_val
        return prompt_summary(slug, fingerprint, title)
    except Exception as err:
        logger.error(f"Error getting summary for {slug}: {err}")
        return "update"


def record_commit(
    slug: str,
    fingerprint: str,
    frontmatter: dict,
    raw_content: str,
    parent_hash: str | None,
    commit_context: dict | None,
) -> Tuple[str, str]:
    logger.info(f"Recording commit for {slug} with fingerprint {fingerprint}")
    try:
        word_count = count_body_words(raw_content)
        summary_val = get_summary(
            commit_context, slug, fingerprint, frontmatter.get("title")
        )
        base_worked = _coerce_hours(frontmatter.get("worked", 0.0), default=0.0)
        latest = get_latest_commit(slug)
        if latest and latest["worked_hours"] is not None:
            base_worked = _coerce_hours(latest["worked_hours"], default=base_worked)
        worked_delta = prompt_worked_delta(frontmatter.get("title") or slug)
        worked_hours = base_worked + worked_delta
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
        return fingerprint, "0d"
    except Exception as err:
        logger.error(f"Error recording commit for {slug}: {err}")
        return fingerprint, "—"


def prompt_worked_delta(label: str) -> float:
    try:
        while True:
            raw = input(
                f"Hours worked since last commit for {label} (blank for 0): "
            ).strip()
            if not raw:
                return 0.0
            try:
                value = float(raw)
            except ValueError:
                continue
            if value < 0:
                continue
            return value
    except Exception as err:
        logger.error(f"Error prompting worked hours for {label}: {err}")
        return 0.0


def _coerce_hours(value, default: float = 0.0) -> float:
    try:
        if isinstance(value, str):
            value = value.strip().lower().rstrip("h")
        return float(value)
    except Exception:
        return default
