"""Package entrypoint for the ssh-mcp CLI."""

import sys

from .client import run


def main() -> None:
    """Execute the CLI from the package and propagate its exit code."""
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
