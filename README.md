# ssh-mcp

基于 Python + Paramiko + SCP 的 SSH 远程自动化工具：远程执行命令、上传目录/文件、下载文件。
支持密码或密钥认证、自定义端口。

| 用法 | 入口 | 适合场景 |
| --- | --- | --- |
| MCP 工具 | `python -m ssh_mcp.mcp_server` | 让 AI agent 直接远程运维 |
| 命令行 | `ssh-mcp execute ...` | 人工操作、写 shell 脚本 |
| Python API | `from ssh_mcp import execute_remote_commands` | 嵌进自己的服务或部署脚本 |

---

## 安装

```bash
cd /path/to/ssh-mcp
uv sync          # 建 venv、按 uv.lock 装依赖，并把本项目本身装进去
```

装完得到两样东西：

- **CLI**：`/path/to/ssh-mcp/.venv/bin/ssh-mcp`
- **供 MCP 客户端启动的解释器**：`/path/to/ssh-mcp/.venv/bin/python`

下面一律用 `.venv/bin/...` 全路径（避免"没激活 venv"这类低级失败）。想用短命令就先
`source .venv/bin/activate`。

`uv` 只用来建环境，**不要用 `uv run` 启动 MCP server**——原因见下节。

### 装完先自测

接进 MCP 客户端之前先用 CLI 打通一次。这一步能把「环境 / 网络问题」和「MCP 配置问题」分开，
避免两头一起查：

```bash
/path/to/ssh-mcp/.venv/bin/ssh-mcp execute \
  --host 192.168.11.223 --user root --password 'pw' --alias 223 "uptime"
```

成功会打印 `Command` / `Exit code` / `Stdout` / `Stderr` 四段。走到这里说明依赖装好了、SSH 通了，
顺带把凭据缓存了（见第二节）——再往上接 MCP 就是纯配置问题。

---

## 一、MCP 接入

在客户端的 MCP 配置文件里加入下面这个条目（现成可抄的版本见 `mcp_config_example.json`，
那个文件里的 `command` 已经填好本机路径，直接复制即可）：

```json
{
  "mcpServers": {
    "ssh-mcp": {
      "command": "/Users/sundonglai/ai/vscode/study/PYTHON/ssh-mcp/.venv/bin/python",
      "args": ["-m", "ssh_mcp.mcp_server"],
      "env": { "SSH_LOG_LEVEL": "INFO" }
    }
  }
}
```

上面这段就是本机的真实路径，可直接复制使用；换机器或项目搬家时，把 `/Users/sundonglai/ai/vscode/study/PYTHON/ssh-mcp`
换成新的项目绝对路径（也就是上一步 `cd` 进去的那个目录）即可。

> 用 `.venv/bin/python` 的绝对路径启动，**不要写 `cwd`、不要用 `uv run`**：部分客户端在 stdio 模式下
> 会把 `cwd` 丢掉，依赖它解析项目的启动串会直接 `Connection closed`。`uv` 只用来建环境。
>
> 连接信息**不写在这里**。每次工具调用自带 `host` / `user`，所以同一个 server 可以连任意多台设备，
> 换机器不用改配置、不用重启。
>
> 改完配置要**让客户端重新加载**：重开一个会话，或在连接器管理里重连这个 MCP。常驻的 stdio 进程
> 不会自己换成新版本——改完本项目代码也一样，必须重连才生效。

### 工具

| 工具 | 必填参数 | 说明 |
| --- | --- | --- |
| `ssh_execute_command` | `command` | 执行远程命令，返回命令 / 退出码 / stdout / stderr |
| `ssh_upload_directory` | `local_dir` | 上传本地目录或文件；按 `scp -r` 语义保留目录名（`/local/x` → `remote_path/x`） |
| `ssh_download_file` | `remote_file` | 下载单个文件；不传 `local_path` 则落到系统临时目录 |
| `ssh_list_hosts` | — | 列出已缓存的机器（不含密码） |
| `ssh_forget_host` | `name` | 删掉某台机器的缓存；一次只删一台，名字命中多台时报错且一台都不删 |

### 连接目标：两种给法

**① 显式传参** —— 不依赖任何状态，想连哪台就连哪台：

```
ssh_execute_command(command="df -h", host="192.168.10.36", user="root", password="...")
ssh_execute_command(command="uptime", host="192.168.11.223", user="root", ssh_key_filepath="/keys/id_ed25519", port=2222)
```

**② 用名字** —— 该机器此前成功连过一次：

```
ssh_execute_command(command="uptime", name="223")
```

首次连接时顺手把你平时的叫法交给 `alias`，之后就能用这个名字：

```
ssh_execute_command(command="uptime", host="192.168.11.223", user="root", password="...", alias="223")
```

名字的匹配顺序是：**别名精确 → host 精确 → host 子串**（`223` 能匹配到 `192.168.11.223`）。
命中多台时**直接报错并列出候选，不会挑一个像的**——猜错就是往错误的机器上跑命令。
显式参数永远优先于缓存，所以临时换端口或换用户不需要改缓存。

命令超时默认 30 秒，超时返回退出码 `124` 并保留已产生的输出；要「非零退出即算失败」传 `fail_on_error: true`。
连接超时是另一个参数（`connect_timeout`，默认 10 秒，见下节）。
失败时返回带分类的可读错误（认证失败 / 主机无法解析 / 端口不通 / 连接超时 / 路径不存在 / 权限不足 / SCP 失败 / 名字歧义）。

---

## 二、连接参数与凭据缓存

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `host` | 见下 | — | 远程主机地址 |
| `user` | 见下 | — | SSH 用户名 |
| `password` | 否 | 无 | 密码认证 |
| `ssh_key_filepath` | 否 | 无 | 密钥认证；与密码二选一，都不传则回退 ssh-agent / `~/.ssh` 默认密钥 |
| `port` | 否 | `22` | SSH 端口 |
| `timeout` | 否 | `30` | **单条命令**的执行超时（秒） |
| `connect_timeout` | 否 | `10` | **建立连接**（TCP + SSH 握手）的超时（秒） |
| `remote_path` | 否 | `/tmp` | 上传目标目录 |
| `name` | 见下 | — | 已缓存机器的名字 / 别名 / host 片段 |
| `alias` | 否 | — | 这次连接成功后，顺便把该机器记成这个名字 |

`host` + `user` 和 `name` **二选一**：前者描述一台机器，后者指向缓存里的一台机器。都没有则报错。
连接信息**不来自环境变量**；只有两个与连接无关的变量会被读取：`SSH_LOG_LEVEL`（日志级别）、
`SSH_CREDENTIALS_FILE`（缓存文件位置）。

### 两个超时是独立的

这两个参数名字像、作用完全不同，别混：

| | `timeout` | `connect_timeout` |
| --- | --- | --- |
| 管什么 | 单条命令跑多久 | TCP 连接 + SSH 握手 |
| 超了会怎样 | **不报错**：返回 `Exit code: 124`，并带上命令已产生的输出 | **整个调用失败**，错误里点名 `connect_timeout` |
| 什么时候调 | 命令本身跑得久（编译、拉镜像、大范围 `find`） | 主机能 ping 通但握手慢，或网络抖动 |

**连不上主机时调 `timeout` 是没用的** —— 它管不到连接阶段。

### 缓存规则

连接**成功**之后，工具会把该机器的连接信息记到 `~/.ssh-mcp/credentials.json`（权限 `0600`，目录 `0700`）。
用户以后说「223 那台」时，agent 用 `name="223"` 就能直接连上，不必再要账号密码。

设计上刻意收紧的几点：

- **只有连成功才写档。** 认证失败绝不写入，否则错密码被固化下来，之后每次都错。
- **显式参数优先于缓存。** 缓存只是兜底，不覆盖调用方给的值。
- **名字歧义直接报错。** 宁可让调用方补一个 host，也不猜一台机器。删除同样如此：
  `ssh_forget_host` 一次只删一台，名字命中多台时报错并列出候选、**一台都不删** ——
  删除不可撤销，更不能交给一个「大概对」的匹配去决定。
- **只记显式给的 `alias`。** 用 `name="192.168.11"` 这类片段命中的调用**不会**把该片段存成别名 ——
  否则一次性的写法会被永久固化，把 `ssh_list_hosts` 的输出弄乱。
- **缓存写失败不影响命令结果。** 已执行的命令结果照常返回，只记一条 warning 日志。
- **密码是明文落盘的**（这是明确选择）：保护手段是文件权限，不是加密。不想留就 `ssh_forget_host`。
  路径可用 `SSH_CREDENTIALS_FILE` 环境变量改到别处——它只决定缓存文件位置，与连接无关。

---

## 三、命令行

```bash
# 首次：显式传参，成功即被记住（--alias 顺手起个名字）
ssh-mcp execute --host 10.0.0.10 --user root --password 'pw' --alias 十号机 "ls -la"

# 之后：直接用名字
ssh-mcp execute --name 十号机 "uptime"

ssh-mcp upload   --host 10.0.0.10 --user root --password 'pw' --remote-path /tmp/upload ./myfiles
ssh-mcp download --host 10.0.0.10 --user root --password 'pw' --local-path ./app.log /var/log/app.log

ssh-mcp --list-hosts          # 看已缓存了哪些机器
ssh-mcp --forget 十号机        # 忘掉一台（名字命中多台会报错，不会一次删掉多台）
```

`--host` + `--user` 与 `--name` 二选一。其它参数：`--alias`、`--ssh-key-filepath`、`--port`、`--timeout`（单条命令执行超时）、`--connect-timeout`（建连超时）、`--version`。
上面写成短命令 `ssh-mcp` 是假设 venv 已激活；没激活就用全路径 `/path/to/ssh-mcp/.venv/bin/ssh-mcp`。

---

## 四、Python API

```python
from ssh_mcp import execute_remote_commands, upload_directory, download_file

# 显式传参
print(execute_remote_commands(["ls -la"], host="10.0.0.10", user="root", password="pw"))

# 成功连过之后，用名字即可（alias 记下这次的称呼）
print(execute_remote_commands(["uptime"], host="10.0.0.10", user="root", password="pw", alias="十号机"))
print(execute_remote_commands(["uptime"], name="十号机"))
```

需要复用一条连接做多件事时用 `RemoteClient`：

```python
from ssh_mcp import RemoteClient

client = RemoteClient(host="10.0.0.10", user="root", password="pw",
                      ssh_key_filepath="", remote_path="/tmp/upload", port=22)
try:
    print(client.execute_commands(["ls -la"]))
    client.bulk_upload("./dist")
    print(client.download_file("/var/log/app.log", local_path="./app.log"))
finally:
    client.close()
```

---

## 五、开发

```bash
uv sync                      # 建/更新环境（不用它启动）
.venv/bin/python -m pytest   # 运行测试
```

---

## 许可证

MIT
