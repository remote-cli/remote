from pathlib import Path
from unittest.mock import ANY, MagicMock, call, patch

import pytest

from remote.configuration import RemoteConfig
from remote.workspace import SyncedWorkspace


@pytest.fixture
def workspace(workspace_config):
    workspace_config.ignores.pull.append("build")
    working_dir = workspace_config.root / "foo" / "bar"
    working_dir.mkdir(parents=True)
    return SyncedWorkspace.from_config(workspace_config, working_dir)


def test_create_workspace(workspace_config):
    working_dir = workspace_config.root / "foo" / "bar"
    workspace = SyncedWorkspace.from_config(workspace_config, working_dir)

    assert workspace.local_root == workspace_config.root
    assert workspace.remote == workspace_config.configurations[0]
    assert workspace.remote_working_dir == workspace_config.configurations[0].directory / "foo" / "bar"
    assert workspace.ignores == workspace_config.ignores


def test_create_workspace_selects_proper_remote_host(workspace_config):
    working_dir = workspace_config.root / "foo" / "bar"
    workspace_config.configurations.append(
        RemoteConfig(
            host="other-host.example.com", directory=Path("other/dir"), shell="bash", shell_options="some options"
        )
    )
    workspace_config.default_configuration = 1

    # workspace should select host from workspace_config.default_configuration
    workspace = SyncedWorkspace.from_config(workspace_config, working_dir)
    assert workspace.local_root == workspace_config.root
    assert workspace.remote == workspace_config.configurations[1]
    assert workspace.remote_working_dir == workspace_config.configurations[1].directory / "foo" / "bar"
    assert workspace.ignores == workspace_config.ignores

    # now it should select host from overrid
    workspace = SyncedWorkspace.from_config(workspace_config, working_dir, config_num=0)
    assert workspace.local_root == workspace_config.root
    assert workspace.remote == workspace_config.configurations[0]
    assert workspace.remote_working_dir == workspace_config.configurations[0].directory / "foo" / "bar"
    assert workspace.ignores == workspace_config.ignores


@patch("remote.util.subprocess.run")
def test_clear_remote_workspace(mock_run, workspace):
    mock_run.return_value = MagicMock(returncode=0)

    workspace.clear_remote()

    # clear should always delete remote root regardless of what the workign dir is
    mock_run.assert_called_once_with(
        ["ssh", "-tKq", workspace.remote.host, f"rm -rf {workspace.remote.directory}"],
        stderr=ANY,
        stdin=ANY,
        stdout=ANY,
    )


@patch("remote.util.subprocess.run")
def test_push(mock_run, workspace):
    mock_run.return_value = MagicMock(returncode=0)

    workspace.push()
    mock_run.assert_called_once_with(
        [
            "rsync",
            "-rlpmchz",
            "--copy-unsafe-links",
            "-e",
            "ssh -q",
            "--force",
            f"{workspace.local_root}/",
            f"{workspace.remote.host}:{workspace.remote.directory}",
        ],
        stderr=ANY,
        stdout=ANY,
    )


@patch("remote.util.subprocess.run")
def test_pull(mock_run, workspace):
    mock_run.return_value = MagicMock(returncode=0)

    workspace.pull()
    mock_run.assert_called_once_with(
        [
            "rsync",
            "-rlpmchz",
            "--copy-unsafe-links",
            "-e",
            "ssh -q",
            "--force",
            "--exclude-from",
            ANY,
            f"{workspace.remote.host}:{workspace.remote.directory}/",
            f"{workspace.local_root}",
        ],
        stderr=ANY,
        stdout=ANY,
    )


@patch("remote.util.subprocess.run")
def test_pull_with_subdir(mock_run, workspace):
    mock_run.return_value = MagicMock(returncode=0)

    workspace.pull(subpath="some-path")
    mock_run.assert_called_once_with(
        [
            "rsync",
            "-rlpmchz",
            "--copy-unsafe-links",
            "-e",
            "ssh -q",
            "--force",
            f"{workspace.remote.host}:{workspace.remote.directory}/some-path",
            f"{workspace.local_root}/some-path",
        ],
        stderr=ANY,
        stdout=ANY,
    )


@patch("remote.util.subprocess.run")
def test_execute(mock_run, workspace):
    mock_run.return_value = MagicMock(returncode=0)

    code = workspace.execute(["echo", "Hello World!"])
    mock_run.assert_called_once_with(
        [
            "ssh",
            "-tKq",
            workspace.remote.host,
            """\
if [ -f remote/dir/.remoteenv ]; then
  source remote/dir/.remoteenv 2>/dev/null 1>/dev/null
fi
cd remote/dir/foo/bar
echo 'Hello World!'
""",
        ],
        stderr=ANY,
        stdin=ANY,
        stdout=ANY,
    )
    assert code == 0


@patch("remote.util.subprocess.run")
def test_execute_and_sync(mock_run, workspace):
    mock_run.side_effect = [MagicMock(returncode=0), MagicMock(returncode=10), MagicMock(returncode=0)]

    code = workspace.execute_in_synced_env(["echo", "Hello World!"])
    mock_run.assert_has_calls(
        [
            call(
                [
                    "rsync",
                    "-rlpmchz",
                    "--copy-unsafe-links",
                    "-e",
                    "ssh -q",
                    "--force",
                    f"{workspace.local_root}/",
                    f"{workspace.remote.host}:{workspace.remote.directory}",
                ],
                stderr=ANY,
                stdout=ANY,
            ),
            call(
                [
                    "ssh",
                    "-tKq",
                    workspace.remote.host,
                    """\
if [ -f remote/dir/.remoteenv ]; then
  source remote/dir/.remoteenv 2>/dev/null 1>/dev/null
fi
cd remote/dir/foo/bar
echo 'Hello World!'
""",
                ],
                stderr=ANY,
                stdin=ANY,
                stdout=ANY,
            ),
            call(
                [
                    "rsync",
                    "-rlpmchz",
                    "--copy-unsafe-links",
                    "-e",
                    "ssh -q",
                    "--force",
                    "--exclude-from",
                    ANY,
                    f"{workspace.remote.host}:{workspace.remote.directory}/",
                    f"{workspace.local_root}",
                ],
                stderr=ANY,
                stdout=ANY,
            ),
        ]
    )
    assert code == 10
