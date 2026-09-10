"""Tests for the credential cache and how a spoken name resolves to a host."""

import json
import stat

import pytest
from paramiko.ssh_exception import AuthenticationException

from ssh_mcp import client as client_module
from ssh_mcp.credentials import (
    AmbiguousName,
    CredentialError,
    NameNotFound,
    credentials_path,
    describe,
    find,
    forget,
    load,
    remember,
)


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Point every test at a throwaway cache file, never the real one."""
    monkeypatch.setenv("SSH_CREDENTIALS_FILE", str(tmp_path / "credentials.json"))
    return tmp_path


def test_remember_then_find_by_alias():
    remember("192.168.11.223", "root", password="pw", aliases=["223", "server223"])

    found = find("223")

    assert found.host == "192.168.11.223"
    assert found.password == "pw"


def test_find_by_host_exact():
    remember("192.168.11.223", "root", password="pw")

    assert find("192.168.11.223").user == "root"


def test_find_by_host_fragment():
    remember("192.168.10.232", "root", password="pw")

    assert find("10.232").host == "192.168.10.232"


def test_alias_is_matched_before_fragment():
    remember("192.168.11.223", "root", password="a", aliases=["223"])
    remember("192.168.223.9", "admin", password="b")

    assert find("223").host == "192.168.11.223"


def test_ambiguous_fragment_is_refused_not_guessed():
    remember("192.168.10.36", "root", password="a")
    remember("192.168.34.52", "sysadm", password="b")

    with pytest.raises(AmbiguousName) as excinfo:
        find("3")

    message = str(excinfo.value)
    assert "192.168.10.36" in message
    assert "192.168.34.52" in message


def test_unknown_name_lists_what_is_cached():
    remember("192.168.11.223", "root", password="pw", aliases=["223"])

    with pytest.raises(NameNotFound) as excinfo:
        find("dev36")

    assert "192.168.11.223" in str(excinfo.value)


def test_empty_cache_raises_helpful_error():
    with pytest.raises(NameNotFound, match="还没有任何已缓存的机器"):
        find("223")


def test_remember_keeps_password_when_new_call_has_none():
    remember("10.0.0.5", "root", password="secret")
    remember("10.0.0.5", "root")

    assert find("10.0.0.5").password == "secret"


def test_remember_merges_aliases_without_duplicates():
    remember("10.0.0.5", "root", password="pw", aliases=["five"])
    remember("10.0.0.5", "root", password="pw", aliases=["five", "测试机"])

    assert find("10.0.0.5").aliases == ("five", "测试机")


def test_remember_updates_in_place_keeping_last_used_newest_first():
    remember("10.0.0.5", "root", password="pw")
    remember("10.0.0.6", "root", password="pw")
    remember("10.0.0.5", "root", password="pw")

    hosts = [credential.host for credential in load()]

    assert len(hosts) == 2
    assert hosts[0] == "10.0.0.5"


def test_same_host_different_port_are_separate_entries():
    remember("10.0.0.5", "root", password="a", port=22)
    remember("10.0.0.5", "root", password="b", port=2222)

    assert len(load()) == 2


def test_cache_file_is_owner_only(_isolated_cache):
    remember("10.0.0.5", "root", password="pw")

    mode = stat.S_IMODE(credentials_path().stat().st_mode)

    assert mode == 0o600


def test_forget_removes_entry():
    remember("10.0.0.5", "root", password="pw", aliases=["five"])

    removed = forget("five")

    assert removed is not None
    assert removed.host == "10.0.0.5"
    assert load() == []
    assert forget("five") is None


def test_forget_refuses_an_ambiguous_name_and_deletes_nothing():
    """A name matching several machines must not take all of them down.

    Regression: forget() deleted every match and reported only the first, so
    ``forget("192.168.1")`` emptied two unrelated machines in one call while
    the reply mentioned a single host.
    """
    remember("192.168.11.231", "root", password="a", aliases=["231"])
    remember("192.168.10.33", "root", password="b", aliases=["33"])

    with pytest.raises(AmbiguousName) as excinfo:
        forget("192.168.1")

    message = str(excinfo.value)
    assert "192.168.11.231" in message
    assert "192.168.10.33" in message
    # The refusal must leave the cache untouched.
    assert len(load()) == 2


def test_forget_uses_the_same_precedence_as_find():
    """An exact alias outranks another host that merely contains the text.

    If forget() resolved names differently from find(), a name refused for a
    command could still delete the wrong entry -- so an exact hit must win here
    too, even when a substring hit also exists.
    """
    remember("192.168.11.223", "root", password="a", aliases=["223"])
    remember("192.168.223.9", "admin", password="b")

    removed = forget("223")

    assert removed is not None
    assert removed.host == "192.168.11.223"
    assert [credential.host for credential in load()] == ["192.168.223.9"]


def test_forget_unknown_name_returns_none_without_touching_the_cache():
    remember("192.168.11.231", "root", password="a", aliases=["231"])

    assert forget("nope") is None
    assert len(load()) == 1


def test_describe_never_leaks_the_password():
    remember("10.0.0.5", "root", password="hunter2", aliases=["five"])

    output = describe()

    assert "hunter2" not in output
    assert "10.0.0.5" in output
    assert "five" in output


def test_corrupt_cache_reports_a_clear_error(_isolated_cache):
    path = _isolated_cache / "credentials.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(CredentialError, match="不是合法 JSON"):
        load()


def test_entries_missing_host_are_rejected(_isolated_cache):
    path = _isolated_cache / "credentials.json"
    path.write_text(json.dumps({"credentials": [{"user": "root"}]}), encoding="utf-8")

    with pytest.raises(CredentialError, match="缺少 host"):
        load()


def test_successful_call_is_cached(monkeypatch):
    def fake_execute(self, commands, timeout=None):
        return "Command: uptime\nExit code: 0\nStdout:\nup\nStderr:\n<empty>"

    monkeypatch.setattr(client_module.RemoteClient, "execute_commands", fake_execute)

    client_module.execute_remote_commands(
        ["uptime"], host="10.0.0.5", user="root", password="pw", alias="五号机"
    )

    cached = find("五号机")
    assert cached.host == "10.0.0.5"
    assert cached.password == "pw"


def test_failed_authentication_is_never_cached(monkeypatch, _isolated_cache):
    def boom(self, commands, timeout=None):
        raise AuthenticationException("bad password")

    monkeypatch.setattr(client_module.RemoteClient, "execute_commands", boom)

    with pytest.raises(AuthenticationException):
        client_module.execute_remote_commands(
            ["uptime"], host="10.0.0.5", user="root", password="wrong", alias="五号机"
        )

    assert not (_isolated_cache / "credentials.json").exists()


def test_call_by_name_reuses_cached_credentials(monkeypatch):
    remember("10.0.0.5", "root", password="pw", aliases=["223"])
    seen = {}

    def fake_execute(self, commands, timeout=None):
        seen["host"] = self.host
        seen["password"] = self.password
        return "Command: uptime\nExit code: 0\nStdout:\nup\nStderr:\n<empty>"

    monkeypatch.setattr(client_module.RemoteClient, "execute_commands", fake_execute)

    client_module.execute_remote_commands(["uptime"], name="223")

    assert seen["host"] == "10.0.0.5"
    assert seen["password"] == "pw"


def test_explicit_arguments_override_cached_credentials(monkeypatch):
    remember("10.0.0.5", "root", password="cached-pw", aliases=["223"])
    seen = {}

    def fake_execute(self, commands, timeout=None):
        seen["user"] = self.user
        seen["password"] = self.password
        return "ok"

    monkeypatch.setattr(client_module.RemoteClient, "execute_commands", fake_execute)

    client_module.execute_remote_commands(
        ["uptime"], name="223", user="admin", password="typed-pw"
    )

    assert seen["user"] == "admin"
    assert seen["password"] == "typed-pw"


def test_calling_by_name_does_not_pin_that_name_as_an_alias(monkeypatch):
    """A name matched by host fragment must not be cached as an alias.

    Regression: every successful call stored the ``name`` it was addressed by,
    so a throwaway fragment such as "192.168.11" became a permanent alias and
    cluttered what ``ssh_list_hosts`` (and the user) sees.
    """
    remember("192.168.11.231", "root", password="pw", aliases=["231"])

    def fake_execute(self, commands, timeout=None):
        return "ok"

    monkeypatch.setattr(client_module.RemoteClient, "execute_commands", fake_execute)

    client_module.execute_remote_commands(["uptime"], name="192.168.11")

    assert find("192.168.11.231").aliases == ("231",)


def test_a_new_explicit_alias_is_still_learned(monkeypatch):
    """Dropping the implicit alias must not stop real aliases from sticking."""
    remember("192.168.11.231", "root", password="pw", aliases=["231"])

    def fake_execute(self, commands, timeout=None):
        return "ok"

    monkeypatch.setattr(client_module.RemoteClient, "execute_commands", fake_execute)

    client_module.execute_remote_commands(["uptime"], name="231", alias="测试机")

    assert find("测试机").host == "192.168.11.231"
    assert find("192.168.11.231").aliases == ("231", "测试机")
