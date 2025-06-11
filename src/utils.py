from __future__ import annotations

import datetime
import logging
import os
from datetime import datetime as datetime_class
from datetime import tzinfo
from pathlib import Path

import regex as re

LOGGER = logging.getLogger(__name__)


def get_matching_files_from_folder(
    folder: Path | str,
    file_matching_pattern: str,
    ignore_names: list[str] | None = None,
) -> list[Path]:
    """
    Retrieves a list of files from a specified folder that match a given pattern.

    This function is designed to work consistently in both regular Python environments
    and PyInstaller frozen environments.
    """
    LOGGER.debug(f"Getting matching files from folder: {folder} with pattern: {file_matching_pattern}")
    if not ignore_names:
        ignore_names = []

    folder_path = Path(folder) if isinstance(folder, str) else folder

    try:
        all_files = list(folder_path.rglob("*"))

        matching_files = []
        for f in all_files:
            if not f.is_file():
                continue

            if any(ignored in str(f) for ignored in ignore_names):
                continue

            try:
                if re.search(file_matching_pattern, str(f.name)):
                    matching_files.append(f)
            except re.error:
                file_name = str(f.name).lower()
                pattern = file_matching_pattern.lower()

                if (
                    ("raw" in pattern and "raw" in file_name)
                    or ("survey" in pattern and "survey" in file_name)
                    or ("iossensor" in pattern and "iossensor" in file_name)
                    or ("preprocessed" in pattern and "preprocessed" in file_name)
                    or ("time use diary" in pattern and "time use diary" in file_name)
                    or (pattern.endswith(".csv") and file_name.endswith(".csv"))
                ):
                    matching_files.append(f)

    except Exception as e:
        LOGGER.exception(f"Error while searching for files: {e}")
        matching_files = []
        for root, _, files in os.walk(str(folder_path)):
            for file in files:
                f = Path(root) / file
                if any(ignored in str(f) for ignored in ignore_names):
                    continue

                try:
                    if re.search(file_matching_pattern, file):
                        matching_files.append(f)
                except re.error:
                    if file_matching_pattern.replace(r"[\s\S]*", "").lower() in file.lower():
                        matching_files.append(f)

    LOGGER.debug(f"Found {len(matching_files)} matching files")
    return matching_files


def get_local_timezone() -> tzinfo | None:
    """
    Retrieves the local timezone of the system.
    """
    return datetime_class.now(datetime.timezone.utc).astimezone().tzinfo
