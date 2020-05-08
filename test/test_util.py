from unittest.mock import ANY, MagicMock, patch

import pytest

from remote.exceptions import RemoteConnectionError, RemoteExecutionError
from remote.util import _temp_file, prepare_shell_command, rsync, ssh


def test_temp_file():
    file = _temp_file(["1", "", "2", "3"])
    assert file.exists()
    assert (
        file.read_text()
        == """\
1

2
3
"""
    )
    assert file.name.startswith("remote.")


def test_rsync_copies_files(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "first").write_text("TEST first")
    (src / "second").write_text("TEST second")
    (src / "third.txt").write_text("TEST third")
    (src / "fourth.txt").write_text("TEST fourth")

    dst = tmp_path / "dst"
    rsync(f"{src}/", str(dst), excludes=["f*"], includes=["*.txt"])

    assert dst.exists()
    assert not (dst / "first").exists()
    assert (dst / "second").exists()
    assert (dst / "second").read_text() == "TEST second"
    assert (dst / "third.txt").exists()
    assert (dst / "third.txt").read_text() == "TEST third"
    assert (dst / "fourth.txt").exists()
    assert (dst / "fourth.txt").read_text() == "TEST fourth"


def test_rsync_copies_files_with_mirror(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "first").write_text("TEST first")
    (src / "second").write_text("TEST second")
    (src / "third.txt").write_text("TEST third")
    (src / "fourth.txt").write_text("TEST fourth")

    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "first").write_text("TEST first")

    # since we use mirror=True "first" should be deleted in dst
    rsync(f"{src}/", str(dst), excludes=["f*"], mirror=True)

    assert dst.exists()
    assert not (dst / "first").exists()
    assert (dst / "second").exists()
    assert (dst / "second").read_text() == "TEST second"
    assert (dst / "third.txt").exists()
    assert (dst / "third.txt").read_text() == "TEST third"
    assert not (dst / "fourth.txt").exists()


@patch("remote.util.subprocess.run")
def test_rsync_respects_all_options(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    rsync(f"src/", "dst", info=True, verbose=True, mirror=True, dry_run=True, extra_args=["--some-extra"])

    mock_run.assert_called_once_with(
        [
            "rsync",
            "-rlpmchz",
            "--copy-unsafe-links",
            "-e",
            "ssh -q",
            "--force",
            "-i",
            "-v",
            "-n",
            "--delete",
            "--delete-after",
            "--delete-excluded",
            "--some-extra",
            "src/",
            "dst",
        ],
        stdout=ANY,
        stderr=ANY,
    )


@patch("remote.util.subprocess.run")
def test_rsync_throws_exception_on_bad_return_code(mock_run):
    mock_run.return_value = MagicMock()
    mock_run.return_value.returncode = 1

    with pytest.raises(RemoteConnectionError):
        rsync(f"src/", "dst")


@pytest.mark.parametrize("returncode", [0, 1])
@patch("remote.util.subprocess.run")
@patch("remote.util._temp_file")
def test_rsync_always_removes_temporary_files(mock_temp_file, mock_run, returncode, tmp_path):
    mock_run.return_value = MagicMock(returncode=returncode)

    files = []

    def ignore_file(_):
        new_path = tmp_path / f"file{len(files)}"
        new_path.write_text("TEST")
        files.append(new_path)
        return new_path

    mock_temp_file.side_effect = ignore_file

    try:
        rsync(f"src/", "dst", excludes=["f*"], includes=["*.txt"])
    except Exception:
        pass

    assert len(files) == 2
    for file in files:
        assert not file.exists()


@patch("remote.util.subprocess.run")
def test_ssh(mock_run):
    mock_run.return_value = MagicMock(returncode=0)

    code = ssh("my-host.example.com", "exit 0")

    assert code == 0
    mock_run.assert_called_once_with(
        ["ssh", "-tKq", "my-host.example.com", "exit 0"], stdout=ANY, stderr=ANY, stdin=ANY
    )


@pytest.mark.parametrize("returncode, error", [(255, RemoteConnectionError), (1, RemoteExecutionError)])
@patch("remote.util.subprocess.run")
def test_ssh_raises_exception(mock_run, returncode, error):
    mock_run.return_value = MagicMock(returncode=returncode)

    with pytest.raises(error):
        ssh("my-host.example.com", f"exit {returncode}")

    mock_run.assert_called_once_with(
        ["ssh", "-tKq", "my-host.example.com", f"exit {returncode}"], stdout=ANY, stderr=ANY, stdin=ANY
    )


@pytest.mark.parametrize("returncode", [255, 1])
@patch("remote.util.subprocess.run")
def test_ssh_returns_error_code_if_configured(mock_run, returncode):
    mock_run.return_value = MagicMock()
    mock_run.return_value.returncode = returncode

    code = ssh("my-host.example.com", f"exit {returncode}", raise_on_error=False)

    assert code == returncode
    mock_run.assert_called_once_with(
        ["ssh", "-tKq", "my-host.example.com", f"exit {returncode}"], stdout=ANY, stderr=ANY, stdin=ANY
    )


@patch("remote.util.subprocess.run")
def test_ssh_no_execute_on_dry_run(mock_run):
    code = ssh("my-host.example.com", "exit 1", dry_run=True)

    assert code == 0
    mock_run.assert_not_called()


@pytest.mark.parametrize(
    "command, expected",
    [
        (["ls", "-l"], "ls -l"),
        (["ls -l"], "ls -l"),
        ("ls -l", "ls -l"),
        (["echo", "some text here"], "echo 'some text here'"),
        (["echo", "some\ntext\nhere"], "echo 'some\ntext\nhere'"),
        (["du", "-sh", "-C", "/some/path/with whitespace/"], "du -sh -C '/some/path/with whitespace/'"),
    ],
)
def test_prepare_shell_command(command, expected):
    result = prepare_shell_command(command)

    assert result == expected
