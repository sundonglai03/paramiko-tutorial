"""对远程主机执行相关任务。"""
import argparse
from typing import List

from .files import fetch_local_files
from .server import RemoteClient


def _build_client(
    host: str,
    user: str,
    password: str | None = None,
    ssh_key_filepath: str | None = None,
    remote_path: str = "/tmp",
) -> RemoteClient:
    """创建远程客户端，并要求显式传入所有必要配置。"""
    if not host:
        raise ValueError("host 不能为空。")
    if not user:
        raise ValueError("user 不能为空。")

    return RemoteClient(
        host=host,
        user=user,
        password=password or "",
        ssh_key_filepath=ssh_key_filepath or "",
        remote_path=remote_path,
    )


def upload_directory(
    local_dir: str,
    host: str,
    user: str,
    password: str | None = None,
    ssh_key_filepath: str | None = None,
    remote_path: str = "/tmp",
) -> None:
    """上传本地文件或目录到远程主机：目录按目录上传，文件按文件上传。"""
    client = _build_client(
        host=host,
        user=user,
        password=password,
        ssh_key_filepath=ssh_key_filepath,
        remote_path=remote_path,
    )

    try:
        client.bulk_upload(local_dir)
    finally:
        client.close()


def execute_remote_commands(
    commands: List[str],
    host: str,
    user: str,
    password: str | None = None,
    ssh_key_filepath: str | None = None,
    remote_path: str = "/tmp",
) -> None:
    """在远程主机上执行一组命令。"""
    client = _build_client(
        host=host,
        user=user,
        password=password,
        ssh_key_filepath=ssh_key_filepath,
        remote_path=remote_path,
    )

    try:
        client.execute_commands(commands)
    finally:
        client.close()


def run(argv: List[str] | None = None):
    """使用显式参数的 CLI 入口，完全不依赖配置文件。"""
    args = argv if argv is not None else []
    parser = argparse.ArgumentParser(description="Paramiko remote automation client")

    # 兼容两种常见写法：
    # 1) python main.py execute --host ... --user ... --password ... ls
    # 2) python main.py --host ... --user ... --password ... execute ls
    parser.add_argument("action", nargs="?", choices=["upload", "execute"], help="要执行的动作")
    parser.add_argument("--host", help="远程主机地址")
    parser.add_argument("--user", help="SSH 用户名")
    parser.add_argument("--password", default="", help="SSH 密码，可为空")
    parser.add_argument("--ssh-key-filepath", default="", help="SSH 私钥路径，可为空")
    parser.add_argument("--remote-path", default="/tmp", help="远程上传目录")
    parser.add_argument("target", nargs="?", help="上传目录，或执行命令")

    parsed = parser.parse_args(args)

    # 兼容 action 放在最后的位置：python main.py --host ... --user ... execute ls
    if parsed.action is None and parsed.target is not None:
        if parsed.target in {"upload", "execute"}:
            parsed.action = parsed.target
            parsed.target = None

    if parsed.host is None or parsed.user is None:
        parser.error("--host 和 --user 是必填参数。")

    if parsed.action is None:
        parser.error("必须指定 action：upload 或 execute。")

    if parsed.target is None:
        parser.error("target 是必填参数：上传目录或执行命令。")

    if parsed.action == "upload":
        upload_directory(
            local_dir=parsed.target,
            host=parsed.host,
            user=parsed.user,
            password=parsed.password,
            ssh_key_filepath=parsed.ssh_key_filepath,
            remote_path=parsed.remote_path,
        )
        return

    execute_remote_commands(
        commands=[parsed.target],
        host=parsed.host,
        user=parsed.user,
        password=parsed.password,
        ssh_key_filepath=parsed.ssh_key_filepath,
        remote_path=parsed.remote_path,
    )
