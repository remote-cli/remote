from time import sleep
from unittest.mock import ANY, MagicMock, patch

from remote.file_changes import execute_on_file_change


@patch("remote.util.subprocess.run")
def test_stream_changes_when_event_triggered(mock_run, workspace):
    """workspace pull is called when a file is created."""
    mock_run.return_value = MagicMock(returncode=0)
    with execute_on_file_change(local_root=workspace.local_root, callback=workspace.push, settle_time=0.01):
        (workspace.local_root / "foo.txt").touch()
        # Mock command execution behavior.
        sleep(0.3)
    mock_run.assert_called_once_with(
        [
            "rsync",
            "-arlpmchz",
            "--copy-unsafe-links",
            "-e",
            "ssh -Kq -o BatchMode=yes",
            "--force",
            "--delete",
            "--rsync-path",
            "mkdir -p remote/dir && rsync",
            "--include-from",
            ANY,
            f"{workspace.local_root}/",
            f"{workspace.remote.host}:{workspace.remote.directory}",
        ],
        stderr=ANY,
        stdout=ANY,
    )


@patch("remote.util.subprocess.run")
def test_stream_changes_when_no_event_triggered(mock_run, workspace):
    """Local sources should not be synced as nothing changed."""
    mock_run.return_value = MagicMock(returncode=0)
    with execute_on_file_change(local_root=workspace.local_root, callback=workspace.push, settle_time=0.01):
        # Mock command execution behavior.
        sleep(0.3)
    assert not mock_run.called
