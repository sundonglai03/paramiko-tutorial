"""SSH and SCP client implementation."""

import os
from typing import List

from paramiko import AutoAddPolicy, SSHClient
from paramiko.auth_handler import AuthenticationException
from scp import SCPClient, SCPException

from .log import LOGGER


class RemoteClient:
    """Connect to a remote host over SSH and upload or execute commands."""

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        ssh_key_filepath: str,
        remote_path: str,
        port: int = 22,
    ):
        self.host = host
        self.user = user
        self.password = password
        self.ssh_key_filepath = ssh_key_filepath
        self.remote_path = remote_path
        self.port = port
        self.client: SSHClient | None = None
        self.scp_client: SCPClient | None = None

    @property
    def connection(self) -> SSHClient:
        """Open and cache the SSH connection."""
        if self.client is not None:
            return self.client
        try:
            self.client = SSHClient()
            self.client.load_system_host_keys()
            self.client.set_missing_host_key_policy(AutoAddPolicy())

            connect_kwargs = {
                "username": self.user,
                "port": self.port,
                "timeout": 10,
            }
            if self.password:
                connect_kwargs["password"] = self.password
            if self.ssh_key_filepath:
                connect_kwargs["key_filename"] = self.ssh_key_filepath

            self.client.connect(self.host, **connect_kwargs)
            return self.client
        except AuthenticationException as e:
            LOGGER.error(f"认证异常：你是否忘记生成 SSH 密钥？{e}")
            raise
        except Exception as e:
            LOGGER.error(f"连接远程主机时发生未知错误：{e}")
            raise

    @property
    def scp(self) -> SCPClient:
        if self.scp_client is not None:
            return self.scp_client
        conn = self.connection
        self.scp_client = SCPClient(conn.get_transport())
        return self.scp_client

    def close(self) -> None:
        """Close the SSH and SCP connections."""
        if self.scp_client is not None:
            self.scp_client.close()
            self.scp_client = None

        if self.client is not None:
            self.client.close()
            self.client = None

    def bulk_upload(self, filepaths: str | List[str], recursive: bool | None = None) -> None:
        """Upload one file, one directory, or a list of paths to the remote host."""
        try:
            if isinstance(filepaths, (str, os.PathLike)):
                local_path = str(filepaths)
                recursive_flag = os.path.isdir(local_path) if recursive is None else recursive
                self.scp.put(local_path, remote_path=self.remote_path, recursive=recursive_flag)
                label = "目录" if recursive_flag else "文件"
                LOGGER.info(
                    f"已完成上传 1 个{label}到 {self.remote_path}（主机：{self.host}）"
                )
                return

            self.scp.put(filepaths, remote_path=self.remote_path, recursive=True)
            LOGGER.info(
                f"已完成上传 {len(filepaths)} 个文件到 {self.remote_path}（主机：{self.host}）"
            )
        except SCPException as e:
            LOGGER.error(f"批量上传过程中发生 SCPException：{e}")
            raise
        except Exception as e:
            LOGGER.error(f"批量上传过程中发生未知异常：{e}")
            raise

    def download_file(self, filepath: str) -> None:
        """Download a file from the remote host."""
        try:
            self.scp.get(filepath)
            LOGGER.info(f"已从 {self.host} 下载 {filepath}")
        except SCPException as e:
            LOGGER.error(f"下载文件过程中发生 SCPException：{e}")
            raise
        except Exception as e:
            LOGGER.error(f"下载文件过程中发生未知异常：{e}")
            raise

    def execute_commands(self, commands: List[str]) -> None:
        """Execute a sequence of commands on the remote host."""
        conn = self.connection

        for cmd in commands:
            _, stdout, stderr = conn.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()
            output = stdout.read().decode()
            error = stderr.read().decode()

            if output:
                LOGGER.info(f"输入: {cmd}\n输出: {output}")

            if error:
                LOGGER.error(f"输入: {cmd}\n错误: {error}")

            if exit_status != 0:
                LOGGER.error(f"命令执行失败: {cmd}\n退出状态: {exit_status}")
                raise RuntimeError(f"远程命令失败: {cmd}（退出状态: {exit_status}）")
