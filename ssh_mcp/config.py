"""Validate connection settings supplied for one SSH call.

Every entrypoint (CLI, Python API, MCP tools) funnels through
:func:`resolve_connection`, so all three take exactly the same knobs. Nothing
is read from ``os.environ``: the caller states which machine to talk to.

The resolver is deliberately stateless: every operation supplies its own host,
user and authentication material. Nothing is read from or written to a
credential cache.

Required: ``host`` + ``user``.

Optional: ``password`` / ``ssh_key_filepath`` (with neither, paramiko falls
back to the ssh-agent and ``~/.ssh`` default keys), ``port`` (22), ``timeout``
-- the per-command execution budget, 30s -- ``connect_timeout`` -- how long to
wait for the socket and SSH handshake, 10s -- and ``remote_path`` (``/tmp``).

The two timeouts are deliberately independent. A command that overruns its
``timeout`` is reported as exit code 124 together with the output it produced,
while an unreachable host fails the call outright. Raising ``timeout``
therefore never rescues a host that cannot be reached: that knob belongs to
``connect_timeout``.
"""

from __future__ import annotations

from typing import NamedTuple

DEFAULT_PORT = 22
DEFAULT_TIMEOUT = 30.0
DEFAULT_REMOTE_PATH = "/tmp"
DEFAULT_CONNECT_TIMEOUT = 10.0


class ConnectionSettings(NamedTuple):
    """Fully resolved settings for one SSH connection."""

    host: str
    user: str
    password: str
    ssh_key_filepath: str
    port: int
    timeout: float
    connect_timeout: float
    remote_path: str
    source: str


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _resolve_port(port: int | str | None) -> int:
    if port is None or port == "":
        return DEFAULT_PORT
    try:
        resolved = int(str(port).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"port 必须是整数，收到：{port!r}") from exc
    if not 1 <= resolved <= 65535:
        raise ValueError(f"port 必须在 1-65535 之间，收到：{resolved}")
    return resolved


def _resolve_seconds(value: float | str | None, default: float, name: str) -> float:
    """Coerce a caller-supplied duration, or fall back to ``default``."""
    if value is None or value == "":
        return default
    try:
        resolved = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数字，收到：{value!r}") from exc
    if resolved <= 0:
        raise ValueError(f"{name} 必须大于 0，收到：{resolved}")
    return resolved


def _resolve_timeout(timeout: float | str | None) -> float:
    """Per-command execution budget (not the connection timeout)."""
    return _resolve_seconds(timeout, DEFAULT_TIMEOUT, "timeout")


def _resolve_connect_timeout(connect_timeout: float | str | None) -> float:
    """Socket / SSH handshake budget, separate from the command timeout."""
    return _resolve_seconds(connect_timeout, DEFAULT_CONNECT_TIMEOUT, "connect_timeout")


def resolve_connection(
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
    ssh_key_filepath: str | None = None,
    port: int | str | None = None,
    timeout: float | str | None = None,
    connect_timeout: float | str | None = None,
    remote_path: str | None = None,
) -> ConnectionSettings:
    """Build settings for one call from explicit arguments.

    Args:
        timeout: per-command execution budget in seconds. Not used for
            connecting -- see ``connect_timeout``.
        connect_timeout: budget for establishing the connection (TCP + SSH
            handshake), in seconds. Defaults to ``10``.

    Raises:
        ValueError: if ``host`` / ``user`` are still missing (the message says
            what to pass), or if ``port`` / ``timeout`` / ``connect_timeout``
            are not usable numbers, or if ``port`` is outside 1-65535.
        ValueError: if required connection fields or numeric options are invalid.
    """
    explicit_host = _clean(host)
    explicit_user = _clean(user)
    if not explicit_host:
        raise ValueError("host 未提供：请传入 host 参数。")
    if not explicit_user:
        raise ValueError("user 未提供：请传入 user 参数。")

    return ConnectionSettings(
        host=explicit_host,
        user=explicit_user,
        password=_clean(password) or "",
        ssh_key_filepath=_clean(ssh_key_filepath) or "",
        port=_resolve_port(port),
        timeout=_resolve_timeout(timeout),
        connect_timeout=_resolve_connect_timeout(connect_timeout),
        remote_path=_clean(remote_path) or DEFAULT_REMOTE_PATH,
        source="arguments",
    )
