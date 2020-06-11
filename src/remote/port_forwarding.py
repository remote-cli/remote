import logging
import subprocess
import sys

from remote.exceptions import SshPortForwardingError

from .configuration import RemotePortForwardingConfig

logger = logging.getLogger(__name__)


class PortForwardingManager:
    def __init__(self, remote_port_forwarding_config: RemotePortForwardingConfig, host: str) -> None:
        self.remote_port_forwarding_config = remote_port_forwarding_config
        self.host = host

    def __enter__(self):
        command = (
            f"ssh -NL {self.remote_port_forwarding_config.remote_port}"
            f":localhost:{self.remote_port_forwarding_config.local_port} {self.host}"
        )
        logger.info(f"Executing:{command}")
        self.process = subprocess.Popen(command.split(), shell=False, stdout=sys.stdout, stderr=sys.stderr)
        # Since its async, we cannot ensure that the ssh tunnel has been already established.
        # However we should do a initial check to see if the process is up.
        if self.process.poll() is not None:
            raise SshPortForwardingError("Unable to establish a ssh tunnel.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.process.terminate()
        try:
            self.process.communicate(timeout=0.2)
        except subprocess.TimeoutExpired:
            logger.debug("Send a SIGKILL if the process did not get killed after sending SIGTERM.")
            self.process.kill()
        return exc_type is None
