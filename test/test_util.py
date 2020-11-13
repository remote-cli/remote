import sys

from unittest.mock import MagicMock, patch

import pytest

from pytest import raises

from remote.exceptions import InvalidInputError, RemoteConnectionError, RemoteExecutionError
from remote.util import ForwardingOption, Ssh, VerbosityLevel, _temp_file, prepare_shell_command, rsync


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


@pytest.fixture
def rsync_ssh():
    return Ssh("test-host", force_tty=False)


def test_rsync_copies_files(tmp_path, rsync_ssh):
    src = tmp_path / "src"
    src.mkdir()
    (src / "first").write_text("TEST first")
    (src / "second").write_text("TEST second")
    (src / "third.txt").write_text("TEST third")
    (src / "fourth.txt").write_text("TEST fourth")

    dst = tmp_path / "dst"
    rsync(f"{src}/", str(dst), rsync_ssh, excludes=["f*"], includes=["*.txt"])

    assert dst.exists()
    assert not (dst / "first").exists()
    assert (dst / "second").exists()
    assert (dst / "second").read_text() == "TEST second"
    assert (dst / "third.txt").exists()
    assert (dst / "third.txt").read_text() == "TEST third"
    assert (dst / "fourth.txt").exists()
    assert (dst / "fourth.txt").read_text() == "TEST fourth"


def test_rsync_copies_files_with_mirror(tmp_path, rsync_ssh):
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
    rsync(f"{src}/", str(dst), rsync_ssh, excludes=["f*"], mirror=True)

    assert dst.exists()
    assert not (dst / "first").exists()
    assert (dst / "second").exists()
    assert (dst / "second").read_text() == "TEST second"
    assert (dst / "third.txt").exists()
    assert (dst / "third.txt").read_text() == "TEST third"
    assert not (dst / "fourth.txt").exists()


@patch("remote.util.subprocess.run")
def test_rsync_respects_all_options(mock_run, rsync_ssh):
    mock_run.return_value = MagicMock(returncode=0)
    rsync("src/", "dst", rsync_ssh, info=True, verbose=True, mirror=True, dry_run=True, extra_args=["--some-extra"])

    mock_run.assert_called_once_with(
        [
            "rsync",
            "-arlpmchz",
            "--copy-unsafe-links",
            "-e",
            "ssh -Kq -o BatchMode=yes",
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
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


@patch("remote.util.subprocess.run")
def test_rsync_throws_exception_on_bad_return_code(mock_run, rsync_ssh):
    mock_run.return_value = MagicMock()
    mock_run.return_value.returncode = 1

    with pytest.raises(RemoteConnectionError):
        rsync("src/", "dst", rsync_ssh)


@pytest.mark.parametrize("returncode", [0, 1])
@patch("remote.util.subprocess.run")
@patch("remote.util._temp_file")
def test_rsync_always_removes_temporary_files(mock_temp_file, mock_run, returncode, tmp_path, rsync_ssh):
    mock_run.return_value = MagicMock(returncode=returncode)

    files = []

    def ignore_file(_):
        new_path = tmp_path / f"file{len(files)}"
        new_path.write_text("TEST")
        files.append(new_path)
        return new_path

    mock_temp_file.side_effect = ignore_file

    try:
        rsync("src/", "dst", rsync_ssh, excludes=["f*"], includes=["*.txt"])
    except Exception:
        pass

    assert len(files) == 2
    for file in files:
        assert not file.exists()


@pytest.mark.parametrize(
    "ssh, expected_cmd",
    [
        (Ssh("host"), "ssh -tKq -o BatchMode=yes"),
        (Ssh("host", port=12345, force_tty=False), "ssh -Kq -o BatchMode=yes -p 12345"),
        (Ssh("host", force_tty=False), "ssh -Kq -o BatchMode=yes"),
        (Ssh("host", disable_password_auth=False), "ssh -tKq"),
        (Ssh("host", verbosity_level=VerbosityLevel.DEFAULT), "ssh -tK -o BatchMode=yes"),
        (
            Ssh("host", verbosity_level=VerbosityLevel.DEFAULT, local_port_forwarding=[ForwardingOption(1234, 4312)]),
            "ssh -tK -o BatchMode=yes -L 4312:localhost:1234",
        ),
        (
            Ssh(
                "host",
                verbosity_level=VerbosityLevel.DEFAULT,
                local_port_forwarding=[ForwardingOption(1234, 4312, "0.0.0.0"), ForwardingOption(5678, 8756, "[::]")],
            ),
            "ssh -tK -o BatchMode=yes -L 4312:0.0.0.0:1234 -L '8756:[::]:5678'",
        ),
        (Ssh("host", verbosity_level=VerbosityLevel.VERBOSE), "ssh -tKv -o BatchMode=yes"),
        (Ssh("host", verbosity_level=VerbosityLevel.VERBOSE, use_gssapi_auth=False), "ssh -tv -o BatchMode=yes"),
        (
            Ssh("host", verbosity_level=VerbosityLevel.DEFAULT, force_tty=False, use_gssapi_auth=False),
            "ssh -o BatchMode=yes",
        ),
        (
            Ssh(
                "host",
                verbosity_level=VerbosityLevel.DEFAULT,
                force_tty=False,
                use_gssapi_auth=False,
                disable_password_auth=False,
            ),
            "ssh",
        ),
    ],
)
def test_ssh_gen_command(ssh, expected_cmd):
    assert ssh.generate_command_str() == expected_cmd


@pytest.mark.parametrize(
    "port, expected_command_run",
    [
        (None, ["ssh", "-tKq", "-o", "BatchMode=yes", "my-host.example.com", "exit 0"]),
        (
            ForwardingOption(5000, 5005),
            ["ssh", "-tKq", "-o", "BatchMode=yes", "-L", "5005:localhost:5000", "my-host.example.com", "exit 0"],
        ),
    ],
)
@patch("remote.util.subprocess.run")
def test_ssh_execute(mock_run, port, expected_command_run):
    mock_run.return_value = MagicMock(returncode=0)

    ssh = Ssh("my-host.example.com", local_port_forwarding=[port] if port else [])
    code = ssh.execute("exit 0")

    assert code == 0
    mock_run.assert_called_once_with(expected_command_run, stdout=sys.stdout, stderr=sys.stderr, stdin=sys.stdin)


@pytest.mark.parametrize("returncode, error", [(255, RemoteConnectionError), (1, RemoteExecutionError)])
@patch("remote.util.subprocess.run")
def test_ssh_raises_exception(mock_run, returncode, error):
    mock_run.return_value = MagicMock(returncode=returncode)

    with pytest.raises(error):
        ssh = Ssh("my-host.example.com")
        ssh.execute(f"exit {returncode}")

    mock_run.assert_called_once_with(
        ["ssh", "-tKq", "-o", "BatchMode=yes", "my-host.example.com", f"exit {returncode}"],
        stdout=sys.stdout,
        stderr=sys.stderr,
        stdin=sys.stdin,
    )


@pytest.mark.parametrize("returncode", [255, 1])
@patch("remote.util.subprocess.run")
def test_ssh_returns_error_code_if_configured(mock_run, returncode):
    mock_run.return_value = MagicMock()
    mock_run.return_value.returncode = returncode

    ssh = Ssh("my-host.example.com")
    code = ssh.execute(f"exit {returncode}", raise_on_error=False)

    assert code == returncode
    mock_run.assert_called_once_with(
        ["ssh", "-tKq", "-o", "BatchMode=yes", "my-host.example.com", f"exit {returncode}"],
        stdout=sys.stdout,
        stderr=sys.stderr,
        stdin=sys.stdin,
    )


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


@pytest.mark.parametrize(
    "port_value, expected_value, exception_raised",
    [
        ("5000", ForwardingOption(5000, 5000), None),
        ("5000:5200", ForwardingOption(5000, 5200), None),
        ("bar:foo", None, InvalidInputError),
        ("2.5:100", None, InvalidInputError),
        ("2.6:32:25", None, InvalidInputError),
        ("bar", None, InvalidInputError),
    ],
)
def test_parse_ports(port_value, expected_value, exception_raised):
    if exception_raised:
        with raises(exception_raised):
            ForwardingOption.from_string(port_value)
    else:
        port = ForwardingOption.from_string(port_value)
        assert expected_value == port
