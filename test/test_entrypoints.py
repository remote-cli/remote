"""Integration-ish tests for CLI endpoints.
We only mock subprocess calls since we cannot do multi-host testing.

Some of the test above don't verify much, but they at least ensure that all parts work well together.
"""
import os
import sys

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import ANY, MagicMock, Mock, call, patch

import pytest

from click import BadParameter
from click.testing import CliRunner

from remote import entrypoints
from remote.configuration.classic import CONFIG_FILE_NAME, IGNORE_FILE_NAME, INDEX_FILE_NAME
from remote.configuration.toml import WORKSPACE_CONFIG
from remote.exceptions import RemoteExecutionError

TEST_HOST = "test-host1.example.com"
TEST_DIR = ".remotes/myproject"
TEST_CONFIG = f"{TEST_HOST}:{TEST_DIR}"


@contextmanager
def cwd(path):
    old_cwd = os.getcwd()
    os.chdir(str(path))
    try:
        yield path
    finally:
        os.chdir(old_cwd)


@pytest.fixture
def tmp_workspace(tmp_path):
    (tmp_path / CONFIG_FILE_NAME).write_text(TEST_CONFIG + "\n")
    (tmp_path / IGNORE_FILE_NAME).write_text(
        """\
pull:
push:
both:
.remote
.remoteignore
.remoteindex
"""
    )
    return tmp_path


def test_log_exceptions_decorator():
    @entrypoints.log_exceptions
    def test_function(num):
        if num > 0:
            raise RemoteExecutionError("Some execution error")
        elif num == 0:
            raise ValueError("Some value error")
        else:
            return

    # This shouldnt fail
    test_function(-1)

    # This should fail with custom error and cause sys.exit
    with pytest.raises(SystemExit):
        test_function(1)

    # This should fail with internal error and propagate exception
    with pytest.raises(ValueError):
        test_function(0)


@pytest.mark.parametrize(
    "connection, is_valid",
    [
        ("host", True),
        ("host123", True),
        ("host.domain.com", True),
        ("ho-st.dom-ain.as1234", True),
        ("ho-st.dom-ain.as1234:/home/dir", True),
        ("ho-st.dom-ain.as1234:.home/dir.dir", True),
        ("ho-st.dom-ain.as1234:.home/dir.dir/123/", True),
        ("ho-st.dom-ain.as1234:.home/dir.dir/123/:something", False),
        ("ho-st.dom-ain.as1234::/home/dir", False),
    ],
)
def test_validate_connection_string(connection, is_valid):
    if is_valid:
        entrypoints.validate_connection_string(None, None, connection)
    else:
        with pytest.raises(BadParameter):
            entrypoints.validate_connection_string(None, None, connection)


@patch("remote.util.subprocess.run")
@patch(
    "remote.configuration.toml.TomlConfigurationMedium.generate_remote_directory",
    MagicMock(return_value=".remotes/myproject_foo"),
)
def test_remote_init(mock_run, tmp_path):
    mock_run.return_value = Mock(returncode=0)
    subdir = tmp_path / "myproject"
    subdir.mkdir()

    runner = CliRunner()
    with cwd(subdir):
        result = runner.invoke(entrypoints.remote_init, ["test-host.example.com"])

    assert result.exit_code == 0
    assert "Created remote directory at test-host.example.com:.remotes/myproject_foo" in result.output
    assert "Remote is configured and ready to use" in result.output

    mock_run.assert_called_once_with(
        ["ssh", "-tKq", "-o", "BatchMode=yes", "test-host.example.com", ANY],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    assert (subdir / WORKSPACE_CONFIG).exists()
    assert (
        (subdir / WORKSPACE_CONFIG).read_text()
        == """\
[[hosts]]
host = "test-host.example.com"
directory = ".remotes/myproject_foo"
default = true
supports_gssapi_auth = true

[push]
exclude = []
include = []

[pull]
exclude = []
include = []

[both]
exclude = [ ".remote.toml",]
include = []
"""
    )


@patch("remote.util.subprocess.run")
def test_remote_init_with_dir(mock_run, tmp_path):
    mock_run.return_value = Mock(returncode=0)
    subdir = tmp_path / "myproject"
    subdir.mkdir()

    runner = CliRunner()
    with cwd(subdir):
        result = runner.invoke(entrypoints.remote_init, ["test-host.example.com:.path/test.dir/_test-dir/"])

    assert result.exit_code == 0
    assert (
        result.output
        == """\
Created remote directory at test-host.example.com:.path/test.dir/_test-dir
Remote is configured and ready to use
"""
    )

    mock_run.assert_called_once_with(
        ["ssh", "-tKq", "-o", "BatchMode=yes", "test-host.example.com", "mkdir -p .path/test.dir/_test-dir"],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    assert (subdir / WORKSPACE_CONFIG).exists()
    assert (
        (subdir / WORKSPACE_CONFIG).read_text()
        == """\
[[hosts]]
host = "test-host.example.com"
directory = ".path/test.dir/_test-dir"
default = true
supports_gssapi_auth = true

[push]
exclude = []
include = []

[pull]
exclude = []
include = []

[both]
exclude = [ ".remote.toml",]
include = []
"""
    )


@patch("remote.util.subprocess.run")
def test_remote_init_gitignore(mock_run, tmp_path):
    mock_run.return_value = Mock(returncode=0)
    subdir = tmp_path / "myproject"
    subdir.mkdir()
    (subdir / ".git").mkdir()

    runner = CliRunner()
    with cwd(subdir):
        result = runner.invoke(entrypoints.remote_init, ["test-host.example.com:.path/test.dir/_test-dir/"])

    assert result.exit_code == 0
    assert ".remote*" in (subdir / ".gitignore").read_text()


@patch("remote.util.subprocess.run")
def test_remote_init_gitignore_no_double_writing(mock_run, tmp_path):
    mock_run.return_value = Mock(returncode=0)
    subdir = tmp_path / "myproject"
    subdir.mkdir()
    (subdir / ".git").mkdir()
    (subdir / ".gitignore").write_text("some\nbuild\n.remote*\n.gradle\n")

    runner = CliRunner()
    with cwd(subdir):
        result = runner.invoke(entrypoints.remote_init, ["test-host.example.com:.path/test.dir/_test-dir/"])

    assert result.exit_code == 0
    assert "some\nbuild\n.remote*\n.gradle\n" == (subdir / ".gitignore").read_text()


@patch("remote.util.subprocess.run")
def test_remote_init_fails_after_ssh_error(mock_run, tmp_path):
    mock_run.return_value = Mock(returncode=255)
    subdir = tmp_path / "myproject"
    subdir.mkdir()

    runner = CliRunner()
    with cwd(subdir):
        result = runner.invoke(entrypoints.remote_init, ["host:path"])

    assert result.exit_code == 1
    assert (
        result.output
        == """\
Failed to create path on remote host host
Please check if host is accessible via SSH
"""
    )

    assert not (subdir / WORKSPACE_CONFIG).exists()


def test_remote_init_fails_if_workspace_is_already_initated(tmp_workspace):
    runner = CliRunner()
    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_init, ["host2:path2"])

    assert result.exit_code == 1
    assert (
        result.output
        == """\
A configured workspace already exists in the current working directory.
If you want to add a new host to it, please use remote-add.
"""
    )

    assert (tmp_workspace / CONFIG_FILE_NAME).exists()
    assert (tmp_workspace / CONFIG_FILE_NAME).read_text() == f"{TEST_CONFIG}\n"


def test_remote_init_fails_on_input_validation(tmp_path):
    runner = CliRunner()

    with cwd(tmp_path):
        result = runner.invoke(entrypoints.remote_init, ["host:path:path"])

    assert result.exit_code == 2

    assert not (tmp_path / WORKSPACE_CONFIG).exists()


def test_remote_commands_fail_on_no_workspace(tmp_path):
    runner = CliRunner()

    results = []
    with cwd(tmp_path):
        results.append(runner.invoke(entrypoints.remote_add, ["host:path"]))
        results.append(runner.invoke(entrypoints.remote_ignore, ["*"]))
        results.append(runner.invoke(entrypoints.remote_host))
        results.append(runner.invoke(entrypoints.remote_set, ["1"]))
        results.append(runner.invoke(entrypoints.remote_pull))
        results.append(runner.invoke(entrypoints.remote_push))
        results.append(runner.invoke(entrypoints.remote_quick, ["echo test"]))
        results.append(runner.invoke(entrypoints.remote, ["echo test"]))
        results.append(runner.invoke(entrypoints.remote_delete))

    for result in results:
        assert result.exit_code == 1
        assert result.output == f"Cannot resolve the remote workspace in {tmp_path}\n"


def test_remote_add_fails_on_input_validation(tmp_path):
    runner = CliRunner()

    with cwd(tmp_path):
        result = runner.invoke(entrypoints.remote_add, ["host:path:path"])

    assert result.exit_code == 2


@patch("remote.util.subprocess.run")
def test_remote_add_adds_host(mock_run, tmp_workspace):
    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_add, ["host:directory"])

    assert result.exit_code == 0
    assert (tmp_workspace / CONFIG_FILE_NAME).exists()
    assert (tmp_workspace / CONFIG_FILE_NAME).read_text() == f"{TEST_CONFIG}\nhost:directory\n"

    mock_run.assert_called_once_with(
        ["ssh", "-tKq", "-o", "BatchMode=yes", "host", "mkdir -p directory"],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


@patch("remote.util.subprocess.run")
def test_remote_add_avoids_duplicates(mock_run, tmp_workspace):
    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()

    results = []
    with cwd(tmp_workspace):
        results.append(runner.invoke(entrypoints.remote_add, ["host:directory"]))
        results.append(runner.invoke(entrypoints.remote_add, [TEST_CONFIG]))
        results.append(runner.invoke(entrypoints.remote_add, ["host:directory"]))

    for result in results:
        assert result.exit_code == 0
    assert (tmp_workspace / CONFIG_FILE_NAME).exists()
    assert (tmp_workspace / CONFIG_FILE_NAME).read_text() == f"{TEST_CONFIG}\nhost:directory\n"


@patch("remote.util.subprocess.run")
def test_remote_add_fails_on_ssh(mock_run, tmp_workspace):
    mock_run.return_value = Mock(returncode=255)
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_add, ["host:directory"])

    assert result.exit_code == 1
    assert (tmp_workspace / CONFIG_FILE_NAME).exists()
    assert (tmp_workspace / CONFIG_FILE_NAME).read_text() == f"{TEST_CONFIG}\n"


def test_remote_ignore(tmp_workspace):
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_ignore, ["*pattern", "other-pattern"])
        # also check there is no duplication
        result_two = runner.invoke(entrypoints.remote_ignore, ["new*.txt", "other-pattern"])

    assert result.exit_code == 0
    assert result_two.exit_code == 0
    assert (
        (tmp_workspace / IGNORE_FILE_NAME).read_text()
        == """\
pull:
push:
both:
*pattern
.remote
.remoteignore
.remoteindex
new*.txt
other-pattern
"""
    )


def test_remote_host(tmp_workspace):
    runner = CliRunner()
    (tmp_workspace / CONFIG_FILE_NAME).write_text(f"{TEST_CONFIG}\nhost:directory\n")

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_host)

        # Check that result changes if we change host
        runner.invoke(entrypoints.remote_set, ["2"])

    assert result.exit_code == 0
    assert result.output == f"{TEST_HOST}\n"


def test_remote_set(tmp_workspace):
    runner = CliRunner()
    (tmp_workspace / CONFIG_FILE_NAME).write_text(f"{TEST_CONFIG}\nnew-host:directory\n")

    with cwd(tmp_workspace):
        # Check that result changes if we change host
        set_result = runner.invoke(entrypoints.remote_set, ["2"])
        host_result = runner.invoke(entrypoints.remote_host)

        bad_attempt_result = runner.invoke(entrypoints.remote_set, ["10"])

    assert set_result.exit_code == 0
    assert host_result.output == "new-host\n"
    assert bad_attempt_result.exit_code == 1
    assert (tmp_workspace / INDEX_FILE_NAME).read_text() == "2\n"


@patch("remote.util.subprocess.run")
def test_remote(mock_run, tmp_workspace):
    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote, ["echo test >> .file"])

    assert result.exit_code == 0
    assert mock_run.call_count == 3
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
                    "mkdir -p .remotes/myproject && rsync",
                    "--include-from",
                    ANY,
                    "--exclude-from",
                    ANY,
                    f"{tmp_workspace}/",
                    f"{TEST_HOST}:{TEST_DIR}",
                ],
                stdout=sys.stdout,
                stderr=sys.stderr,
            ),
            call(
                [
                    "ssh",
                    "-tKq",
                    "-o",
                    "BatchMode=yes",
                    TEST_HOST,
                    """\
cd .remotes/myproject
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd .
echo test >> .file
""",
                ],
                stdout=sys.stdout,
                stdin=sys.stdin,
                stderr=sys.stderr,
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
                    f"{TEST_HOST}:{TEST_DIR}/",
                    f"{tmp_workspace}",
                ],
                stdout=sys.stdout,
                stderr=sys.stderr,
            ),
        ]
    )


@patch(
    "remote.entrypoints.datetime",
    MagicMock(now=MagicMock(return_value=datetime(year=2020, month=7, day=13, hour=10, minute=11, second=12))),
)
@patch("remote.util.subprocess.run")
def test_remote_with_output_logging(mock_run, tmp_workspace):
    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote, ["--log", "my_logs", "echo test >> .file"])

    assert result.exit_code == 0
    assert mock_run.call_count == 3
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
                    "mkdir -p .remotes/myproject && rsync",
                    "--include-from",
                    ANY,
                    "--exclude-from",
                    ANY,
                    f"{tmp_workspace}/",
                    f"{TEST_HOST}:{TEST_DIR}",
                ],
                stdout=ANY,
                stderr=ANY,
            ),
            call(
                [
                    "ssh",
                    "-tKq",
                    "-o",
                    "BatchMode=yes",
                    TEST_HOST,
                    """\
cd .remotes/myproject
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd .
echo test >> .file
""",
                ],
                stdout=ANY,
                stdin=None,
                stderr=ANY,
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
                    f"{TEST_HOST}:{TEST_DIR}/",
                    f"{tmp_workspace}",
                ],
                stdout=ANY,
                stderr=ANY,
            ),
        ]
    )
    for mock_call in mock_run.mock_calls:
        name, args, kwargs = mock_call
        assert kwargs["stderr"].name.endswith("my_logs/2020-07-13_10:11:12/test-host1.example.com_output.log")
        assert kwargs["stdout"].name.endswith("my_logs/2020-07-13_10:11:12/test-host1.example.com_output.log")
        try:
            assert kwargs["stdin"] is None
        except KeyError:
            pass


@patch(
    "remote.entrypoints.datetime",
    MagicMock(now=MagicMock(return_value=datetime(year=2020, month=7, day=13, hour=10, minute=11, second=12))),
)
@patch("remote.util.subprocess.run")
def test_remote_mass(mock_run, tmp_workspace):
    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote, ["--multi", "echo test >> .file"])

    assert result.exit_code == 0
    assert mock_run.call_count == 3
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
                    "mkdir -p .remotes/myproject && rsync",
                    "--include-from",
                    ANY,
                    "--exclude-from",
                    ANY,
                    f"{tmp_workspace}/",
                    f"{TEST_HOST}:{TEST_DIR}",
                ],
                stdout=ANY,
                stderr=ANY,
            ),
            call(
                [
                    "ssh",
                    "-tKq",
                    "-o",
                    "BatchMode=yes",
                    TEST_HOST,
                    """\
cd .remotes/myproject
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd .
echo test >> .file
""",
                ],
                stdout=ANY,
                stdin=None,
                stderr=ANY,
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
                    f"{TEST_HOST}:{TEST_DIR}/",
                    f"{tmp_workspace}",
                ],
                stdout=ANY,
                stderr=ANY,
            ),
        ]
    )
    for mock_call in mock_run.mock_calls:
        name, args, kwargs = mock_call
        assert kwargs["stderr"].name.endswith("logs/2020-07-13_10:11:12/test-host1.example.com_output.log")
        assert kwargs["stdout"].name.endswith("logs/2020-07-13_10:11:12/test-host1.example.com_output.log")
        try:
            assert kwargs["stdin"] is None
        except KeyError:
            pass


@pytest.mark.parametrize("label, host", [("usual", "host1"), ("unusual", "host2"), ("2", "host2"), ("3", "host3")])
@patch("remote.util.subprocess.run")
def test_remote_labeling_works(mock_run, tmp_path, label, host):
    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()
    (tmp_path / WORKSPACE_CONFIG).write_text(
        f"""\
[[hosts]]
host = "host1"
directory = "{TEST_DIR}"
default = true
label = "usual"

[[hosts]]
host = "host2"
directory = "{TEST_DIR}"
label = "unusual"

[[hosts]]
host = "host3"
directory = "{TEST_DIR}"
"""
    )

    with cwd(tmp_path):
        result = runner.invoke(entrypoints.remote, ["-l", label, "echo test >> .file"])

    assert result.exit_code == 0
    assert mock_run.call_count == 3
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
                    "mkdir -p .remotes/myproject && rsync",
                    "--include-from",
                    ANY,
                    "--exclude-from",
                    ANY,
                    f"{tmp_path}/",
                    f"{host}:{TEST_DIR}",
                ],
                stdout=sys.stdout,
                stderr=sys.stderr,
            ),
            call(
                [
                    "ssh",
                    "-tKq",
                    "-o",
                    "BatchMode=yes",
                    host,
                    """\
cd .remotes/myproject
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd .
echo test >> .file
""",
                ],
                stdout=sys.stdout,
                stdin=sys.stdin,
                stderr=sys.stderr,
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
                    f"{host}:{TEST_DIR}/",
                    f"{tmp_path}",
                ],
                stdout=sys.stdout,
                stderr=sys.stderr,
            ),
        ]
    )


@patch("remote.util.subprocess.run")
def test_remote_fails_on_unknown_option(mock_run, tmp_workspace):
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote, ["--unknown-opt", "echo", "test >> .file"])

    assert result.exit_code == 2
    assert "Error: no such option --unknown-opt" in result.output


@patch("remote.util.subprocess.run")
def test_remote_execution_fail(mock_run, tmp_workspace):
    mock_run.side_effect = [Mock(returncode=0), Mock(returncode=123), Mock(returncode=0)]
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote, ["echo", "test >> .file"])

    assert result.exit_code == 123
    assert mock_run.call_count == 3
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
                    "mkdir -p .remotes/myproject && rsync",
                    "--include-from",
                    ANY,
                    "--exclude-from",
                    ANY,
                    f"{tmp_workspace}/",
                    f"{TEST_HOST}:{TEST_DIR}",
                ],
                stdout=sys.stdout,
                stderr=sys.stderr,
            ),
            call(
                [
                    "ssh",
                    "-tKq",
                    "-o",
                    "BatchMode=yes",
                    TEST_HOST,
                    """\
cd .remotes/myproject
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd .
echo 'test >> .file'
""",
                ],
                stdout=sys.stdout,
                stdin=sys.stdin,
                stderr=sys.stderr,
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
                    f"{TEST_HOST}:{TEST_DIR}/",
                    f"{tmp_workspace}",
                ],
                stdout=sys.stdout,
                stderr=sys.stderr,
            ),
        ]
    )


@patch("remote.util.subprocess.run")
def test_remote_sync_fail(mock_run, tmp_workspace):
    # first sync fail -> nothing was executed
    mock_run.return_value = Mock(returncode=255)
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote, ["echo test >> .file"])

    assert result.exit_code == 255
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
            "mkdir -p .remotes/myproject && rsync",
            "--include-from",
            ANY,
            "--exclude-from",
            ANY,
            f"{tmp_workspace}/",
            f"{TEST_HOST}:{TEST_DIR}",
        ],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


@patch("remote.util.subprocess.run")
def test_remote_quick(mock_run, tmp_workspace):
    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_quick, ["echo", "test"])

    assert result.exit_code == 0
    mock_run.assert_called_once_with(
        [
            "ssh",
            "-tKq",
            "-o",
            "BatchMode=yes",
            TEST_HOST,
            """\
cd .remotes/myproject
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd .
echo test
""",
        ],
        stdout=sys.stdout,
        stdin=sys.stdin,
        stderr=sys.stderr,
    )


@patch("remote.util.subprocess.run")
def test_remote_quick_fails_on_unknown_option(mock_run, tmp_workspace):
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_quick, ["--unknown-opt", "echo", "test >> .file"])

    assert result.exit_code == 2
    assert "Error: no such option --unknown-opt" in result.output


@patch("remote.util.subprocess.run")
def test_remote_quick_execution_fail(mock_run, tmp_workspace):
    mock_run.return_value = Mock(returncode=15)
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_quick, ["echo", "test"])

    assert result.exit_code == 15
    mock_run.assert_called_once_with(
        [
            "ssh",
            "-tKq",
            "-o",
            "BatchMode=yes",
            TEST_HOST,
            """\
cd .remotes/myproject
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd .
echo test
""",
        ],
        stdout=sys.stdout,
        stdin=sys.stdin,
        stderr=sys.stderr,
    )


@patch("remote.util.subprocess.run")
def test_remote_push(mock_run, tmp_workspace):
    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_push)

    assert result.exit_code == 0
    mock_run.assert_called_once_with(
        [
            "rsync",
            "-arlpmchz",
            "--copy-unsafe-links",
            "-e",
            "ssh -Kq -o BatchMode=yes",
            "--force",
            "-i",
            "--delete",
            "--rsync-path",
            "mkdir -p .remotes/myproject && rsync",
            "--include-from",
            ANY,
            "--exclude-from",
            ANY,
            f"{tmp_workspace}/",
            f"{TEST_HOST}:{TEST_DIR}",
        ],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


@patch("remote.util.subprocess.run")
def test_remote_push_mass(mock_run, tmp_workspace):
    (tmp_workspace / CONFIG_FILE_NAME).write_text(f"{TEST_CONFIG}\nnew-host:other-directory\n")

    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_push, "--multi")

    assert result.exit_code == 0
    assert mock_run.call_count == 2
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
                    "-i",
                    "--delete",
                    "--rsync-path",
                    "mkdir -p .remotes/myproject && rsync",
                    "--include-from",
                    ANY,
                    "--exclude-from",
                    ANY,
                    f"{tmp_workspace}/",
                    f"{TEST_HOST}:{TEST_DIR}",
                ],
                stdout=sys.stdout,
                stderr=sys.stderr,
            ),
            call(
                [
                    "rsync",
                    "-arlpmchz",
                    "--copy-unsafe-links",
                    "-e",
                    "ssh -Kq -o BatchMode=yes",
                    "--force",
                    "-i",
                    "--delete",
                    "--rsync-path",
                    "mkdir -p other-directory && rsync",
                    "--include-from",
                    ANY,
                    "--exclude-from",
                    ANY,
                    f"{tmp_workspace}/",
                    "new-host:other-directory",
                ],
                stdout=sys.stdout,
                stderr=sys.stderr,
            ),
        ]
    )


@patch("remote.util.subprocess.run")
def test_remote_pull(mock_run, tmp_workspace):
    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_pull)

    assert result.exit_code == 0
    mock_run.assert_called_once_with(
        [
            "rsync",
            "-arlpmchz",
            "--copy-unsafe-links",
            "-e",
            "ssh -Kq -o BatchMode=yes",
            "--force",
            "-i",
            "--exclude-from",
            ANY,
            f"{TEST_HOST}:{TEST_DIR}/",
            str(tmp_workspace),
        ],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


@patch("remote.util.subprocess.run")
def test_remote_pull_subdirs(mock_run, tmp_workspace):
    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_pull, ["build", "dist"])

    assert result.exit_code == 0
    assert mock_run.call_count == 2
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
                    "-i",
                    f"{TEST_HOST}:{TEST_DIR}/build",
                    f"{tmp_workspace}/",
                ],
                stdout=sys.stdout,
                stderr=sys.stderr,
            ),
            call(
                [
                    "rsync",
                    "-arlpmchz",
                    "--copy-unsafe-links",
                    "-e",
                    "ssh -Kq -o BatchMode=yes",
                    "--force",
                    "-i",
                    f"{TEST_HOST}:{TEST_DIR}/dist",
                    f"{tmp_workspace}/",
                ],
                stdout=sys.stdout,
                stderr=sys.stderr,
            ),
        ]
    )


@patch("remote.util.subprocess.run")
def test_remote_delete(mock_run, tmp_workspace):
    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_delete)

    assert result.exit_code == 0
    mock_run.assert_called_once_with(
        ["ssh", "-tKq", "-o", "BatchMode=yes", TEST_HOST, f"rm -rf {TEST_DIR}"],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


@pytest.mark.parametrize(
    "port_value, expected_output, expected_exit_code",
    [
        ("bar:foo", "Please pass valid integer value for ports", 1),
        ("bar:5000", "Please pass valid integer value for ports", 1),
        ("bar:foo:foo", "Please pass a valid value to enable local port forwarding", 1),
        ("2.4:2.4", "Please pass valid integer value for ports", 1),
    ],
)
@patch("remote.util.subprocess.run")
def test_remote_port_forwarding_user_input_error(
    mock_run, tmp_workspace, port_value, expected_output, expected_exit_code
):
    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()
    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote, ["-t", port_value, "echo test"])
        assert result.exit_code == expected_exit_code
        assert expected_output in result.output


@pytest.mark.parametrize(
    "port_value, expected_port_forwarding, expected_exit_code",
    [("5000", "5000:localhost:5000", 0), ("5000:5005", "5005:localhost:5000", 0)],
)
@pytest.mark.parametrize(
    "entrypoint", [entrypoints.remote, entrypoints.remote_quick], ids=["remote", "remote-quick"],
)
@patch("remote.util.subprocess.run")
def test_remote_port_forwarding_successful(
    mock_run, tmp_workspace, port_value, expected_port_forwarding, expected_exit_code, entrypoint,
):
    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()
    with cwd(tmp_workspace):
        result = runner.invoke(entrypoint, ["-t", port_value, "echo test"])
        assert result.exit_code == expected_exit_code
        mock_run.assert_any_call(
            [
                "ssh",
                "-tKq",
                "-o",
                "BatchMode=yes",
                "-L",
                expected_port_forwarding,
                "test-host1.example.com",
                """\
cd .remotes/myproject
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd .
echo test
""",
            ],
            stderr=sys.stderr,
            stdin=sys.stdin,
            stdout=sys.stdout,
        )


@patch("remote.util.subprocess.run")
def test_stream_changes(mock_run, tmp_workspace):
    """Ensure the execution with stream changes runs successfully"""
    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()
    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote, ["--stream-changes", "echo test"])
        assert result.exit_code == 0


@patch("remote.explain.subprocess.run")
@patch("remote.util.subprocess.run")
def test_remote_explain(util_run, explain_run, tmp_workspace):
    # This is jsut a smoke test to check that remote-explain doesn't throw any exceptions
    # It is pretty hard to unit-test it correctly
    util_run.return_value = Mock(returncode=0)
    explain_run.return_value = Mock(
        returncode=0,
        stdout="""\
PING some-host.example.com (1.1.1.1): 56 data bytes
64 bytes from 1.1.1.1: icmp_seq=0 ttl=59 time=25.608 ms
64 bytes from 1.1.1.1: icmp_seq=1 ttl=59 time=15.121 ms
64 bytes from 1.1.1.1: icmp_seq=2 ttl=59 time=15.735 ms

--- some-host.example.com ping statistics ---
3 packets transmitted, 3 packets received, 0.0% packet loss
round-trip min/avg/max/stddev = 15.121/18.821/25.608/4.805 ms
""",
    )
    runner = CliRunner()
    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_explain, ["--deep"])

    explain_run.assert_has_calls([call(["ping", "-c", "10", "test-host1.example.com"], capture_output=True, text=True)])
    explain_run.assert_has_calls([call(["ping", "-c", "1", "test-host1.example.com"], capture_output=True, text=True)])
    assert result.exit_code == 0
