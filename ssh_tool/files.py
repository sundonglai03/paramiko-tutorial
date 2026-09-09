"""Utilities for locating local files to upload to remote hosts."""

from os import path, walk
from typing import List


def fetch_local_files(local_file_dir: str) -> List[str]:
    """Generate a list of file paths under the given local directory."""
    if not local_file_dir:
        raise ValueError("local_file_dir 不能为空。")

    if path.isfile(local_file_dir):
        return [local_file_dir]

    if not path.isdir(local_file_dir):
        raise FileNotFoundError(f"未找到本地路径: {local_file_dir}")

    results: List[str] = []
    for root, _, files in walk(local_file_dir):
        for file in files:
            results.append(f"{root}/{file}")
    return results
