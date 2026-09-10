"""Credential cache for SSH destinations.

The user talks about machines by the name they use in conversation -- "223",
"dev36", "10 那台". Those names are not resolvable by an agent, so the server
remembers a destination the first time it connects to it *successfully*, and
later calls may name that destination instead of repeating host / user /
password. The alias stored is whatever the caller heard, not a name the tool
invented.

Rules that keep the cache from being dangerous:

* **Only a successful connection is remembered.** A failed authentication must
  never be written, otherwise a wrong password gets frozen into the cache and
  every later call repeats the mistake.
* **Explicit arguments always win.** The cache is a fallback, never an
  override, so `host` / `user` / `password` passed by the caller decide the
  connection (see :func:`ssh_mcp.config.resolve_connection`).
* **An ambiguous name is an error, never a guess.** If a name matches more than
  one destination the call fails and lists the candidates. For a read that is
  because picking the wrong machine means running commands on the wrong host;
  for :func:`forget` it is because a deletion cannot be taken back, so it must
  never be decided by a lookup that was only *probably* right. Both paths share
  :func:`_match`, so a name refused for one is refused for the other.

Storage is ``~/.ssh-mcp/credentials.json`` (override with
``SSH_CREDENTIALS_FILE``), written ``0600`` inside a ``0700`` directory. The
file holds plaintext secrets by design -- that was an explicit choice; the
protection is filesystem permissions, not encryption.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, NamedTuple, Sequence

DEFAULT_CREDENTIALS_PATH = "~/.ssh-mcp/credentials.json"
ENV_CREDENTIALS_FILE = "SSH_CREDENTIALS_FILE"
SCHEMA_VERSION = 1


class CredentialError(ValueError):
    """Base class for credential cache problems."""


class NameNotFound(CredentialError):
    """No cached destination matches the requested name."""


class AmbiguousName(CredentialError):
    """The requested name matches more than one cached destination."""


class Credential(NamedTuple):
    """One remembered SSH destination."""

    host: str
    user: str
    password: str
    ssh_key_filepath: str
    port: int
    aliases: tuple[str, ...]
    last_used: str

    def summary(self) -> str:
        """Return a password-free one-line description.

        One pair of brackets around one labelled list, so the line reads the
        same whether or not an alias was ever recorded -- a machine with no
        alias used to render as ``[-]  (password)``, which looks like a broken
        bracket rather than "no alias".
        """
        auth = "密码" if self.password else ("密钥" if self.ssh_key_filepath else "ssh-agent")
        detail = f"别名 {'/'.join(self.aliases)}，{auth}" if self.aliases else auth
        return f"{self.user}@{self.host}:{self.port}（{detail}）"


def credentials_path() -> Path:
    """Return the cache file location (``SSH_CREDENTIALS_FILE`` or default)."""
    configured = os.environ.get(ENV_CREDENTIALS_FILE, "").strip()
    return Path(configured or DEFAULT_CREDENTIALS_PATH).expanduser()


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _to_credential(entry: Dict[str, Any]) -> Credential:
    if not isinstance(entry, dict):
        raise CredentialError(f"缓存条目必须是对象，收到：{entry!r}")
    host = _clean(entry.get("host"))
    user = _clean(entry.get("user") or entry.get("username"))
    if not host or not user:
        raise CredentialError(f"缓存条目缺少 host 或 user：{entry!r}")

    raw_port = entry.get("port")
    try:
        port = int(str(raw_port).strip()) if raw_port not in (None, "") else 22
    except (TypeError, ValueError) as exc:
        raise CredentialError(f"缓存条目 port 非法（{host}）：{raw_port!r}") from exc

    raw_aliases = entry.get("aliases") or []
    if isinstance(raw_aliases, str):
        raw_aliases = [raw_aliases]
    aliases = tuple(
        dict.fromkeys(_clean(a) for a in raw_aliases if _clean(a))  # de-duped, order kept
    )

    return Credential(
        host=host,
        user=user,
        password=_clean(entry.get("password")),
        ssh_key_filepath=_clean(entry.get("ssh_key_filepath") or entry.get("key_filepath")),
        port=port,
        aliases=aliases,
        last_used=_clean(entry.get("last_used")),
    )


def _read_entries() -> List[Dict[str, Any]]:
    path = credentials_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CredentialError(f"凭据缓存不是合法 JSON：{path}（{exc}）") from exc
    except OSError as exc:
        raise CredentialError(f"凭据缓存无法读取：{path}（{exc}）") from exc

    if isinstance(data, list):  # tolerate a bare array
        return data
    if not isinstance(data, dict):
        raise CredentialError(f"凭据缓存顶层必须是对象：{path}")
    entries = data.get("credentials", [])
    if not isinstance(entries, list):
        raise CredentialError(f"凭据缓存的 credentials 字段必须是数组：{path}")
    return entries


def load() -> List[Credential]:
    """Return every cached destination, most recently used first.

    Raises:
        CredentialError: if the file exists but is unreadable or malformed.
    """
    return [_to_credential(entry) for entry in _read_entries()]


def _name_matches(credential: Credential, needle: str) -> bool:
    lowered = needle.lower()
    return any(alias.lower() == lowered for alias in credential.aliases)


def _candidate_label(credential: Credential) -> str:
    """Describe one candidate for an error message.

    The alias list is omitted rather than padded when a machine has none: an
    ``aliases or host`` fallback prints the host twice, once outside the
    brackets and once inside, which reads as a mistake.
    """
    label = credential.user
    if credential.aliases:
        label = f"{'/'.join(credential.aliases)}，{label}"
    return f"{credential.host}:{credential.port}（{label}）"


def _candidates_text(credentials: Sequence[Credential]) -> str:
    if not credentials:
        return "（缓存为空）"
    return "；".join(_candidate_label(credential) for credential in credentials)


def _match(credentials: Sequence[Credential], needle: str) -> List[Credential]:
    """Return the hits from the first stage that produces any.

    Stages are tried in order -- alias exact, then host exact, then host
    substring -- and resolution stops at the first non-empty one, so an exact
    alias outranks another machine's host that merely contains the same text.

    Shared by :func:`find` and :func:`forget` on purpose: if the two resolved
    names differently, a name refused for a command could still silently delete
    the wrong entry.
    """
    lowered = needle.lower()
    stages = (
        lambda c: _name_matches(c, needle),
        lambda c: c.host.lower() == lowered,
        lambda c: lowered in c.host.lower(),
    )
    for predicate in stages:
        hits = [credential for credential in credentials if predicate(credential)]
        if hits:
            return hits
    return []


def find(name: str) -> Credential:
    """Resolve a user-spoken name to a cached destination.

    Matching order, stopping at the first stage that produces any hit:

    1. alias exact (the name the user actually said)
    2. host exact
    3. host substring -- so "223" finds ``192.168.11.223``

    Raises:
        NameNotFound: nothing matched. Message lists what is cached.
        AmbiguousName: several matched. Message lists the candidates; the call
            is refused rather than guessed.
    """
    cleaned = _clean(name)
    if not cleaned:
        raise NameNotFound("name 为空。")

    credentials = load()
    if not credentials:
        raise NameNotFound(
            f"还没有任何已缓存的机器（{credentials_path()}）。"
            "请先带 host / user / password 调用一次，成功后会记住。"
        )

    hits = _match(credentials, cleaned)
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise AmbiguousName(
            f"{cleaned!r} 匹配到多台机器，无法确定是哪一台：{_candidates_text(hits)}。"
            "请直接传 host（和 user）指明。"
        )

    raise NameNotFound(
        f"缓存里没有匹配 {cleaned!r} 的机器。已缓存：{_candidates_text(credentials)}。"
        "若首次连接，请带上 host / user / password 调用一次。"
    )


def remember(
    host: str,
    user: str,
    password: str = "",
    ssh_key_filepath: str = "",
    port: int | str | None = None,
    aliases: Iterable[str] = (),
) -> Credential:
    """Create or refresh the cache entry for one destination.

    An existing entry keeps its password when the new call has none (a cache
    hit should not wipe the stored password), and keeps previously learned
    aliases unless new ones are supplied.

    Raises:
        CredentialError: if the file cannot be written.
    """
    host = _clean(host)
    user = _clean(user)
    if not host or not user:
        raise CredentialError("host 和 user 都不能为空，无法写入凭据缓存。")

    try:
        resolved_port = int(str(port).strip()) if port not in (None, "") else 22
    except (TypeError, ValueError) as exc:
        raise CredentialError(f"port 非法：{port!r}") from exc

    incoming = [_clean(a) for a in aliases if _clean(a)]

    path = credentials_path()
    entries = _read_entries()
    existing = [
        entry
        for entry in entries
        if _clean(entry.get("host")) == host
        and _clean(entry.get("user") or entry.get("username")) == user
        and (_clean(entry.get("port")) or "22") == str(resolved_port)
    ]

    kept_aliases: List[str] = []
    kept_password = ""
    kept_key = ""
    if existing:
        old = _to_credential(existing[0])
        kept_aliases = list(old.aliases)
        kept_password = old.password
        kept_key = old.ssh_key_filepath

    merged_aliases = list(dict.fromkeys([*kept_aliases, *incoming]))
    credential = Credential(
        host=host,
        user=user,
        password=_clean(password) or kept_password,
        ssh_key_filepath=_clean(ssh_key_filepath) or kept_key,
        port=resolved_port,
        aliases=tuple(merged_aliases),
        last_used=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    key = (host, user, str(resolved_port))
    survivors = [
        entry
        for entry in entries
        if (
            _clean(entry.get("host")),
            _clean(entry.get("user") or entry.get("username")),
            _clean(entry.get("port")) or "22",
        )
        != key
    ]
    # Most recently used goes first, so the file reads as a usage history and
    # load() needs no timestamp sorting (two calls can land in the same second).
    survivors.insert(
        0,
        {
            "host": credential.host,
            "user": credential.user,
            "password": credential.password,
            "ssh_key_filepath": credential.ssh_key_filepath,
            "port": credential.port,
            "aliases": list(credential.aliases),
            "last_used": credential.last_used,
        }
    )

    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        path.write_text(
            json.dumps(
                {"version": SCHEMA_VERSION, "credentials": survivors},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)
    except OSError as exc:
        raise CredentialError(f"凭据缓存写入失败：{path}（{exc}）") from exc

    return credential


def forget(name: str) -> Credential | None:
    """Delete the single cached entry matching a name. Returns what was removed.

    Resolution is identical to :func:`find` -- alias exact, then host exact,
    then host substring. A name that matches several machines is **refused**,
    with the candidates listed, instead of deleting all of them: a deletion
    cannot be taken back, and "remove every match" let one call such as
    ``forget("192.168.1")`` quietly drop two unrelated machines while reporting
    only the first one back.

    Args:
        name: alias, host, or host fragment of the machine to drop.

    Returns:
        The removed credential, or ``None`` when nothing matched.

    Raises:
        AmbiguousName: the name matched more than one destination. Nothing is
            deleted; pass a fuller name, or call once per machine.
        CredentialError: the cache is unreadable or cannot be written.
    """
    cleaned = _clean(name)
    if not cleaned:
        return None

    entries = _read_entries()
    credentials = [_to_credential(entry) for entry in entries]

    hits = _match(credentials, cleaned)
    if not hits:
        return None
    if len(hits) > 1:
        raise AmbiguousName(
            f"{cleaned!r} 匹配到多台机器，无法确定删哪一台：{_candidates_text(hits)}。"
            "请把名字写准（用别名或完整 host），或一台一台地删。"
        )

    doomed = hits[0]
    # entries and credentials are positionally aligned, and _match returns the
    # very objects held in credentials, so identity picks the exact entry.
    survivors = [
        entry
        for entry, credential in zip(entries, credentials)
        if credential is not doomed
    ]

    path = credentials_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        path.write_text(
            json.dumps(
                {"version": SCHEMA_VERSION, "credentials": survivors},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)
    except OSError as exc:
        raise CredentialError(f"凭据缓存写入失败：{path}（{exc}）") from exc

    return doomed


def describe() -> str:
    """Return a password-free listing of the cache for the client to read."""
    credentials = load()
    if not credentials:
        return f"凭据缓存为空（{credentials_path()}）。"
    lines = [f"已缓存 {len(credentials)} 台（{credentials_path()}）："]
    lines.extend(f"  {credential.summary()}" for credential in credentials)
    return "\n".join(lines)


__all__ = [
    "DEFAULT_CREDENTIALS_PATH",
    "ENV_CREDENTIALS_FILE",
    "AmbiguousName",
    "Credential",
    "CredentialError",
    "NameNotFound",
    "credentials_path",
    "describe",
    "find",
    "forget",
    "load",
    "remember",
]
