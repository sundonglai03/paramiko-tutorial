import importlib


def test_ssh_tool_package_is_importable():
    module = importlib.import_module("ssh_tool")
    assert hasattr(module, "upload_directory")
    assert hasattr(module, "execute_remote_commands")
    assert hasattr(module, "RemoteClient")
