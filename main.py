"""脚本入口。"""

import sys

from ssh_tool import run


if __name__ == "__main__":
    run(sys.argv[1:])