import subprocess

from unittest.mock import MagicMock, Mock, patch

import pytest

from remote.configuration import RemotePortForwardingConfig
from remote.exceptions import SshPortForwardingError
from remote.port_forwarding import PortForwardingManager


@pytest.mark.parametrize(
    "poll_return_value, exception_raised",
    [  # When the subprocess finished with an exit code of 0
        (0, SshPortForwardingError),
        #  When the subprocess finished with a non zero exit code.
        (2, SshPortForwardingError),
        # When the subprocess is still running.
        (None, None),
    ],
)
@patch("remote.util.subprocess.Popen")
def test_if_process_started(mock_Popen, poll_return_value, exception_raised):

    mock_Popen.return_value = MagicMock(poll=Mock(return_value=poll_return_value))
    remote_port_forwarding_config = RemotePortForwardingConfig(5000, 5000)
    host = "foo"
    if exception_raised:
        with pytest.raises(exception_raised):
            with PortForwardingManager(remote_port_forwarding_config, host):
                pass
    else:
        with PortForwardingManager(remote_port_forwarding_config, host):
            pass


@patch("remote.util.subprocess.Popen")
def test_if_exception_is_propagated(mock_Popen):
    remote_port_forwarding_config = RemotePortForwardingConfig(5000, 5000)
    host = "foo"
    with pytest.raises(Exception):
        with PortForwardingManager(remote_port_forwarding_config, host):
            raise Exception("test")


@patch("remote.util.subprocess.Popen")
def test_if_resource_cleaned_up(mock_Popen):

    mock_Popen_ob = MagicMock(poll=Mock(return_value=None))
    mock_Popen.return_value = mock_Popen_ob
    remote_port_forwarding_config = RemotePortForwardingConfig(5000, 5000)
    host = "foo"
    with PortForwardingManager(remote_port_forwarding_config, host):
        pass
    assert mock_Popen_ob.terminate.called

    # Test if SIGKILL failed to kill the process, SIGTEREM is sent
    mock_Popen_ob = MagicMock(
        poll=Mock(return_value=None), communicate=Mock(side_effect=subprocess.TimeoutExpired(cmd=["foo"], timeout=2))
    )
    mock_Popen.return_value = mock_Popen_ob
    with PortForwardingManager(remote_port_forwarding_config, host):
        pass

    assert mock_Popen_ob.terminate.called
    assert mock_Popen_ob.kill.called
