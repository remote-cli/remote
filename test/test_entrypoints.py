"""Integration-ish tests for CLI endpoints.
We only mock subprocess calls since we cannot do multi-host testing.

Some of the test above don't verify much, but they at least ensure that all parts work well together.
"""
import os

from contextlib import contextmanager
from unittest.mock import ANY, Mock, call, patch

import pytest

from click import BadParameter
from click.testing import CliRunner

from remote import entrypoints
from remote.configuration.classic import CONFIG_FILE_NAME, IGNORE_FILE_NAME, INDEX_FILE_NAME
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
def test_remote_init(mock_run, tmp_path):
    mock_run.return_value = Mock(returncode=0)
    subdir = tmp_path / "myproject"
    subdir.mkdir()

    runner = CliRunner()
    with cwd(subdir):
        result = runner.invoke(entrypoints.remote_init, ["test-host.example.com"])

    assert result.exit_code == 0
    assert "Created remote directory at test-host.example.com:.remotes/myproject_" in result.output
    assert "Remote is configured and ready to use" in result.output

    mock_run.assert_called_once_with(["ssh", "-tKq", "test-host.example.com", ANY], stdin=ANY, stdout=ANY, stderr=ANY)

    assert (subdir / CONFIG_FILE_NAME).exists()
    assert (subdir / CONFIG_FILE_NAME).read_text().startswith("test-host.example.com:.remotes/myproject_")
    assert (subdir / IGNORE_FILE_NAME).exists()
    assert (
        (subdir / IGNORE_FILE_NAME).read_text()
        == """\
pull:
push:
both:
.remote
.remoteignore
.remoteindex
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
        ["ssh", "-tKq", "test-host.example.com", "mkdir -p .path/test.dir/_test-dir"],
        stdin=ANY,
        stdout=ANY,
        stderr=ANY,
    )

    assert (subdir / CONFIG_FILE_NAME).exists()
    assert (subdir / CONFIG_FILE_NAME).read_text() == "test-host.example.com:.path/test.dir/_test-dir\n"
    assert (subdir / IGNORE_FILE_NAME).exists()
    assert (
        (subdir / IGNORE_FILE_NAME).read_text()
        == """\
pull:
push:
both:
.remote
.remoteignore
.remoteindex
"""
    )


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

    assert not (subdir / CONFIG_FILE_NAME).exists()
    assert not (subdir / IGNORE_FILE_NAME).exists()


def test_remote_init_fails_if_workspace_is_already_initated(tmp_workspace):
    runner = CliRunner()
    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_init, ["host2:path2"])

    assert result.exit_code == 1
    assert (
        result.output
        == """\
A configured workspace already exists in the current directory.
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
    assert not (tmp_path / CONFIG_FILE_NAME).exists()


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
        ["ssh", "-tKq", "host", "mkdir -p directory"], stdin=ANY, stdout=ANY, stderr=ANY,
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
    assert host_result.output == f"new-host\n"
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
                    "-rlpmchz",
                    "--copy-unsafe-links",
                    "-e",
                    "ssh -q",
                    "--force",
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
                    TEST_HOST,
                    """if [ -f .remotes/myproject/.remoteenv ]; then
  source .remotes/myproject/.remoteenv 2>/dev/null 1>/dev/null
fi
cd .remotes/myproject
echo test >> .file
""",
                ],
                stdout=ANY,
                stdin=ANY,
                stderr=ANY,
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
                    f"{TEST_HOST}:{TEST_DIR}/",
                    f"{tmp_workspace}",
                ],
                stdout=ANY,
                stderr=ANY,
            ),
        ]
    )


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
                    "-rlpmchz",
                    "--copy-unsafe-links",
                    "-e",
                    "ssh -q",
                    "--force",
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
                    TEST_HOST,
                    """if [ -f .remotes/myproject/.remoteenv ]; then
  source .remotes/myproject/.remoteenv 2>/dev/null 1>/dev/null
fi
cd .remotes/myproject
echo 'test >> .file'
""",
                ],
                stdout=ANY,
                stdin=ANY,
                stderr=ANY,
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
                    f"{TEST_HOST}:{TEST_DIR}/",
                    f"{tmp_workspace}",
                ],
                stdout=ANY,
                stderr=ANY,
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

    assert result.exit_code == 1
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
            f"{tmp_workspace}/",
            f"{TEST_HOST}:{TEST_DIR}",
        ],
        stdout=ANY,
        stderr=ANY,
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
            TEST_HOST,
            """if [ -f .remotes/myproject/.remoteenv ]; then
  source .remotes/myproject/.remoteenv 2>/dev/null 1>/dev/null
fi
cd .remotes/myproject
echo test
""",
        ],
        stdout=ANY,
        stdin=ANY,
        stderr=ANY,
    )


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
            TEST_HOST,
            """if [ -f .remotes/myproject/.remoteenv ]; then
  source .remotes/myproject/.remoteenv 2>/dev/null 1>/dev/null
fi
cd .remotes/myproject
echo test
""",
        ],
        stdout=ANY,
        stdin=ANY,
        stderr=ANY,
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
            "-rlpmchz",
            "--copy-unsafe-links",
            "-e",
            "ssh -q",
            "--force",
            "-i",
            "--exclude-from",
            ANY,
            f"{tmp_workspace}/",
            f"{TEST_HOST}:{TEST_DIR}",
        ],
        stdout=ANY,
        stderr=ANY,
    )


@patch("remote.util.subprocess.run")
def test_remote_push_mass(mock_run, tmp_workspace):
    (tmp_workspace / CONFIG_FILE_NAME).write_text(f"{TEST_CONFIG}\nnew-host:other-directory\n")

    mock_run.return_value = Mock(returncode=0)
    runner = CliRunner()

    with cwd(tmp_workspace):
        result = runner.invoke(entrypoints.remote_push, "--mass")

    assert result.exit_code == 0
    assert mock_run.call_count == 2
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
                    "-i",
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
                    "rsync",
                    "-rlpmchz",
                    "--copy-unsafe-links",
                    "-e",
                    "ssh -q",
                    "--force",
                    "-i",
                    "--exclude-from",
                    ANY,
                    f"{tmp_workspace}/",
                    f"new-host:other-directory",
                ],
                stdout=ANY,
                stderr=ANY,
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
            "-rlpmchz",
            "--copy-unsafe-links",
            "-e",
            "ssh -q",
            "--force",
            "-i",
            "--exclude-from",
            ANY,
            f"{TEST_HOST}:{TEST_DIR}/",
            str(tmp_workspace),
        ],
        stdout=ANY,
        stderr=ANY,
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
                    "-rlpmchz",
                    "--copy-unsafe-links",
                    "-e",
                    "ssh -q",
                    "--force",
                    "-i",
                    f"{TEST_HOST}:{TEST_DIR}/build",
                    f"{tmp_workspace}/build",
                ],
                stdout=ANY,
                stderr=ANY,
            ),
            call(
                [
                    "rsync",
                    "-rlpmchz",
                    "--copy-unsafe-links",
                    "-e",
                    "ssh -q",
                    "--force",
                    "-i",
                    f"{TEST_HOST}:{TEST_DIR}/dist",
                    f"{tmp_workspace}/dist",
                ],
                stdout=ANY,
                stderr=ANY,
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
        ["ssh", "-tKq", TEST_HOST, f"rm -rf {TEST_DIR}"], stdin=ANY, stdout=ANY, stderr=ANY,
    )
