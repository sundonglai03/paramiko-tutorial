"""MCP server wrapper for SSH operations.

Registers real MCP tools for command execution, directory upload and file
download while keeping the plain Python API available from the same package.

Design rules:

* **Errors are raised, not returned.** The MCP SDK turns a raised exception
  into ``CallToolResult(isError=True)``, so the calling model can tell that a
  call failed instead of reading a success wrapper around an error string.
  Failures are raised as :class:`~mcp.server.mcpserver.exceptions.ToolError`
  on purpose: the SDK replaces *any other* exception with
  ``UnexpectedToolError``, whose message is only ``Error executing tool <name>``
  and which withholds the original text from the client. See
  :func:`_describe_error`.
* **A call is either fully explicit or names a known machine.** Pass
  ``host`` + ``user`` (+ ``password`` / ``ssh_key_filepath``) to reach any box
  with no state at all, or pass ``name`` for a machine this tool already
  connected to successfully -- the user's own way of referring to it, such as
  ``"223"``. Explicit arguments always win over the cache.
* **Success is what earns a cache entry.** Nothing is stored until a call
  actually connects, so a wrong password is never remembered, and an ambiguous
  name is refused with the candidate list rather than guessed. See
  :mod:`ssh_mcp.credentials`.
* **Two independent timeouts.** ``timeout`` bounds a single command and reports
  exit code 124 with the output produced so far, so an overrunning command never
  raises. ``connect_timeout`` bounds the socket plus SSH handshake and does fail
  the call. A raised ``SocketTimeout`` therefore always points at the connection
  phase, which is why :func:`_describe_error` names ``connect_timeout`` there.
* **Every parameter is documented in the published schema.** The annotations
  below are what a calling model sees in ``tools/list``; keeping them on the
  signature is what stops callers from guessing at semantics such as
  ``fail_on_error``.
"""

from __future__ import annotations

import socket
from typing import Annotated, NoReturn

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from paramiko.ssh_exception import (
    AuthenticationException,
    NoValidConnectionsError,
    SSHException,
)
from pydantic import Field
from scp import SCPException

from . import __version__
from .client import download_file, execute_remote_commands, upload_directory
from .config import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_PORT,
    DEFAULT_REMOTE_PATH,
    DEFAULT_TIMEOUT,
)
from .credentials import CredentialError, describe, forget

server = MCPServer("ssh-mcp", version=__version__)


def _seconds(value: float) -> str:
    """Render a duration for a human, without a trailing ``.0``."""
    return f"{value:g}"


def _oserror_text(exc: OSError) -> str:
    """Render an ``OSError`` without the useless ``[Errno None]`` wrapper.

    ``OSError(None, "boom")`` -- the shape several libraries use to raise a
    plain message through an ``OSError`` subclass -- stringifies to
    ``[Errno None] boom``. The ``None`` is noise the caller cannot act on, so
    it is dropped and the message kept.
    """
    if exc.errno is None and exc.strerror:
        return exc.strerror
    return str(exc)


CONNECTION_ARGS = (
    "连接目标二选一：传 host + user（可选 password / ssh_key_filepath / port），"
    "或传 name 指定一台此前成功连接过的机器（如 \"223\"）。显式参数优先于 name。"
)

HostArg = Annotated[
    str | None,
    Field(description="远程主机地址。与 user 一起给出即直接连接，可不传 name。"),
]
UserArg = Annotated[
    str | None,
    Field(description="SSH 用户名。与 host 一起给出，或用 name 指向已缓存的机器。"),
]
PasswordArg = Annotated[
    str | None,
    Field(
        description=(
            "SSH 密码。与 ssh_key_filepath 至少给一个；"
            "都不给则回退到 ssh-agent / ~/.ssh 默认密钥。"
        )
    ),
]
KeyArg = Annotated[
    str | None,
    Field(description="SSH 私钥文件路径。与 password 至少给一个。"),
]
PortArg = Annotated[int | None, Field(description=f"SSH 端口，默认 {DEFAULT_PORT}。")]
TimeoutArg = Annotated[
    float | None,
    Field(
        description=(
            f"单条命令的执行超时秒数，默认 {_seconds(DEFAULT_TIMEOUT)}。超时不算异常："
            "返回退出码 124 并保留命令已产生的输出。"
        )
    ),
]
ConnectTimeoutArg = Annotated[
    float | None,
    Field(
        description=(
            f"建立连接（TCP + SSH 握手）的超时秒数，默认 {_seconds(DEFAULT_CONNECT_TIMEOUT)}。"
            "主机连不上 / 网络慢时调这个；调 timeout 对连接阶段无效。"
        )
    ),
]
NameArg = Annotated[
    str | None,
    Field(
        description=(
            "已成功连接过的机器的别名、host 或 host 片段，如 \"223\"。"
            "命中多台会报错并列出候选，不会替你猜。"
        )
    ),
]
AliasArg = Annotated[
    str | None,
    Field(
        description=(
            "给这次连接的机器记一个称呼（如 \"223\"），连接成功后写入凭据缓存，"
            "下次即可用 name 调用。只记录这里显式给的值。"
        )
    ),
]


def _describe_error(exc: BaseException) -> str:
    """Turn a low-level SSH/SCP failure into one readable diagnostic line.

    Subclasses are checked before their bases: ``socket.gaierror``,
    ``ConnectionRefusedError`` and ``FileNotFoundError`` are all ``OSError``,
    and ``socket.timeout`` is an alias of ``TimeoutError``.
    """
    if isinstance(exc, AuthenticationException):
        return (
            f"SSH 认证失败（{exc}）。"
            "请检查本次调用传入的 user / password / ssh_key_filepath 参数。"
        )
    if isinstance(exc, SSHException):
        return f"SSH 连接或协议错误（{type(exc).__name__}：{exc}）。"
    if isinstance(exc, TimeoutError):  # socket.timeout is an alias of TimeoutError
        # A command that overruns its own budget is reported as exit code 124
        # rather than raised, so arriving here means the *connection* phase ran
        # out of time. The knob that helps is connect_timeout, not timeout --
        # saying otherwise sends the caller after a parameter that cannot help.
        return (
            f"连接超时（{exc}）。请确认主机可达、端口开放、路由通畅；"
            f"链路确实慢时可加大 connect_timeout 参数（默认 {_seconds(DEFAULT_CONNECT_TIMEOUT)} 秒）。"
        )
    if isinstance(exc, socket.gaierror):
        return f"主机名无法解析（{exc}）。请检查 host 参数是否正确。"
    if isinstance(exc, ConnectionRefusedError):
        return f"连接被拒绝（{exc}）。请确认目标主机 SSH 端口已开放、port 参数正确。"
    if isinstance(exc, NoValidConnectionsError):
        # Subclasses socket.error, not SSHException, so it needs its own branch.
        return f"无法建立 SSH 连接（{exc}）。请确认主机在线、端口开放、防火墙已放行。"
    if isinstance(exc, FileNotFoundError):
        return f"本地路径不存在（{_oserror_text(exc)}）。"
    if isinstance(exc, NotADirectoryError):
        return f"路径存在但不是目录（{_oserror_text(exc)}）。"
    if isinstance(exc, IsADirectoryError):
        return f"目标是目录而非文件（{_oserror_text(exc)}）。下载只支持单个文件。"
    if isinstance(exc, PermissionError):
        return f"权限不足（{_oserror_text(exc)}）。请检查本地目录写权限或远端路径读权限。"
    if isinstance(exc, OSError):
        return f"网络或文件系统错误（{type(exc).__name__}：{_oserror_text(exc)}）。"
    if isinstance(exc, SCPException):
        return (
            f"SCP 传输失败（{exc}）。"
            "常见原因：远端文件不存在、路径无权限，或目标是目录。"
        )
    if isinstance(exc, ValueError):
        if isinstance(exc, CredentialError):
            # No brackets around {exc}: a credential message carries its own
            # parenthesised detail (the candidate list), so wrapping it again
            # nests brackets and turns one line into a stack.
            return f"凭据缓存问题：{exc}\n可用 ssh_list_hosts 查看已缓存的机器。"
        return f"参数或配置错误（{exc}）。"
    return f"{type(exc).__name__}: {exc}"


def _raise_tool_error(exc: BaseException, action: str) -> NoReturn:
    """Re-raise a failure as ``ToolError`` so its message reaches the client.

    The ``action`` prefix is skipped for credential problems: those messages
    already start with "凭据缓存问题", so prefixing them yields the stutter
    "删除凭据缓存失败：凭据缓存问题：…".
    """
    detail = _describe_error(exc)
    if isinstance(exc, CredentialError):
        raise ToolError(detail) from exc
    raise ToolError(f"{action}失败：{detail}") from exc


@server.tool(
    name="ssh_execute_command",
    description=(
        "Run a command on a remote SSH host and return its stdout/stderr output. "
        + CONNECTION_ARGS
    ),
)
def ssh_execute_command(
    command: Annotated[
        str,
        Field(description="要执行的远程命令（单条）。"),
    ],
    host: HostArg = None,
    user: UserArg = None,
    password: PasswordArg = None,
    ssh_key_filepath: KeyArg = None,
    port: PortArg = None,
    timeout: TimeoutArg = None,
    connect_timeout: ConnectTimeoutArg = None,
    name: NameArg = None,
    alias: AliasArg = None,
    fail_on_error: Annotated[
        bool,
        Field(
            description=(
                "true 时命令以非 0 状态退出即当作失败抛出；默认 false，"
                "非 0 退出只体现在返回文本的 Exit code 行里。"
            )
        ),
    ] = False,
) -> str:
    """Execute one remote SSH command and return the real command output.

    Raises:
        ToolError: if no target was given, if the target is ambiguous, if
            connecting or executing fails, or if the command exits non-zero
            while ``fail_on_error`` is enabled.
    """
    try:
        result = execute_remote_commands(
            commands=[command],
            host=host,
            user=user,
            password=password,
            ssh_key_filepath=ssh_key_filepath,
            port=port,
            timeout=timeout,
            connect_timeout=connect_timeout,
            name=name,
            alias=alias,
        )
    except Exception as exc:
        _raise_tool_error(exc, "执行远程命令")

    if not result:
        result = f"Command: {command}\nExit code: 0\nStdout:\n<empty>\nStderr:\n<empty>"

    if fail_on_error and "\nExit code: 0\n" not in result:
        raise ToolError(f"远程命令以非 0 状态退出：\n{result}")

    return result


@server.tool(
    name="ssh_upload_directory",
    description=(
        "Upload a local directory or file into a remote directory over SCP. "
        "上传本地目录或文件到远端目录，按 scp -r 语义保留目录名。"
        + CONNECTION_ARGS
    ),
)
def ssh_upload_directory(
    local_dir: Annotated[
        str,
        Field(description="要上传的本地目录或文件路径。"),
    ],
    host: HostArg = None,
    user: UserArg = None,
    password: PasswordArg = None,
    ssh_key_filepath: KeyArg = None,
    remote_path: Annotated[
        str,
        Field(
            description=(
                "远端目标目录，始终按目录处理，不存在会自动创建。"
                "目录按 scp -r 语义保留自身名字：local_dir=/tmp/x + remote_path=/srv → /srv/x。"
            )
        ),
    ] = DEFAULT_REMOTE_PATH,
    port: PortArg = None,
    connect_timeout: ConnectTimeoutArg = None,
    name: NameArg = None,
    alias: AliasArg = None,
) -> str:
    """Upload a local directory via SCP over SSH.

    ``remote_path`` is always treated as a *directory*; it is created on the
    remote host when missing so SCP never collapses the payload into a file.

    ``scp -r`` semantics: a directory keeps its own name, so
    ``local_dir=/tmp/x`` with ``remote_path=/srv`` lands in ``/srv/x`` and not
    in ``/srv``. A single file lands as ``/srv/<name>``.

    Raises:
        ToolError: if no target was given, the local source is missing, the
            connection fails, or the transfer is rejected.
    """
    try:
        return upload_directory(
            local_dir=local_dir,
            host=host,
            user=user,
            password=password,
            ssh_key_filepath=ssh_key_filepath,
            remote_path=remote_path,
            port=port,
            connect_timeout=connect_timeout,
            name=name,
            alias=alias,
        )
    except Exception as exc:
        _raise_tool_error(exc, "上传")


@server.tool(
    name="ssh_download_file",
    description=(
        "Download a file from a remote SSH host to a local path. "
        "把远端单个文件下载到本地。"
        + CONNECTION_ARGS
    ),
)
def ssh_download_file(
    remote_file: Annotated[
        str,
        Field(description="远端文件路径，只支持单个文件，不接受目录。"),
    ],
    host: HostArg = None,
    user: UserArg = None,
    password: PasswordArg = None,
    ssh_key_filepath: KeyArg = None,
    local_path: Annotated[
        str | None,
        Field(
            description=(
                "本地落盘路径。不传则落到系统临时目录的 ssh-mcp-downloads/ 下，"
                "返回值里给出实际位置；该路径已存在会被直接覆盖。"
            )
        ),
    ] = None,
    port: PortArg = None,
    connect_timeout: ConnectTimeoutArg = None,
    name: NameArg = None,
    alias: AliasArg = None,
) -> str:
    """Download a single file from the remote host via SCP.

    When ``local_path`` is omitted the file lands in the system temp directory
    under ``ssh-mcp-downloads/``; an existing file at ``local_path`` is
    overwritten without warning.

    Raises:
        ToolError: if no target was given, the remote file is missing or is a
            directory, the local destination cannot be written, or the
            connection fails.
    """
    try:
        return download_file(
            remote_file=remote_file,
            host=host,
            user=user,
            password=password,
            ssh_key_filepath=ssh_key_filepath,
            local_path=local_path,
            port=port,
            connect_timeout=connect_timeout,
            name=name,
            alias=alias,
        )
    except Exception as exc:
        _raise_tool_error(exc, "下载")


@server.tool(
    name="ssh_list_hosts",
    description=(
        "List machines this tool connected to successfully before, so they can be "
        "addressed by name instead of host/user/password. Passwords are never returned. "
        "列出已缓存的机器（可作为 name 使用），不回显密码。"
    ),
)
def ssh_list_hosts() -> str:
    """Return the credential cache contents without any secret."""
    try:
        return describe()
    except Exception as exc:
        _raise_tool_error(exc, "读取凭据缓存")


@server.tool(
    name="ssh_forget_host",
    description=(
        "Remove a cached machine's credentials so it must be addressed with "
        "host/user/password again. Use it for boxes that were only visited once. "
        "Removes one machine per call: a name matching several is refused and "
        "nothing is deleted. "
        "删除某台机器的缓存凭据，之后必须重新传 host / user / password。"
        "一次只删一台；名字命中多台时报错并列出候选，不会一次删掉多台。"
    ),
)
def ssh_forget_host(
    name: Annotated[
        str,
        Field(
            description=(
                "要遗忘的机器：别名、host 或 host 片段。一次只删一台 —— "
                "命中多台时报错并列出候选，任何一台都不会被删。"
            )
        ),
    ],
) -> str:
    """Delete the one cached entry a name resolves to; refuse if ambiguous."""
    try:
        removed = forget(name)
    except Exception as exc:
        _raise_tool_error(exc, "删除凭据缓存")

    if removed is None:
        return f"凭据缓存里没有匹配 {name!r} 的机器。"
    return f"已删除并遗忘：{removed.summary()}"


def create_mcp_server() -> MCPServer:
    """Return the MCP server instance for this SSH project."""
    return server


def main() -> None:
    """Run the SSH tool server over stdio transport for MCP clients."""
    anyio.run(server.run_stdio_async)


__all__ = [
    "DEFAULT_TIMEOUT",
    "create_mcp_server",
    "main",
    "server",
    "ssh_download_file",
    "ssh_execute_command",
    "ssh_forget_host",
    "ssh_list_hosts",
    "ssh_upload_directory",
]


if __name__ == "__main__":
    main()
