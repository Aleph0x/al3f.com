import os
import logging
from jinja2 import Environment, FileSystemLoader

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
content_dir = os.path.join(base_dir, "content")
templates_dir = os.path.join(base_dir, "src", "templates")
public_dir = os.path.join(base_dir, "public")
snapshots_dir = os.path.join(base_dir, "snapshots")
logs_dir = os.path.join(base_dir, "logs")
os.makedirs(logs_dir, exist_ok=True)


def setup_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)

    file_handler = None
    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    except Exception:
        # Fallback to console-only if file logging is not writable
        file_handler = None

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    if not logger.hasHandlers():
        if file_handler:
            logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


logger = setup_logger("base_utils", os.path.join(logs_dir, "base_utils.log"))

env = Environment(loader=FileSystemLoader(templates_dir))


def ensure_directory(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as err:
        logger.error(f"Error ensuring directory {path}: {err}")
