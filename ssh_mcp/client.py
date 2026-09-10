"""Python-friendly client API for SSH remote tasks.

Connection details are explicit arguments, with a name looked up in the
credential cache as a fallback (see :mod:`ssh_mcp.config`). A call that
connects successfully is remembered, so the next call may name the machine
instead of repeating the credentials.
"""

import argparse
import sys
from typing import List

from .config import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_REMOTE_PATH,
    DEFAULT_TIMEOUT,
    ConnectionSettings,
    resolve_connection,
)
from .credentials import CredentialError, describe, forget, remember
from .log import LOGGER
from .server import RemoteClient


def _build_client(
    name: str | None = None,
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    ssh_key_filepath: str | None = None,
    remote_path: str | None = None,
    port: int | None = None,
    timeout: float | None = None,
    connect_timeout: float | None = None,
) -> tuple[RemoteClient, ConnectionSettings]:
    """Create a remote client from the connection arguments the caller passed.

    ``name`` is consulted only where the explicit arguments leave a gap.
    """
    settings = resolve_connection(
        host=host,
        user=user,
        password=password,
        ssh_key_filepath=ssh_key_filepath,
        port=port,
        timeout=timeout,
        connect_timeout=connect_timeout,
        remote_path=remote_path,
        name=name,
    )

    client = RemoteClient(
        host=settings.host,
        user=settings.user,
        password=settings.password,
        ssh_key_filepath=settings.ssh_key_filepath,
        remote_path=settings.remote_path,
        port=settings.port,
        connect_timeout=settings.connect_timeout,
    )
    return client, settings


def _remember_success(settings: ConnectionSettings, alias: str | None = None) -> None:
    """Cache a destination that just connected successfully.

    Only the caller's explicit ``alias`` is stored. The ``name`` a call was
    addressed by is deliberately *not* promoted to an alias: a lookup that
    matched by host fragment (say ``"192.168.11"``) would otherwise be pinned
    into the cache forever and clutter ``ssh_list_hosts``.

    Called only after a call succeeded, so a failed authentication never gets
    written. A cache write failure is logged and swallowed: the command already
    ran, and losing it because bookkeeping failed would be worse.
    """
    aliases = [alias] if alias and alias.strip() else []
    try:
        remember(
            host=settings.host,
            user=settings.user,
            password=settings.password,
            ssh_key_filepath=settings.ssh_key_filepath,
            port=settings.port,
            aliases=aliases,
        )
    except CredentialError as exc:
        LOGGER.warning(f"凭据缓存写入失败（不影响本次结果）：{exc}")


def upload_directory(
    local_dir: str,
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    ssh_key_filepath: str | None = None,
    remote_path: str | None = None,
    port: int | None = None,
    connect_timeout: float | None = None,
    name: str | None = None,
    alias: str | None = None,
) -> str:
    """Upload a local directory or file into a remote directory."""
    client, settings = _build_client(
        name=name,
        host=host,
        user=user,
        password=password,
        ssh_key_filepath=ssh_key_filepath,
        remote_path=remote_path,
        port=port,
        connect_timeout=connect_timeout,
    )

    try:
        client.bulk_upload(local_dir)
    finally:
        client.close()

    _remember_success(settings, alias)
    return f"Upload completed: {local_dir} -> {settings.remote_path}"


def download_file(
    remote_file: str,
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    ssh_key_filepath: str | None = None,
    local_path: str | None = None,
    port: int | None = None,
    connect_timeout: float | None = None,
    name: str | None = None,
    alias: str | None = None,
) -> str:
    """Download a single file from the remote host to a local path."""
    client, settings = _build_client(
        name=name,
        host=host,
        user=user,
        password=password,
        ssh_key_filepath=ssh_key_filepath,
        port=port,
        connect_timeout=connect_timeout,
    )

    try:
        saved_path = client.download_file(remote_file, local_path=local_path)
    finally:
        client.close()

    _remember_success(settings, alias)
    return f"Download completed: {remote_file} -> {saved_path}"


def execute_remote_commands(
    commands: List[str],
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    ssh_key_filepath: str | None = None,
    port: int | None = None,
    timeout: float | None = None,
    connect_timeout: float | None = None,
    name: str | None = None,
    alias: str | None = None,
) -> str:
    """Run a list of commands on the remote host and return stdout/stderr."""
    client, settings = _build_client(
        name=name,
        host=host,
        user=user,
        password=password,
        ssh_key_filepath=ssh_key_filepath,
        port=port,
        timeout=timeout,
        connect_timeout=connect_timeout,
    )

    try:
        result = client.execute_commands(commands, timeout=settings.timeout)
    finally:
        client.close()

    _remember_success(settings, alias)
    return result


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI argument parser shared by the console scripts."""
    parser = argparse.ArgumentParser(
        prog="ssh-mcp",
        description=(
            "SSH / SCP remote automation. Either pass --host and --user with "
            "--password or --ssh-key-filepath, or pass --name for a machine this "
            "tool connected to successfully before. --list-hosts shows what is "
            "cached, --forget drops an entry. Connection details never come from "
            "the environment. Use --timeout for long-running commands and "
            "--connect-timeout for slow links; they are independent."
        ),
    )

    parser.add_argument("action", nargs="?", choices=["upload", "execute", "download"], help="要执行的动作")
    parser.add_argument("--host", help="远程主机地址（与 --name 二选一）")
    parser.add_argument("--user", help="SSH 用户名（与 --name 二选一）")
    parser.add_argument("--password", default=None, help="SSH 密码；与 --ssh-key-filepath 至少给一个")
    parser.add_argument(
        "--ssh-key-filepath", default=None, help="SSH 私钥路径；与 --password 至少给一个"
    )
    parser.add_argument("--name", default=None, help="已成功连接过的机器名/别名/IP 片段")
    parser.add_argument("--alias", default=None, help="给这次连接的机器起个称呼，成功后一并记住")
    parser.add_argument("--list-hosts", action="store_true", help="列出已缓存的机器并退出")
    parser.add_argument(
        "--forget", default=None, help="删除某个已缓存的机器并退出；名字命中多台会报错，且一台都不删"
    )
    parser.add_argument(
        "--remote-path", default=None, help=f"远程上传目录，默认 {DEFAULT_REMOTE_PATH}"
    )
    parser.add_argument("--local-path", default=None, help="下载文件到本地路径，可为空")
    parser.add_argument("--port", type=int, default=None, help="SSH 端口，默认 22")
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help=f"单条命令的执行超时秒数（默认 {DEFAULT_TIMEOUT:g}），超时返回退出码 124",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=None,
        help=f"建立连接的超时秒数（默认 {DEFAULT_CONNECT_TIMEOUT:g}），与 --timeout 互不影响",
    )
    parser.add_argument("--version", action="store_true", help="打印版本号并退出")
    parser.add_argument("target", nargs="?", help="上传目录，执行命令，或远程文件路径")

    return parser


def run(argv: List[str] | None = None) -> int:
    """CLI entrypoint. Returns a process exit code."""
    parser = build_parser()
    parsed = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if parsed.version:
        from . import __version__

        print(f"ssh-mcp {__version__}")
        return 0

    try:
        return _dispatch(parser, parsed)
    except (CredentialError, ValueError) as exc:
        # Connection/credential problems are user-facing, not stack traces.
        print(f"ssh-mcp: {exc}", file=sys.stderr)
        return 1


def _dispatch(parser: argparse.ArgumentParser, parsed: argparse.Namespace) -> int:
    """Run the action described by parsed arguments. Returns an exit code."""
    if parsed.list_hosts:
        print(describe())
        return 0

    if parsed.forget:
        removed = forget(parsed.forget)
        print(
            f"已删除 {removed.summary()}"
            if removed
            else f"缓存里没有匹配 {parsed.forget!r} 的机器。"
        )
        return 0

    if parsed.action is None and parsed.target in {"upload", "execute", "download"}:
        parsed.action = parsed.target
        parsed.target = None

    if parsed.action is None:
        parser.error("必须指定 action：upload、execute 或 download。")

    if not parsed.name and not (parsed.host and parsed.user):
        parser.error("必须提供 --host 和 --user（首次连接），或用 --name 指定一台已缓存的机器。")

    if parsed.target is None:
        parser.error("target 是必填参数：上传目录、执行命令或远程文件路径。")

    if parsed.action == "upload":
        upload_directory(
            local_dir=parsed.target,
            host=parsed.host,
            user=parsed.user,
            password=parsed.password,
            ssh_key_filepath=parsed.ssh_key_filepath,
            remote_path=parsed.remote_path,
            port=parsed.port,
            connect_timeout=parsed.connect_timeout,
            name=parsed.name,
            alias=parsed.alias,
        )
        return 0

    if parsed.action == "download":
        download_file(
            remote_file=parsed.target,
            host=parsed.host,
            user=parsed.user,
            password=parsed.password,
            ssh_key_filepath=parsed.ssh_key_filepath,
            local_path=parsed.local_path,
            port=parsed.port,
            connect_timeout=parsed.connect_timeout,
            name=parsed.name,
            alias=parsed.alias,
        )
        return 0

    result = execute_remote_commands(
        commands=[parsed.target],
        host=parsed.host,
        user=parsed.user,
        password=parsed.password,
        ssh_key_filepath=parsed.ssh_key_filepath,
        port=parsed.port,
        timeout=parsed.timeout,
        connect_timeout=parsed.connect_timeout,
        name=parsed.name,
        alias=parsed.alias,
    )
    if result:
        print(result)
    return 0
