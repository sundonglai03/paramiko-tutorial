from unittest.mock import Mock

from paramiko_tutorial.server import RemoteClient


def test_bulk_upload_supports_directory_and_single_file(tmp_path):
    client = RemoteClient(
        host="example.com",
        user="root",
        password="",
        ssh_key_filepath="",
        remote_path="/tmp",
    )
    client.scp_client = Mock()

    directory = tmp_path / "remote_dir"
    directory.mkdir()
    file_path = tmp_path / "single.txt"
    file_path.write_text("hello")

    client.bulk_upload(str(directory))
    client.scp_client.put.assert_called_with(
        str(directory), remote_path="/tmp", recursive=True
    )

    client.scp_client.put.reset_mock()
    client.bulk_upload(str(file_path))
    client.scp_client.put.assert_called_with(
        str(file_path), remote_path="/tmp", recursive=False
    )
