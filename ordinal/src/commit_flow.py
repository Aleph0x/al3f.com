from datetime import datetime
from typing import Tuple
from src.revisions import insert_commit, get_latest_commit
from src.base_utils import setup_logger

logger = setup_logger("commit_flow", "logs/commit_flow.log")


def should_commit(slug: str, fingerprint: str) -> bool:
    logger.info(
        f"Checking if commit is needed for {slug} with fingerprint {fingerprint}"
    )
    try:
        logger.info(
            f"Checking if commit is needed for {slug} with fingerprint {fingerprint}"
        )
        latest = get_latest_commit(slug)
        latest_hash = latest["last_hash"] if latest else None
        return latest_hash != fingerprint
    except Exception as err:
        logger.error(f"Error checking commit necessity for {slug}: {err}")
        return False


def prompt_summary(slug: str, fingerprint: str) -> str:
    logger.info(f"Prompting summary for {slug} with fingerprint {fingerprint}")
    try:
        summary_val = ""
        while not summary_val.strip():
            summary_val = input(f"Summary for {slug} ({fingerprint}): ").strip()
        return summary_val
    except Exception as err:
        logger.error(f"Error prompting summary for {slug}: {err}")
        return "update"


def get_summary(commit_context: dict | None, slug: str, fingerprint: str) -> str:
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
        return prompt_summary(slug, fingerprint)
    except Exception as err:
        logger.error(f"Error getting summary for {slug}: {err}")
        return "update"


def record_commit(
    slug: str,
    fingerprint: str,
    frontmatter: dict,
    raw_content: str,
    worked_hours: float,
    parent_hash: str | None,
    commit_context: dict | None,
) -> Tuple[str, str]:
    logger.info(f"Recording commit for {slug} with fingerprint {fingerprint}")
    try:
        word_count = sum(1 for _ in raw_content.split())
        summary_val = get_summary(commit_context, slug, fingerprint)
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
