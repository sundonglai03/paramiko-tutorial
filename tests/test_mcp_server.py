import importlib
import os
import socket
import stat
from pathlib import Path

import anyio
from mcp.server.mcpserver.exceptions import ToolError
from paramiko.ssh_exception import AuthenticationException

from ssh_mcp.server import DEFAULT_COMMAND_TIMEOUT, RemoteClient


def test_mcp_server_module_exists():
    module = importlib.import_module("ssh_mcp.mcp_server")
    assert hasattr(module, "create_mcp_server")
    assert hasattr(module, "ssh_execute_command")
    assert hasattr(module, "ssh_upload_directory")
    assert hasattr(module, "ssh_download_file")
    assert hasattr(module, "main")


def test_ssh_execute_command_returns_command_output(monkeypatch):
    module = importlib.import_module("ssh_mcp.mcp_server")

    def fake_execute_remote_commands(
        *, commands, host, user, password, ssh_key_filepath, port, timeout, connect_timeout=None, name=None, alias=None
    ):
        assert commands == ["echo hello"]
        return "Command: echo hello\nExit code: 0\nStdout:\nhello from remote\nStderr:\n<empty>"

    monkeypatch.setattr(module, "execute_remote_commands", fake_execute_remote_commands)

    result = module.ssh_execute_command(
        command="echo hello",
        host="example.com",
        user="root",
        password="pw",
        ssh_key_filepath=None,
        port=22,
    )

    assert "Exit code: 0" in result
    assert "hello from remote" in result
    assert "Stdout:" in result
    assert "SSH command executed successfully" not in result


def test_execute_commands_returns_failure_details_without_raising(monkeypatch):
    class FakeStdin:
        def close(self):
            pass

    class FakeChannel:
        def __init__(self):
            self.timeout = None

        def settimeout(self, timeout):
            self.timeout = timeout

        def recv_exit_status(self):
            return 2

    class FakeStdout:
        def __init__(self):
            self.channel = FakeChannel()

        def read(self):
            return b"ls: cannot access '/nope': No such file or directory\n"

    class FakeStderr:
        def read(self):
            return b""

    class FakeConnection:
        def exec_command(self, cmd, timeout=None, **kwargs):
            assert timeout == DEFAULT_COMMAND_TIMEOUT
            return FakeStdin(), FakeStdout(), FakeStderr()

    client = RemoteClient(
        host="example.com",
        user="root",
        password="pw",
        ssh_key_filepath="",
        remote_path="/tmp",
        port=22,
    )
    monkeypatch.setattr(RemoteClient, "connection", property(lambda self: FakeConnection()))

    result = client.execute_commands(["ls /nope"])

    assert "Exit code: 2" in result
    assert "No such file or directory" in result
    assert "Command: ls /nope" in result


def test_download_file_uses_temp_dir_by_default(monkeypatch, tmp_path):
    class FakeSCP:
        def __init__(self):
            self.calls = []

        def get(self, filepath, local_path=None):
            self.calls.append({"filepath": filepath, "local_path": local_path})
            if local_path is None:
                raise AssertionError("local_path must be set when downloading")
            target = Path(local_path)
            target.write_text("remote-content")
            return str(target)

    client = RemoteClient(
        host="example.com",
        user="root",
        password="pw",
        ssh_key_filepath="",
        remote_path="/tmp",
        port=22,
    )
    client.scp_client = FakeSCP()
    monkeypatch.setattr("ssh_mcp.server.tempfile.gettempdir", lambda: str(tmp_path))

    result = client.download_file("/etc/hostname")

    expected = tmp_path / "ssh-mcp-downloads" / "hostname"
    assert str(expected) in result
    assert expected.read_text() == "remote-content"
    assert stat.S_IMODE(os.stat(expected).st_mode) == 0o600


def test_execute_commands_timeout_returns_structured_error():
    class FakeChannel:
        def __init__(self):
            self.closed = False

        def settimeout(self, timeout):
            self.timeout = timeout

        def recv_exit_status(self):
            raise TimeoutError("channel timed out")

        def close(self):
            self.closed = True

    class FakeStdout:
        def __init__(self):
            self.channel = FakeChannel()

        def read(self):
            return b""

    class FakeStderr:
        def read(self):
            return b""

    class FakeConnection:
        def exec_command(self, cmd, timeout=None, **kwargs):
            return object(), FakeStdout(), FakeStderr()

    client = RemoteClient(
        host="example.com",
        user="root",
        password="pw",
        ssh_key_filepath="",
        remote_path="/tmp",
        port=22,
    )
    client.client = FakeConnection()

    result = client.execute_commands(["cat"], timeout=30.0)

    assert "Command: cat" in result
    assert "timed out after 30.0 seconds" in result


def test_ssh_execute_command_raises_on_real_connection_error(monkeypatch):
    """A failed call must surface as a tool error, not as a success string."""
    module = importlib.import_module("ssh_mcp.mcp_server")

    def fake_execute_remote_commands(
        *, commands, host, user, password, ssh_key_filepath, port, timeout, connect_timeout=None, name=None, alias=None
    ):
        raise ConnectionError("Connection refused by remote host")

    monkeypatch.setattr(module, "execute_remote_commands", fake_execute_remote_commands)

    try:
        module.ssh_execute_command(
            command="pwd",
            host="example.com",
            user="root",
            password="pw",
            ssh_key_filepath=None,
            port=22,
        )
        raise AssertionError("Expected ToolError to propagate")
    except ToolError as exc:
        # ToolError is what the MCP SDK forwards verbatim to the client.
        assert "Connection refused by remote host" in str(exc)


def test_tool_call_reports_failure_detail_to_client(monkeypatch):
    """Regression: the SDK hides any non-ToolError message from the client.

    Without the ``ToolError`` conversion the client only ever sees
    ``Error executing tool <name>``; this asserts the real cause survives.
    """
    module = importlib.import_module("ssh_mcp.mcp_server")

    def fake_execute_remote_commands(
        *, commands, host, user, password, ssh_key_filepath, port, timeout, connect_timeout=None, name=None, alias=None
    ):
        raise ConnectionError("Connection refused by remote host")

    monkeypatch.setattr(module, "execute_remote_commands", fake_execute_remote_commands)

    try:
        anyio.run(
            module.server.call_tool,
            "ssh_execute_command",
            {
                "command": "pwd",
                "host": "example.com",
                "user": "root",
                "password": "pw",
                "port": 22,
            },
        )
        raise AssertionError("Expected the tool call to fail")
    except ToolError as exc:
        # The SDK prefixes its own text, then keeps ours - the transport layer
        # turns str(exc) into CallToolResult(is_error=True).content[0].text.
        assert "Error executing tool ssh_execute_command" in str(exc)
        assert "Connection refused by remote host" in str(exc)


def test_describe_error_classifies_common_failures():
    module = importlib.import_module("ssh_mcp.mcp_server")
    describe = module._describe_error

    assert "认证失败" in describe(AuthenticationException("Authentication failed."))
    assert "无法解析" in describe(socket.gaierror("Name or service not known"))
    assert "被拒绝" in describe(ConnectionRefusedError(111, "Connection refused"))
    assert "超时" in describe(TimeoutError("timed out"))
    assert "不存在" in describe(FileNotFoundError("Upload source does not exist: /nope"))
    assert "非文件" in describe(IsADirectoryError(21, "Is a directory"))
    assert "权限" in describe(PermissionError(13, "Permission denied"))


def test_ssh_execute_command_can_fail_on_non_zero_exit(monkeypatch):
    module = importlib.import_module("ssh_mcp.mcp_server")

    def fake_execute_remote_commands(
        *, commands, host, user, password, ssh_key_filepath, port, timeout, connect_timeout=None, name=None, alias=None
    ):
        return "Command: ls /nope\nExit code: 2\nStdout:\n<empty>\nStderr:\nno such file"

    monkeypatch.setattr(module, "execute_remote_commands", fake_execute_remote_commands)

    ok = module.ssh_execute_command("ls /nope", "example.com", "root", "pw", timeout=5)
    assert "Exit code: 2" in ok


def test_main_supports_streamable_http_transport(monkeypatch):
    module = importlib.import_module("ssh_mcp.mcp_server")

    calls = {}

    def fake_run(transport=None, **kwargs):
        calls["transport"] = transport
        calls["kwargs"] = kwargs

    def fake_execute_remote_commands(
        *, commands, host, user, password, ssh_key_filepath, port, timeout, connect_timeout=None, name=None, alias=None
    ):
        return "Command: ls /nope\nExit code: 2\nStdout:\n<empty>\nStderr:\nno such file"

    monkeypatch.setattr(module.server, "run", fake_run)
    monkeypatch.setattr(module, "execute_remote_commands", fake_execute_remote_commands)

    module.main(["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9001", "--path", "/mcp"])

    assert calls["transport"] == "streamable-http"
    assert calls["kwargs"]["host"] == "0.0.0.0"
    assert calls["kwargs"]["port"] == 9001
    assert calls["kwargs"]["streamable_http_path"] == "/mcp"

    try:
        module.ssh_execute_command(
            "ls /nope", "example.com", "root", "pw", timeout=5, fail_on_error=True
        )
        raise AssertionError("Expected ToolError for non-zero exit")
    except ToolError as exc:
        assert "远程命令以非 0 状态退出" in str(exc)
        assert "Exit code: 2" in str(exc)
        assert "no such file" in str(exc)


def test_bulk_upload_missing_source_raises_clear_error(monkeypatch, tmp_path):
    client = RemoteClient(
        host="example.com",
        user="root",
        password="pw",
        ssh_key_filepath="",
        remote_path="/tmp",
        port=22,
    )
    missing = tmp_path / "missing-dir"

    try:
        client.bulk_upload(str(missing), recursive=True)
        raise AssertionError("Expected FileNotFoundError")
    except FileNotFoundError as exc:
        assert "does not exist" in str(exc)
        assert str(missing) in str(exc)


def test_bulk_upload_directory_keeps_basename_like_scp_r(monkeypatch, tmp_path):
    local_dir = tmp_path / "updir"
    (local_dir / "sub").mkdir(parents=True)
    (local_dir / "a.txt").write_text("a")
    (local_dir / "sub" / "b.txt").write_text("b")

    class FakeSCP:
        def __init__(self):
            self.calls = []

        def put(self, source, remote_path=None, recursive=False):
            self.calls.append({
                "source": source,
                "remote_path": remote_path,
                "recursive": recursive,
            })

    class FakeStdin:
        def close(self):
            pass

    class FakeChannel:
        def __init__(self):
            self.timeout = None

        def settimeout(self, timeout):
            self.timeout = timeout

        def recv_exit_status(self):
            return 0

    class FakeStdout:
        def __init__(self, payload=b""):
            self.channel = FakeChannel()
            self._payload = payload

        def read(self):
            return self._payload

    class FakeStderr:
        def read(self):
            return b""

    class FakeConnection:
        """Stands in for paramiko: reports that the remote dir was created."""

        def __init__(self):
            self.commands = []

        def exec_command(self, cmd, timeout=None, **kwargs):
            self.commands.append(cmd)
            return FakeStdin(), FakeStdout(b"__SSH_MCP_DIR_OK__\n"), FakeStderr()

    fake_connection = FakeConnection()

    client = RemoteClient(
        host="example.com",
        user="root",
        password="pw",
        ssh_key_filepath="",
        remote_path="/remote/dest",
        port=22,
    )
    client.scp_client = FakeSCP()
    client.client = fake_connection

    client.bulk_upload(str(local_dir), recursive=True)

    # scp -r semantics: one put for the directory itself, which recreates the
    # basename under remote_path -> /remote/dest/updir/...
    assert len(client.scp_client.calls) == 1
    call = client.scp_client.calls[0]
    assert call["source"] == str(local_dir)
    assert call["remote_path"] == "/remote/dest"
    assert call["recursive"] is True
    # The destination directory must be created before the first SCP put.
    assert fake_connection.commands
    assert "mkdir -p" in fake_connection.commands[0]


def test_bulk_upload_single_file_lands_inside_remote_path(monkeypatch, tmp_path):
    local_file = tmp_path / "a.txt"
    local_file.write_text("a")

    class FakeSCP:
        def __init__(self):
            self.calls = []

        def put(self, source, remote_path=None, recursive=False):
            self.calls.append({"source": source, "remote_path": remote_path, "recursive": recursive})

    class FakeStdin:
        def close(self):
            pass

    class FakeChannel:
        def settimeout(self, timeout):
            pass

        def recv_exit_status(self):
            return 0

    class FakeStdout:
        def __init__(self, payload=b""):
            self.channel = FakeChannel()
            self._payload = payload

        def read(self):
            return self._payload

    class FakeStderr:
        def read(self):
            return b""

    class FakeConnection:
        def exec_command(self, cmd, timeout=None, **kwargs):
            return FakeStdin(), FakeStdout(b"__SSH_MCP_DIR_OK__\n"), FakeStderr()

    client = RemoteClient(
        host="example.com",
        user="root",
        password="pw",
        ssh_key_filepath="",
        remote_path="/remote/dest",
        port=22,
    )
    client.scp_client = FakeSCP()
    client.client = FakeConnection()

    client.bulk_upload(str(local_file))

    assert len(client.scp_client.calls) == 1
    assert client.scp_client.calls[0]["source"] == str(local_file)
    assert client.scp_client.calls[0]["remote_path"] == "/remote/dest"
    assert client.scp_client.calls[0]["recursive"] is False


def test_every_tool_parameter_is_documented_in_the_schema():
    """Whatever a caller sees in ``tools/list`` must explain itself.

    Regression: ``fail_on_error`` shipped with no description, so a calling
    model had to guess whether a non-zero exit raises or is returned.
    """
    module = importlib.import_module("ssh_mcp.mcp_server")

    schemas = {tool.name: tool.input_schema for tool in anyio.run(module.server.list_tools)}

    assert set(schemas) == {
        "ssh_execute_command",
        "ssh_upload_directory",
        "ssh_download_file",
        "ssh_list_hosts",
        "ssh_forget_host",
    }

    undocumented = [
        f"{tool}.{param}"
        for tool, schema in schemas.items()
        for param, spec in schema["properties"].items()
        if not spec.get("description")
    ]
    assert undocumented == []


def test_connect_timeout_is_published_in_the_schema():
    module = importlib.import_module("ssh_mcp.mcp_server")

    schemas = {tool.name: tool.input_schema for tool in anyio.run(module.server.list_tools)}

    for tool in ("ssh_execute_command", "ssh_upload_directory", "ssh_download_file"):
        assert "connect_timeout" in schemas[tool]["properties"]


def test_timeout_error_points_at_connect_timeout():
    """The connection budget is the knob that helps; saying otherwise misleads."""
    module = importlib.import_module("ssh_mcp.mcp_server")

    message = module._describe_error(TimeoutError("timed out"))

    assert "connect_timeout" in message
    assert "可加大 timeout" not in message


def test_ssh_execute_command_forwards_connect_timeout(monkeypatch):
    module = importlib.import_module("ssh_mcp.mcp_server")
    seen = {}

    def fake_execute_remote_commands(
        *, commands, host, user, password, ssh_key_filepath, port, timeout, connect_timeout=None, name=None, alias=None
    ):
        seen["connect_timeout"] = connect_timeout
        return "Command: uptime\nExit code: 0\nStdout:\nup\nStderr:\n<empty>"

    monkeypatch.setattr(module, "execute_remote_commands", fake_execute_remote_commands)

    module.ssh_execute_command("uptime", "example.com", "root", "pw", connect_timeout=2.5)

    assert seen["connect_timeout"] == 2.5


def test_oserror_without_errno_loses_the_errno_none_noise():
    """``OSError(None, "msg")`` renders as ``[Errno None] msg``.

    That ``None`` is an artifact of how the library raised the error and means
    nothing to the caller, so it must not reach the message.
    """
    module = importlib.import_module("ssh_mcp.mcp_server")

    message = module._describe_error(OSError(None, "connection reset by peer"))

    assert "[Errno None]" not in message
    assert "connection reset by peer" in message


def test_a_real_errno_is_still_shown():
    module = importlib.import_module("ssh_mcp.mcp_server")

    assert "[Errno 2]" in module._oserror_text(OSError(2, "No such file"))


def test_credential_error_is_not_wrapped_in_a_second_pair_of_brackets():
    """A credential message brings its own brackets; a wrapper nests them."""
    module = importlib.import_module("ssh_mcp.mcp_server")
    from ssh_mcp.credentials import AmbiguousName

    message = module._describe_error(
        AmbiguousName("'192.168.1' 匹配到多台机器：10.0.0.1:22（one，root）。")
    )

    assert message.count("（") == 1
    assert message.count("）") == 1
    assert "ssh_list_hosts" in message


def test_forget_host_refuses_an_ambiguous_name_and_keeps_every_entry(
    monkeypatch, tmp_path
):
    """Regression: an ambiguous name used to delete every match, silently."""
    module = importlib.import_module("ssh_mcp.mcp_server")
    monkeypatch.setenv("SSH_CREDENTIALS_FILE", str(tmp_path / "credentials.json"))
    from ssh_mcp import credentials

    credentials.remember("192.168.11.231", "root", password="a", aliases=["231"])
    credentials.remember("192.168.10.33", "root", password="b", aliases=["33"])

    try:
        module.ssh_forget_host("192.168.1")
        raise AssertionError("Expected ToolError for an ambiguous name")
    except ToolError as exc:
        assert "无法确定删哪一台" in str(exc)
        assert "192.168.11.231" in str(exc)
        assert "192.168.10.33" in str(exc)

    assert len(credentials.load()) == 2


def test_list_hosts_renders_a_machine_without_an_alias_cleanly(monkeypatch, tmp_path):
    """No ``[-]`` placeholder: it read as a broken bracket, not "no alias"."""
    module = importlib.import_module("ssh_mcp.mcp_server")
    monkeypatch.setenv("SSH_CREDENTIALS_FILE", str(tmp_path / "credentials.json"))
    from ssh_mcp import credentials

    credentials.remember("192.168.11.231", "root", password="hunter2")

    output = module.ssh_list_hosts()

    assert "[-]" not in output
    assert "192.168.11.231" in output
    assert "hunter2" not in output
