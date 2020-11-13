import sys

from pathlib import Path
from unittest.mock import ANY, MagicMock, call, patch

import pytest

from remote.configuration import RemoteConfig
from remote.exceptions import InvalidRemoteHostLabel
from remote.util import CommunicationOptions, ForwardingOption
from remote.workspace import CompiledSyncRules, SyncedWorkspace


def test_create_workspace(workspace_config):
    working_dir = workspace_config.root / "foo" / "bar"
    workspace = SyncedWorkspace.from_config(workspace_config, working_dir)

    assert workspace.local_root == workspace_config.root
    assert workspace.remote == workspace_config.configurations[0]
    assert workspace.remote_working_dir == workspace_config.configurations[0].directory / "foo" / "bar"
    assert workspace.pull_rules == CompiledSyncRules([], [])
    assert workspace.push_rules == CompiledSyncRules([], ["/.remoteenv"])


def test_create_workspace_selects_proper_remote_host(workspace_config):
    working_dir = workspace_config.root / "foo" / "bar"
    workspace_config.configurations.append(
        RemoteConfig(
            host="other-host.example.com",
            directory=Path("other/dir"),
            shell="bash",
            shell_options="some options",
            label="bar",
        )
    )
    workspace_config.configurations.append(
        RemoteConfig(
            host="foo.example.com", directory=Path("other/dir"), shell="bash", shell_options="some options", label="foo"
        )
    )

    workspace_config.default_configuration = 1

    # workspace should select host from workspace_config.default_configuration
    workspace = SyncedWorkspace.from_config(workspace_config, working_dir)
    assert workspace.local_root == workspace_config.root
    assert workspace.remote == workspace_config.configurations[1]
    assert workspace.remote_working_dir == workspace_config.configurations[1].directory / "foo" / "bar"
    assert workspace.pull_rules == CompiledSyncRules([], [])
    assert workspace.push_rules == CompiledSyncRules([], ["/.remoteenv"])
    assert workspace.remote.label == "bar"

    # now it should select host from override
    workspace = SyncedWorkspace.from_config(workspace_config, working_dir, remote_host_id=0)
    assert workspace.local_root == workspace_config.root
    assert workspace.remote == workspace_config.configurations[0]
    assert workspace.remote_working_dir == workspace_config.configurations[0].directory / "foo" / "bar"
    assert workspace.pull_rules == CompiledSyncRules([], [])
    assert workspace.push_rules == CompiledSyncRules([], ["/.remoteenv"])

    # now it should select from the label passed
    workspace = SyncedWorkspace.from_config(workspace_config, working_dir, remote_host_id="foo")
    assert workspace.local_root == workspace_config.root
    assert workspace.remote == workspace_config.configurations[2]
    assert workspace.remote_working_dir == workspace_config.configurations[2].directory / "foo" / "bar"
    assert workspace.pull_rules == CompiledSyncRules([], [])
    assert workspace.push_rules == CompiledSyncRules([], ["/.remoteenv"])
    assert workspace_config.configurations[2].label == "foo"

    # now it should raise an exception as the label is not present
    with pytest.raises(InvalidRemoteHostLabel):
        workspace = SyncedWorkspace.from_config(workspace_config, working_dir, remote_host_id="iamnotpresent")


@patch("remote.util.subprocess.run")
def test_clear_remote_workspace(mock_run, workspace):
    mock_run.return_value = MagicMock(returncode=0)

    workspace.clear_remote()

    # clear should always delete remote root regardless of what the workign dir is
    mock_run.assert_called_once_with(
        ["ssh", "-tKq", "-o", "BatchMode=yes", workspace.remote.host, f"rm -rf {workspace.remote.directory}"],
        stderr=sys.stderr,
        stdin=sys.stdin,
        stdout=sys.stdout,
    )


@patch("remote.util.subprocess.run")
def test_push(mock_run, workspace):
    mock_run.return_value = MagicMock(returncode=0)

    workspace.push()
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
        stderr=sys.stderr,
        stdout=sys.stdout,
    )


@patch("remote.util.subprocess.run")
def test_push_with_subdir(mock_run, workspace):
    mock_run.return_value = MagicMock(returncode=0)

    workspace.push(subpath=Path("some-path"))
    mock_run.assert_called_once_with(
        [
            "rsync",
            "-arlpmchz",
            "--copy-unsafe-links",
            "-e",
            "ssh -Kq -o BatchMode=yes",
            "--force",
            "--delete",
            f"{workspace.local_root}/foo/bar/some-path",
            f"{workspace.remote.host}:{workspace.remote.directory}/foo/bar/",
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
            "-arlpmchz",
            "--copy-unsafe-links",
            "-e",
            "ssh -Kq -o BatchMode=yes",
            "--force",
            "--exclude-from",
            ANY,
            f"{workspace.remote.host}:{workspace.remote.directory}/",
            f"{workspace.local_root}",
        ],
        stderr=sys.stderr,
        stdout=sys.stdout,
    )


@patch("remote.util.subprocess.run")
def test_pull_with_subdir(mock_run, workspace):
    mock_run.return_value = MagicMock(returncode=0)

    workspace.pull(subpath=Path("some-path"))
    mock_run.assert_called_once_with(
        [
            "rsync",
            "-arlpmchz",
            "--copy-unsafe-links",
            "-e",
            "ssh -Kq -o BatchMode=yes",
            "--force",
            f"{workspace.remote.host}:{workspace.remote.directory}/foo/bar/some-path",
            f"{workspace.local_root}/foo/bar/",
        ],
        stderr=sys.stderr,
        stdout=sys.stdout,
    )


@patch("remote.util.subprocess.run")
def test_pull_with_subdir_exec_from_root(mock_run, workspace):
    workspace.remote_working_dir = workspace.remote.directory
    mock_run.return_value = MagicMock(returncode=0)

    workspace.pull(subpath=Path("some-path"))
    mock_run.assert_called_once_with(
        [
            "rsync",
            "-arlpmchz",
            "--copy-unsafe-links",
            "-e",
            "ssh -Kq -o BatchMode=yes",
            "--force",
            f"{workspace.remote.host}:{workspace.remote.directory}/some-path",
            f"{workspace.local_root}/",
        ],
        stderr=sys.stderr,
        stdout=sys.stdout,
    )


@patch("remote.util.subprocess.run")
def test_execute(mock_run, workspace):
    mock_run.return_value = MagicMock(returncode=0)

    code = workspace.execute(["echo", "Hello World!"])
    mock_run.assert_called_once_with(
        [
            "ssh",
            "-tKq",
            "-o",
            "BatchMode=yes",
            workspace.remote.host,
            """\
cd remote/dir
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd foo/bar
echo 'Hello World!'
""",
        ],
        stderr=sys.stderr,
        stdin=sys.stdin,
        stdout=sys.stdout,
    )
    assert code == 0


@patch("remote.util.subprocess.run")
def test_execute_with_dry_run(mock_run, workspace):
    mock_run.return_value = MagicMock(returncode=0)

    code = workspace.execute(["echo", "Hello World!"], dry_run=True)
    mock_run.assert_called_once_with(
        ["ssh", "-tKq", "-o", "BatchMode=yes", workspace.remote.host, "echo echo 'Hello World!'"],
        stderr=sys.stderr,
        stdin=sys.stdin,
        stdout=sys.stdout,
    )
    assert code == 0


@patch("remote.util.subprocess.run")
def test_execute_with_communication_override(mock_run, workspace, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)

    with (logs_dir / "output.log").open("w") as output_file:
        workspace.communication = CommunicationOptions(stderr=output_file, stdout=output_file, stdin=None)
        code = workspace.execute(["echo", "Hello World!"])
        mock_run.assert_called_once_with(
            [
                "ssh",
                "-tKq",
                "-o",
                "BatchMode=yes",
                workspace.remote.host,
                """\
cd remote/dir
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd foo/bar
echo 'Hello World!'
""",
            ],
            stderr=output_file,
            stdin=None,
            stdout=output_file,
        )
        assert code == 0


@patch("remote.util.subprocess.run")
def test_execute_with_port_forwarding(mock_run, workspace):
    mock_run.return_value = MagicMock(returncode=0)

    code = workspace.execute(["echo", "Hello World!"], ports=[ForwardingOption(5005, 5000)],)
    mock_run.assert_called_once_with(
        [
            "ssh",
            "-tKq",
            "-o",
            "BatchMode=yes",
            "-L",
            "5000:localhost:5005",
            workspace.remote.host,
            """\
cd remote/dir
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd foo/bar
echo 'Hello World!'
""",
        ],
        stderr=sys.stderr,
        stdin=sys.stdin,
        stdout=sys.stdout,
    )
    assert code == 0


@patch("remote.util.subprocess.run")
def test_execute_with_custom_port(mock_run, workspace):
    mock_run.return_value = MagicMock(returncode=0)

    workspace.remote.port = 4321
    code = workspace.execute(["echo", "Hello World!"], ports=[ForwardingOption(5005, 5000, local_interface="0.0.0.0")],)
    mock_run.assert_called_once_with(
        [
            "ssh",
            "-tKq",
            "-o",
            "BatchMode=yes",
            "-p",
            "4321",
            "-L",
            "0.0.0.0:5000:localhost:5005",
            workspace.remote.host,
            """\
cd remote/dir
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd foo/bar
echo 'Hello World!'
""",
        ],
        stderr=sys.stderr,
        stdin=sys.stdin,
        stdout=sys.stdout,
    )
    assert code == 0


@patch("remote.util.subprocess.run")
def test_execute_with_custom_env(mock_run, workspace):
    mock_run.return_value = MagicMock(returncode=0)

    code = workspace.execute(["echo", "Hello World!"], env={"TEST_VAR": "test", "OTHER_VAR": "meow"})
    mock_run.assert_called_once_with(
        [
            "ssh",
            "-tKq",
            "-o",
            "BatchMode=yes",
            workspace.remote.host,
            """\
cd remote/dir
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd foo/bar
export OTHER_VAR=meow
export TEST_VAR=test
echo 'Hello World!'
""",
        ],
        stderr=sys.stderr,
        stdin=sys.stdin,
        stdout=sys.stdout,
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
                stderr=sys.stderr,
                stdout=sys.stdout,
            ),
            call(
                [
                    "ssh",
                    "-tKq",
                    "-o",
                    "BatchMode=yes",
                    workspace.remote.host,
                    """\
cd remote/dir
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd foo/bar
echo 'Hello World!'
""",
                ],
                stderr=sys.stderr,
                stdin=sys.stdin,
                stdout=sys.stdout,
            ),
            call(
                [
                    "rsync",
                    "-arlpmchz",
                    "--copy-unsafe-links",
                    "-e",
                    "ssh -Kq -o BatchMode=yes",
                    "--force",
                    "--exclude-from",
                    ANY,
                    f"{workspace.remote.host}:{workspace.remote.directory}/",
                    f"{workspace.local_root}",
                ],
                stderr=sys.stderr,
                stdout=sys.stdout,
            ),
        ]
    )
    assert code == 10


@patch("remote.util.subprocess.run")
def test_execute_and_sync_with_port_forwarding(mock_run, workspace):
    mock_run.side_effect = [MagicMock(returncode=0), MagicMock(returncode=10), MagicMock(returncode=0)]

    code = workspace.execute_in_synced_env(["echo", "Hello World!"], ports=[ForwardingOption(5005, 5000)],)
    mock_run.assert_has_calls(
        [
            call(
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
                stderr=sys.stderr,
                stdout=sys.stdout,
            ),
            call(
                [
                    "ssh",
                    "-tKq",
                    "-o",
                    "BatchMode=yes",
                    "-L",
                    "5000:localhost:5005",
                    workspace.remote.host,
                    """\
cd remote/dir
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd foo/bar
echo 'Hello World!'
""",
                ],
                stderr=sys.stderr,
                stdin=sys.stdin,
                stdout=sys.stdout,
            ),
            call(
                [
                    "rsync",
                    "-arlpmchz",
                    "--copy-unsafe-links",
                    "-e",
                    "ssh -Kq -o BatchMode=yes",
                    "--force",
                    "--exclude-from",
                    ANY,
                    f"{workspace.remote.host}:{workspace.remote.directory}/",
                    f"{workspace.local_root}",
                ],
                stderr=sys.stderr,
                stdout=sys.stdout,
            ),
        ]
    )
    assert code == 10


@patch("remote.util.subprocess.run")
def test_execute_and_sync_with_communication_override(mock_run, workspace, tmp_path):
    mock_run.side_effect = [MagicMock(returncode=0), MagicMock(returncode=10), MagicMock(returncode=0)]
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)

    with (logs_dir / "output.log").open("w") as output_file:
        workspace.communication = CommunicationOptions(stderr=output_file, stdout=output_file, stdin=None)
        code = workspace.execute_in_synced_env(["echo", "Hello World!"])
        mock_run.assert_has_calls(
            [
                call(
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
                    stderr=output_file,
                    stdout=output_file,
                ),
                call(
                    [
                        "ssh",
                        "-tKq",
                        "-o",
                        "BatchMode=yes",
                        workspace.remote.host,
                        """\
cd remote/dir
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd foo/bar
echo 'Hello World!'
""",
                    ],
                    stderr=output_file,
                    stdin=None,
                    stdout=output_file,
                ),
                call(
                    [
                        "rsync",
                        "-arlpmchz",
                        "--copy-unsafe-links",
                        "-e",
                        "ssh -Kq -o BatchMode=yes",
                        "--force",
                        "--exclude-from",
                        ANY,
                        f"{workspace.remote.host}:{workspace.remote.directory}/",
                        f"{workspace.local_root}",
                    ],
                    stderr=output_file,
                    stdout=output_file,
                ),
            ]
        )
        assert code == 10
