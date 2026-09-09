# SSH Tool

一个基于 Python + Paramiko + SCP 的 SSH 远程自动化工具，支持：

- 远程执行命令
- 上传本地目录或文件
- Python 直接调用
- MCP 标准接入

这个项目适合用于服务器运维、部署脚本、批量命令执行和 AI/MCP 场景下的 SSH 工具封装。

## 安装

推荐使用 `uv`：

```bash
uv sync
```

或直接安装：

```bash
pip install .
```

## MCP 接入

这个项目同时支持 Python 调用和 MCP stdio 接入。MCP 入口在 [ssh_tool/mcp_server.py](ssh_tool/mcp_server.py)。

启动命令：

```bash
uv run python -m ssh_tool.mcp_server
```

如果你的 agent 支持 MCP 配置，可直接这样接入：

```json
{
  "mcpServers": {
    "ssh-tool": {
      "command": "uv",
      "args": ["run", "python", "-m", "ssh_tool.mcp_server"],
      "cwd": "/Users/sundonglai/ai/vscode/study/PYTHON/python-ssh"
    }
  }
}
```

可用工具：

- `ssh_execute_command`
- `ssh_upload_directory`

## Python 调用方式

### 1. 执行远程命令

```python
from ssh_tool import execute_remote_commands

execute_remote_commands(
    ["ls -la", "whoami"],
    host="192.168.1.10",
    user="root",
    password="your_password",
    port=2222,
)
```

### 2. 上传目录

```python
from ssh_tool import upload_directory

upload_directory(
    local_dir="/Users/yourname/Desktop/myfiles",
    host="192.168.1.10",
    user="root",
    password="your_password",
    remote_path="/tmp/upload",
    port=2222,
)
```

### 3. 直接使用 `RemoteClient`

```python
from ssh_tool.server import RemoteClient

client = RemoteClient(
    host="192.168.1.10",
    user="root",
    password="your_password",
    ssh_key_filepath="/Users/yourname/.ssh/id_rsa",
    remote_path="/tmp/upload",
    port=2222,
)

try:
    client.bulk_upload(["/Users/yourname/Desktop/a.txt", "/Users/yourname/Desktop/b.txt"])
finally:
    client.close()
```

## 命令行调用方式

```bash
python main.py execute --host 192.168.11.231 --user root --password 'R0ck9' --port 2222 "ls -la"
python main.py upload --host 192.168.11.231 --user root --password 'R0ck9' --port 2222 --remote-path /tmp/upload /Users/yourname/Desktop/myfiles
```

## 项目结构

```text
ssh-tool/
├── main.py
├── pyproject.toml
├── README.md
├── ssh_tool/
│   ├── __init__.py
│   ├── client.py
│   ├── files.py
│   ├── log.py
│   ├── mcp_server.py
│   └── server.py
└── LICENSE
```

## 说明

- [ssh_tool/server.py](ssh_tool/server.py) 负责 SSH 连接与 SCP 传输
- [ssh_tool/files.py](ssh_tool/files.py) 负责扫描待上传文件
- [ssh_tool/mcp_server.py](ssh_tool/mcp_server.py) 负责 MCP tool 暴露
- [main.py](main.py) 负责 CLI 入口

## 设计亮点

- 适合 Python 直接调用
- 适合 MCP 代理接入
- 支持自定义 SSH 端口
- 支持上传任意目录
- 支持批量命令执行

## 许可证

MIT License.

## 项目结构

```text
ssh-tool/
├── main.py
├── pyproject.toml
├── README.md
├── ssh_tool/
│   ├── __init__.py
│   ├── client.py
│   ├── files.py
│   ├── log.py
│   ├── mcp_server.py
│   └── server.py
└── LICENSE
```

## 关键模块说明

### [main.py](main.py)

脚本入口：

```python
if __name__ == "__main__":
    run(sys.argv[1:])
```

它会将命令行参数传给 `run()`，兼容旧的 CLI 调用方式。

### [ssh_tool/files.py](ssh_tool/files.py)

用于扫描任意本地目录，获取所有文件路径，供上传使用。

### [ssh_tool/__init__.py](ssh_tool/__init__.py)

对外封装了两个核心接口：

- `upload_directory(...)`：上传任意目录
- `execute_remote_commands(...)`：执行远程命令

### [ssh_tool/log.py](ssh_tool/log.py)

定义了自定义日志格式，使用 `loguru` 统一输出信息。

### [ssh_tool/server.py](ssh_tool/server.py)

实现真实的 Paramiko 连接与 SCP 上传逻辑。

## 直接调用方式（推荐）

### 1. 上传任意目录

```python
from ssh_tool import upload_directory

upload_directory(
    local_dir="/Users/yourname/Desktop/myfiles",
    host="192.168.1.10",
    user="root",
    password="your_password",
    remote_path="/tmp/upload",
    port=2222,
)
```

### 2. 执行远程命令

```python
from ssh_tool import execute_remote_commands

execute_remote_commands(
    ["ls -la", "whoami"],
    host="192.168.1.10",
    user="root",
    password="your_password",
    port=2222,
)
```

### 3. 直接使用 `RemoteClient`

```python
from ssh_tool.server import RemoteClient

client = RemoteClient(
    host="192.168.1.10",
    user="root",
    password="your_password",
    ssh_key_filepath="/Users/yourname/.ssh/id_rsa",
    remote_path="/tmp/upload",
    port=2222,
)

try:
    client.bulk_upload(["/Users/yourname/Desktop/a.txt", "/Users/yourname/Desktop/b.txt"])
finally:
    client.close()
```

## 命令行调用方式

推荐使用下面这种显式参数形式，参数顺序更清晰，也更适合脚本和接口调用：

### 执行远程命令

```bash
python main.py execute --host 192.168.11.231 --user root --password 'R0ck9' --port 2222 ls
python main.py execute --host 192.168.11.231 --user root --password 'R0ck9' --port 2222 "ls -la"
```

说明：

- `execute` 表示执行远程命令
- `--port` 指定 SSH 端口，默认值为 `22`
- `ls` 或 `"ls -la"` 是远程要执行的命令
- 如果密码中带特殊字符，建议用单引号包起来

### 上传本地目录到远程主机

```bash
python main.py upload --host 192.168.11.231 --user root --password 'R0ck9' --port 2222 --remote-path /tmp/upload /Users/yourname/Desktop/myfiles
```

这样可以直接上传任意目录中的文件，而不是必须使用固定的 [files/](files/) 目录。

> 也支持较早的参数顺序：`python main.py --host ... --user ... --password ... --port 2222 execute ls`，但推荐使用上面的写法，语义更清晰。

## 安装依赖

推荐使用 `uv` 管理环境：

```bash
uv sync
```

或者使用 pip：

```bash
pip install .
```

## MCP 接入方式

这个项目同时支持 Python 直接调用和标准 MCP stdio 接入。MCP 入口在 [ssh_tool/mcp_server.py](ssh_tool/mcp_server.py)，启动方式如下：

```bash
uv run python -m ssh_tool.mcp_server
```

如果你的 agent 支持 MCP 配置，可以直接这样接入：

```json
{
  "mcpServers": {
    "ssh-tool": {
      "command": "uv",
      "args": ["run", "python", "-m", "ssh_tool.mcp_server"],
      "cwd": "/Users/sundonglai/ai/vscode/study/PYTHON/python-ssh"
    }
  }
}
```

这样可以在支持 MCP 的 agent 中直接调用：

- `ssh_execute_command`
- `ssh_upload_directory`

## 设计亮点

- 支持显式参数传入配置
- 支持自定义 SSH 端口（默认 22）
- 支持上传任意目录
- 支持批量命令执行和批量文件上传
- 适合二次封装为外部接口或 SDK
- 保留 CLI 兼容入口

## 适用场景

适合以下场景：

- 通过 Python 接口调用远程主机
- 自动同步本地脚本到远程服务器
- 执行远程部署任务
- 批量处理服务器日志
- 作为内部工具库被其他项目复用

## 许可证

本项目使用 MIT License。

## 说明

目前这个版本更偏“接口化设计”，即适合被其他服务或脚本调用，而不是单纯依赖项目本地配置文件。对于需要快速接入、二次封装或调用方传参的场景，这种形式更稳妥。