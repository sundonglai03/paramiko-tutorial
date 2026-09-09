"""MCP server wrapper for SSH operations.

This module registers real MCP tools for SSH command execution and directory
upload while keeping the plain Python API available from the same package.
"""

from __future__ import annotations

import anyio
from mcp.server.mcpserver import MCPServer

from .client import execute_remote_commands, upload_directory


server = MCPServer("ssh-tool")


@server.tool(name="ssh_execute_command", description="Run a command on a remote SSH host.")
def ssh_execute_command(
    command: str,
    host: str,
    user: str,
    password: str | None = None,
    ssh_key_filepath: str | None = None,
    port: int = 22,
) -> str:
    """Execute a remote SSH command."""
    execute_remote_commands(
        commands=[command],
        host=host,
        user=user,
        password=password,
        ssh_key_filepath=ssh_key_filepath,
        port=port,
    )
    return f"SSH command executed successfully: {command}"


@server.tool(name="ssh_upload_directory", description="Upload a local directory to a remote SSH host.")
def ssh_upload_directory(
    local_dir: str,
    host: str,
    user: str,
    password: str | None = None,
    ssh_key_filepath: str | None = None,
    remote_path: str = "/tmp",
    port: int = 22,
) -> str:
    """Upload a local directory via SCP over SSH."""
    upload_directory(
        local_dir=local_dir,
        host=host,
        user=user,
        password=password,
        ssh_key_filepath=ssh_key_filepath,
        remote_path=remote_path,
        port=port,
    )
    return f"SSH upload completed: {local_dir}"


def create_mcp_server() -> MCPServer:
    """Return the MCP server instance for this SSH project."""
    return server


async def main() -> None:
    """Run the SSH tool server over stdio transport for MCP clients."""
    await server.run_stdio_async()


if __name__ == "__main__":
    anyio.run(main)
