"""查找要上传到远程主机的本地文件。"""
from os import path, walk
from typing import List


def fetch_local_files(local_file_dir: str) -> List[str]:
    """
    生成指定文件或目录下所有文件的完整路径列表。

    :param str local_file_dir: 要通过 SCP 上传到远程主机的本地文件或目录。
    :returns: List[str]
    """
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
