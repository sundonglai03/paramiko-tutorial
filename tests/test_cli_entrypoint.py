import importlib


def test_package_entrypoint_exists():
    module = importlib.import_module("ssh_mcp.__main__")
    assert hasattr(module, "main")
    assert callable(module.main)
