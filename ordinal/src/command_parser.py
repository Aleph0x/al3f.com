from src.file_manager import setup_project, cleanup_orphans, get_categories
from src.html_renderer import generate_static_site
from src.snapshot_manager import manage_snapshots
from src.base_utils import setup_logger

logger = setup_logger("command_parser", "logs/command_parser.log")


def parse_commands(parser):
    logger.info("Setting up commands.")

    categories = get_categories()
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser("setup", help="Set up project directories.")
    setup_parser.set_defaults(func=lambda args: setup_project())

    generate_parser = subparsers.add_parser("generate", help="Generate static site.")
    generate_parser.add_argument(
        "--category", choices=categories + ["all"], default="all", help="Category to generate."
    )
    generate_parser.add_argument(
        "--commit", action="store_true", help="Record acknowledged changes to the revisions database."
    )
    generate_parser.add_argument(
        "--commit-all",
        action="store_true",
        help="Bundle all detected changes under a single shared summary.",
    )
    generate_parser.add_argument(
        "--summary",
        type=str,
        default=None,
        help="Optional summary to use for commits (shared when --commit-all is set).",
    )
    generate_parser.set_defaults(
        func=lambda args: generate_static_site(args.category, args.commit, args.commit_all, args.summary)
    )

    cleanup_parser = subparsers.add_parser("cleanup", help="Remove orphaned files.")
    cleanup_parser.set_defaults(func=lambda args: cleanup_orphans())

    snapshot_parser = subparsers.add_parser("snapshot", help="Manage snapshots.")
    snapshot_parser.add_argument(
        "--action",
        choices=["create", "restore", "delete"],
        required=True,
        help="Action to perform.",
    )
    snapshot_parser.add_argument("--category", type=str, help="Category for snapshots.")
    snapshot_parser.set_defaults(func=lambda args: manage_snapshots(args.action, args.category))
