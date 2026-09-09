# Paramiko Tutorial

一个基于 Python + Paramiko + SCP 的远程主机自动化脚本示例，用于在 SSH 服务器上执行命令，以及上传任意本地目录中的文件到远程主机。

## 项目简介

这个项目演示了如何：

- 通过 SSH 连接远程服务器
- 执行一组远程 shell 命令
- 使用 SCP 批量上传本地文件到远程目录
- 让调用方直接通过参数传入主机、用户、密码、目录等配置
- 适合做接口调用或二次封装
- 使用统一日志输出记录执行过程

它的核心入口在 [main.py](main.py)，并且同时保留了兼容命令行调用方式。

## 功能概览

### 1. 连接远程主机

在 [paramiko_tutorial/server.py](paramiko_tutorial/server.py) 中，定义了 `RemoteClient` 类，负责：

- 建立 SSH 连接
- 处理主机密钥策略
- 创建 SCP 传输通道
- 执行远程命令
- 上传/下载文件
- 关闭连接

### 2. 任意目录上传

[files.py](paramiko_tutorial/files.py) 中的 `fetch_local_files(local_file_dir)` 可以接收任意本地目录，并扫描这个目录下的所有文件，生成要上传的文件路径列表。

### 3. 执行远程命令

`execute_commands()` 会依次执行每条命令，并读取：

- 标准输出
- 标准错误
- 退出状态码

如果某条命令返回非零状态码，会抛出异常并停止后续执行。

## 项目结构

```text
paramiko-tutorial/
├── main.py
├── pyproject.toml
├── README.md
├── files/
├── paramiko_tutorial/
│   ├── __init__.py
│   ├── files.py
│   ├── log.py
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

### [paramiko_tutorial/files.py](paramiko_tutorial/files.py)

用于扫描任意本地目录，获取所有文件路径，供上传使用。

### [paramiko_tutorial/__init__.py](paramiko_tutorial/__init__.py)

对外封装了两个核心接口：

- `upload_directory(...)`：上传任意目录
- `execute_remote_commands(...)`：执行远程命令

### [paramiko_tutorial/log.py](paramiko_tutorial/log.py)

定义了自定义日志格式，使用 `loguru` 统一输出信息。

### [paramiko_tutorial/server.py](paramiko_tutorial/server.py)

实现真实的 Paramiko 连接与 SCP 上传逻辑。

## 直接调用方式（推荐）

### 1. 上传任意目录

```python
from paramiko_tutorial import upload_directory

upload_directory(
    local_dir="/Users/yourname/Desktop/myfiles",
    host="192.168.1.10",
    user="root",
    password="your_password",
    remote_path="/tmp/upload",
)
```

### 2. 执行远程命令

```python
from paramiko_tutorial import execute_remote_commands

execute_remote_commands(
    ["ls -la", "whoami"],
    host="192.168.1.10",
    user="root",
    password="your_password",
)
```

### 3. 直接使用 `RemoteClient`

```python
from paramiko_tutorial.server import RemoteClient

client = RemoteClient(
    host="192.168.1.10",
    user="root",
    password="your_password",
    ssh_key_filepath="/Users/yourname/.ssh/id_rsa",
    remote_path="/tmp/upload",
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
python main.py execute --host 192.168.11.231 --user root --password 'R0ck9' ls
python main.py execute --host 192.168.11.231 --user root --password 'R0ck9' "ls -la"
```

说明：

- `execute` 表示执行远程命令
- `ls` 或 `"ls -la"` 是远程要执行的命令
- 如果密码中带特殊字符，建议用单引号包起来

### 上传本地目录到远程主机

```bash
python main.py upload --host 192.168.11.231 --user root --password 'R0ck9' --remote-path /tmp/upload /Users/yourname/Desktop/myfiles
```

这样可以直接上传任意目录中的文件，而不是必须使用固定的 [files/](files/) 目录。

> 也支持较早的参数顺序：`python main.py --host ... --user ... --password ... execute ls`，但推荐使用上面的写法，语义更清晰。

## 安装依赖

推荐使用 `uv` 管理环境：

```bash
uv sync
```

或者使用 pip：

```bash
pip install .
```

## 设计亮点

- 支持显式参数传入配置
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