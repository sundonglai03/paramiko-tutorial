"""Python-friendly client API for SSH remote tasks."""

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
    port: int = 22,
) -> RemoteClient:
    """Create a remote client with all required connection parameters."""
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
        port=port,
    )


def upload_directory(
    local_dir: str,
    host: str,
    user: str,
    password: str | None = None,
    ssh_key_filepath: str | None = None,
    remote_path: str = "/tmp",
    port: int = 22,
) -> None:
    """Upload a local directory or file to the remote host."""
    client = _build_client(
        host=host,
        user=user,
        password=password,
        ssh_key_filepath=ssh_key_filepath,
        remote_path=remote_path,
        port=port,
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
    port: int = 22,
) -> None:
    """Run a list of commands on the remote host."""
    client = _build_client(
        host=host,
        user=user,
        password=password,
        ssh_key_filepath=ssh_key_filepath,
        remote_path=remote_path,
        port=port,
    )

    try:
        client.execute_commands(commands)
    finally:
        client.close()


def run(argv: List[str] | None = None):
    """CLI entrypoint compatible with either explicit action style."""
    args = argv if argv is not None else []
    parser = argparse.ArgumentParser(description="MCP SSH remote automation client")

    parser.add_argument("action", nargs="?", choices=["upload", "execute"], help="要执行的动作")
    parser.add_argument("--host", help="远程主机地址")
    parser.add_argument("--user", help="SSH 用户名")
    parser.add_argument("--password", default="", help="SSH 密码，可为空")
    parser.add_argument("--ssh-key-filepath", default="", help="SSH 私钥路径，可为空")
    parser.add_argument("--remote-path", default="/tmp", help="远程上传目录")
    parser.add_argument("--port", type=int, default=22, help="SSH 端口，默认 22")
    parser.add_argument("target", nargs="?", help="上传目录，或执行命令")

    parsed = parser.parse_args(args)

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
            port=parsed.port,
        )
        return

    execute_remote_commands(
        commands=[parsed.target],
        host=parsed.host,
        user=parsed.user,
        password=parsed.password,
        ssh_key_filepath=parsed.ssh_key_filepath,
        remote_path=parsed.remote_path,
        port=parsed.port,
    )
