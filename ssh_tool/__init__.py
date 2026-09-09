"""Public API for the MCP SSH project.

This package supports both:
- direct Python usage
- MCP integration via the server entrypoint
"""

from .client import execute_remote_commands, run, upload_directory
from .server import RemoteClient

__all__ = [
    "RemoteClient",
    "upload_directory",
    "execute_remote_commands",
    "run",
]
