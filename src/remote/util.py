import logging
import shlex
import subprocess
import sys
import tempfile
import time

from contextlib import contextmanager
from dataclasses import dataclass, field, fields, is_dataclass
from enum import IntEnum
from pathlib import Path
from typing import List, Optional, Sequence, TextIO, Union

from remote.exceptions import InvalidInputError

from .exceptions import RemoteConnectionError, RemoteExecutionError

logger = logging.getLogger(__name__)

DEFAULT_SSH_PORT = 22


def _temp_file(lines: List[str]) -> Path:
    """Create a temporary file with provided content and return its path

    :param lines: list of lines to be written in the file
    """
    _, path = tempfile.mkstemp(prefix="remote.", dir="/tmp", text=True)
    tmpfile = Path(path)
    tmpfile.write_text("\n".join(lines) + "\n")

    return tmpfile


def _gen_rsync_patterns_file(patterns, opt, args, cleanup):
    if patterns:
        exclude_file = _temp_file(patterns)
        cleanup.append(exclude_file)
        args.extend((opt, str(exclude_file)))
        logger.info(f"{opt} patterns:")
        for p in patterns:
            logger.info("  - %s", p)


@contextmanager
def _measure_duration(operation: str):
    start = time.time()
    yield None
    runtime = time.time() - start
    logger.info("%s done in %.2f seconds", operation, runtime)


@dataclass(frozen=True)
class ForwardingOption:
    """Port forwarding options for ssh"""

    remote_port: int
    local_port: int
    remote_interface: str = "localhost"
    local_interface: Optional[str] = None

    @classmethod
    def from_string(cls, port_args: str) -> "ForwardingOption":
        """Parse port values from the user input.
        :param host: the input string from port tunnelling option.
        :returns: A tuple of remote port, local port.
        """
        ports: List = port_args.split(":")
        if len(ports) > 2:
            raise InvalidInputError("Please pass a valid value to enable local port forwarding")
        try:
            if len(ports) == 1:
                return cls(int(ports[0]), int(ports[0]))
            return cls(int(ports[0]), int(ports[1]))
        except ValueError as e:
            raise InvalidInputError("Please pass valid integer value for ports") from e

    def to_ssh_string(self) -> str:
        prefix = f"{self.local_interface}:" if self.local_interface else ""
        return f"{prefix}{self.local_port}:{self.remote_interface}:{self.remote_port}"


class VerbosityLevel(IntEnum):
    QUIET = 1
    DEFAULT = 2
    VERBOSE = 3


@dataclass(frozen=True)
class CommunicationOptions:
    stdin: Optional[TextIO] = sys.stdin
    stdout: TextIO = sys.stdout
    stderr: TextIO = sys.stderr


@dataclass(frozen=True)
class Ssh:
    """Ssh configuration class, pregenrates and executes commands remotely"""

    host: str
    port: Optional[int] = None
    force_tty: bool = True
    verbosity_level: VerbosityLevel = VerbosityLevel.QUIET
    use_gssapi_auth: bool = True
    disable_password_auth: bool = True
    local_port_forwarding: List[ForwardingOption] = field(default_factory=list)
    communication: CommunicationOptions = CommunicationOptions()

    def generate_command(self) -> List[str]:
        """Generate the base ssh command to execute (without host)"""
        command = ["ssh"]
        options = "t" if self.force_tty else ""
        if self.use_gssapi_auth:
            options += "K"
        if self.verbosity_level <= VerbosityLevel.QUIET:
            options += "q"
        elif self.verbosity_level >= VerbosityLevel.VERBOSE:
            options += "v"

        if options:
            command.append(f"-{options}")
        if self.disable_password_auth:
            command.extend(("-o", "BatchMode=yes"))
        if self.port and self.port != DEFAULT_SSH_PORT:
            command.extend(("-p", str(self.port)))

        for port in self.local_port_forwarding:
            command.extend(("-L", port.to_ssh_string()))

        return command

    def generate_command_str(self) -> str:
        """Generate the base ssh command to execute (without host)"""
        return prepare_shell_command(self.generate_command())

    def execute(self, command: str, raise_on_error: bool = True) -> int:
        """Execute a command remotely using SSH and return it's exit code

        :param command: a command to execute
        :param raise_on_error: raise an exception is remote execution

        :returns: exit code of remote command or 255 if connection didn't go through
        """
        subprocess_command = self.generate_command()

        logger.info("Executing:\n%s %s <<EOS\n%sEOS", " ".join(subprocess_command), self.host, command)
        subprocess_command.extend((self.host, command))
        with _measure_duration("Execution"):
            result = subprocess.run(
                subprocess_command,
                stdout=self.communication.stdout,
                stderr=self.communication.stderr,
                stdin=self.communication.stdin,
            )

        if raise_on_error:
            # ssh exits with the exit status of the remote command or with 255 if an error occurred
            if result.returncode == 255:
                raise RemoteConnectionError(f"Failed to connect to {self.host}")
            elif result.returncode != 0:
                raise RemoteExecutionError(f'Failed to execute "{command}" on host {self.host} ({result.returncode})')
        return result.returncode


def rsync(
    src: str,
    dst: str,
    ssh: Ssh,
    info: bool = False,
    verbose: bool = False,
    dry_run: bool = False,
    delete: bool = False,
    mirror: bool = False,
    excludes: List[str] = None,
    includes: List[str] = None,
    extra_args: List[str] = None,
    communication=CommunicationOptions(),
):
    """Run rsync to sync files from src into dst

    :param src: Source files to copy. If source is a directory and you need to copy its contents, append / to its path
    :param dst: Destination file or directory
    :param ssh: ssh configuration to use for rsync
    :param info: True if need to add -i flag to rsync
    :param verbose: True if need to add -v flag to rsync
    :param dry_run: True if need to add -n flag to rsync
    :param delete: True if all files inside destination directory need to be deleted if they were not found at source and
                   they are not excluded by exclude filters
    :param mirror: True if all files inside destination directory need to be deleted if they were not found at source
    :param excludes: List of file patterns to exclude from syncing
    :param includes: List of file patterns to include even if they were excluded by exclude filters
    :param extra_args: Extra arguments for rsync function
    :param communication: file descriptors to use for process communication
    """

    logger.info("Sync files from %s to %s", src, dst)
    args = ["rsync", "-arlpmchz", "--copy-unsafe-links", "-e", ssh.generate_command_str(), "--force"]
    if info:
        args.append("-i")
    if verbose:
        args.append("-v")
    if dry_run:
        args.append("-n")
    if delete or mirror:
        args.append("--delete")
    if mirror:
        args.extend(("--delete-after", "--delete-excluded"))
    if extra_args:
        args.extend(extra_args)

    cleanup: List[Path] = []
    # It is important to add include patterns before exclude patters because rsync might ignore includes if you do otherwise.
    _gen_rsync_patterns_file(includes, "--include-from", args, cleanup)
    _gen_rsync_patterns_file(excludes, "--exclude-from", args, cleanup)

    args.extend((src, dst))

    logger.info("Starting sync with command %s", " ".join(args))
    with _measure_duration("Sync"):
        result = subprocess.run(args, stdout=communication.stdout, stderr=communication.stderr)

    for file in cleanup:
        file.unlink()

    if result.returncode != 0:
        raise RemoteConnectionError(f"Failed to sync files between {src} and {dst}. Is remote host reachable?")


def prepare_shell_command(command: Union[str, Sequence[str]]) -> str:
    """Format command parts into one shell command"""
    if isinstance(command, str):
        return command
    # This means the whole command is already preformatted for us
    if len(command) == 1 and " " in command[0]:
        return command[0]

    return " ".join([shlex.quote(c) for c in command])


def pformat_dataclass(obj, indent="  "):
    """Return a string with an object contents prettified"""
    result = []

    has_dataclass_fields = False
    for field in fields(obj):  # noqa: F402 'field' shadows the import
        value = getattr(obj, field.name)
        if is_dataclass(value):
            str_value = "\n" + pformat_dataclass(value, indent + "  ")
            has_dataclass_fields = True
        else:
            str_value = str(value)
        result.append((field.name, str_value))

    if has_dataclass_fields:
        return "\n".join(f"{indent}- {name}: {value}" for name, value in result)
    else:
        width = max(len(name) for name, _ in result)
        return "\n".join(f"{indent}- {name: <{width}}: {value}" for name, value in result)
