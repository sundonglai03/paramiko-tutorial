import importlib


def test_mcp_server_module_exists():
    module = importlib.import_module("ssh_tool.mcp_server")
    assert hasattr(module, "create_mcp_server")
    assert hasattr(module, "ssh_execute_command")
    assert hasattr(module, "ssh_upload_directory")
