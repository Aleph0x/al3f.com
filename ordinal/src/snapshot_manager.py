import os
import shutil
from datetime import datetime
from typing import Optional
from src.base_utils import setup_logger, ensure_directory, snapshots_dir, public_dir

logger = setup_logger("snapshot_manager", "logs/snapshot_manager.log")


def snapshot_site(public_dir: str, snapshots_dir: str = snapshots_dir) -> None:
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for root, _, files in os.walk(public_dir):
            for file in files:
                if file.endswith(".html"):
                    rel_fp = os.path.relpath(os.path.join(root, file), public_dir)
                    snapshot_fp = os.path.join(snapshots_dir, rel_fp)
                    snapshot_dir = os.path.dirname(snapshot_fp)
                    ensure_directory(snapshot_dir)
                    snapshot_file = f"{os.path.splitext(file)[0]}_{timestamp}.html"
                    shutil.copy2(
                        os.path.join(root, file),
                        os.path.join(snapshot_dir, snapshot_file),
                    )
                    logger.info(
                        f"Snapshot created: {rel_fp} -> {os.path.join(snapshot_dir, snapshot_file)}"
                    )
    except Exception as err:
        logger.error(f"Error creating site snapshot: {err}")


def snapshot_category(public_dir: str, snapshots_dir: str, category: str) -> None:
    try:
        category_dir = os.path.join(public_dir, category)

        if not os.path.exists(category_dir):
            logger.error(
                f"Category `{category}` does not exist in the public directory."
            )
            return

        category_snapshot_dir = os.path.join(snapshots_dir, category)
        ensure_directory(category_snapshot_dir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_count = 0

        for root, _, files in os.walk(category_dir):
            for file in files:
                if file.endswith(".html"):
                    rel_fp = os.path.relpath(os.path.join(root, file), category_dir)
                    snapshot_fp = os.path.join(
                        category_snapshot_dir, f"{rel_fp}_{timestamp}.html"
                    )
                    ensure_directory(os.path.dirname(snapshot_fp))
                    shutil.copy2(os.path.join(root, file), snapshot_fp)
                    logger.info(f"Snapshot created: {rel_fp} -> {snapshot_fp}")
                    snapshot_count += 1

        if snapshot_count == 0:
            logger.warning(f"No HTML files found for category `{category}`.")
        else:
            logger.info(
                f"Snapshot created for {snapshot_count} file(s) in category `{category}`."
            )
    except Exception as err:
        logger.error(f"Error creating snapshot for category `{category}`: {err}")


def restore_site(
    category: Optional[str] = None, snapshot: Optional[str] = None
) -> None:
    try:
        source_dir = (
            os.path.join(snapshots_dir, category) if category else snapshots_dir
        )
        target_dir = os.path.join(public_dir, category) if category else public_dir

        if not os.path.exists(source_dir):
            logger.error(f"Snapshot directory `{source_dir}` does not exist.")
            return

        try:
            snapshots = [
                os.path.join(root, file)
                for root, _, files in os.walk(source_dir)
                for file in files
                if file.endswith(".html")
            ]
        except Exception as err:
            logger.error(f"Error listing snapshots in `{source_dir}`: {err}")
            return

        if not snapshots:
            logger.warning("No snapshots found.")
            return

        if not snapshot:
            print("Available snapshots for restoration:")
            snapshot_dict = {}
            for i, snap in enumerate(snapshots, start=1):
                relative_path = os.path.relpath(snap, source_dir)
                print(f"{i}. {relative_path}")
                snapshot_dict[i] = snap

            try:
                user_input = (
                    input(
                        "Enter the number of the snapshot to restore (or 'cancel' to exit): "
                    )
                    .strip()
                    .lower()
                )

                if user_input == "cancel":
                    logger.info("Snapshot restoration cancelled by user.")
                    return

                selected_index = int(user_input)
                if selected_index not in snapshot_dict:
                    raise ValueError("Invalid selection.")

                snapshot = snapshot_dict[selected_index]
            except (ValueError, KeyError):
                logger.warning("Invalid input. Restoration aborted.")
                return

        if snapshot is None:
            logger.warning("No snapshot selected. Restoration aborted.")
            return

        restored_files = 0
        for file in snapshots:
            if snapshot in file:
                try:
                    rel_fp = os.path.relpath(file, source_dir)
                    restore_fp = os.path.join(
                        target_dir, rel_fp.split("_")[0] + ".html"
                    )
                    ensure_directory(os.path.dirname(restore_fp))
                    shutil.copy2(file, restore_fp)
                    logger.info(f"Restored: {file} -> {restore_fp}")
                    restored_files += 1
                except Exception as err:
                    logger.error(f"Error restoring file `{file}`: {err}")

        if restored_files == 0:
            logger.warning(f"No files restored from snapshot: {snapshot}")
        else:
            logger.info(f"Restored {restored_files} file(s) from snapshot: {snapshot}")
    except Exception as err:
        logger.error(f"Error in restore_site: {err}", exc_info=True)


def cleanup_snapshots(snapshots_dir: str = snapshots_dir) -> None:
    try:
        if not os.path.exists(snapshots_dir):
            print("No snapshots available to delete.")
            logger.warning(
                "Snapshots directory does not exist. No snapshots to delete."
            )
            return

        snapshots = [
            os.path.join(root, file)
            for root, _, files in os.walk(snapshots_dir)
            for file in files
            if file.endswith(".html")
        ]

        if not snapshots:
            print("No snapshots available to delete.")
            logger.info("No snapshots found.")
            return

        print("Available snapshots for deletion:")
        snapshot_dict = {}
        for i, snapshot in enumerate(snapshots, start=1):
            relative_path = os.path.relpath(snapshot, snapshots_dir)
            print(f"{i}. {relative_path}")
            snapshot_dict[i] = snapshot

        user_input = (
            input(
                "Enter the numbers of the snapshots to delete (comma separated), or 'all' to delete all: "
            )
            .strip()
            .lower()
        )

        if user_input == "all":
            confirmation = (
                input("Are you sure you want to delete all snapshots? (yes/no): ")
                .strip()
                .lower()
            )
            if confirmation not in ["yes", "y"]:
                print("Deletion aborted.")
                logger.info("Deletion aborted by user.")
                return

            for snapshot in snapshots:
                try:
                    os.remove(snapshot)
                    logger.info(f"Deleted snapshot: {snapshot}")
                except Exception as err:
                    logger.error(f"Error deleting snapshot `{snapshot}`: {err}")
            print("All snapshots have been deleted.")
        else:
            try:
                indices = [int(x.strip()) for x in user_input.split(",")]
                selected_snapshots = [
                    snapshot_dict[i] for i in indices if i in snapshot_dict
                ]
                if not selected_snapshots:
                    raise ValueError("Invalid selection.")
            except (ValueError, KeyError):
                print("Invalid input. Deletion aborted.")
                logger.warning("Invalid input for snapshot deletion. Aborting.")
                return

            confirmation = (
                input(
                    f"Are you sure you want to delete {len(selected_snapshots)} selected snapshots? (yes/no): "
                )
                .strip()
                .lower()
            )
            if confirmation not in ["yes", "y"]:
                print("Deletion cancelled.")
                logger.info("Deletion cancelled by user.")
                return

            for snapshot in selected_snapshots:
                try:
                    os.remove(snapshot)
                    logger.info(f"Deleted snapshot: {snapshot}")
                except Exception as err:
                    logger.error(f"Error deleting snapshot `{snapshot}`: {err}")
            print(f"{len(selected_snapshots)} snapshots have been deleted.")
    except Exception as err:
        logger.error(f"Error during snapshot deletion: {err}", exc_info=True)


def manage_snapshots(action: str, category: Optional[str] = None) -> None:
    if action == "create":
        if category:
            snapshot_category(public_dir, snapshots_dir, category)
        else:
            snapshot_site(public_dir, snapshots_dir)
    elif action == "restore":
        restore_site(category=category)
    elif action == "delete":
        cleanup_snapshots(snapshots_dir)
    else:
        logger.error(f"Unknown snapshot action: {action}")
