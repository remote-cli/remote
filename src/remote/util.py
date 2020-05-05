import logging
import re
import subprocess
import sys
import tempfile
import time

from contextlib import contextmanager
from pathlib import Path
from typing import List, Sequence, Union

from .exceptions import RemoteConnectionError, RemoteExecutionError

logger = logging.getLogger(__name__)


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


def rsync(
    src: str,
    dst: str,
    info: bool = False,
    verbose: bool = False,
    dry_run: bool = False,
    mirror: bool = False,
    excludes: List[str] = None,
    includes: List[str] = None,
    extra_args: List[str] = None,
):
    """Run rsync to sync files from src into dst

    :param src: Source files to copy. If source is a directory and you need to copy its contents, append / to its path
    :param dst: Destination file or directory
    :param info: True if need to add -i flag to rsync
    :param verbose: True if need to add -v flag to rsync
    :param dry_run: True if need to add -n flag to rsync
    :param mirror: True if all files inside destination directory need to be deleted if they were not bringed from source
    :param excludes: List of file patterns to exclude from syncing
    """

    logger.info("Sync files from %s to %s", src, dst)
    args = ["rsync", "-rlpmchz", "--copy-unsafe-links", "-e", "ssh -q", "--force"]
    if info:
        args.append("-i")
    if verbose:
        args.append("-v")
    if dry_run:
        args.append("-n")
    if mirror:
        args.extend(("--delete", "--delete-after", "--delete-excluded"))
    if extra_args:
        args.extend(extra_args)

    cleanup: List[Path] = []
    # It is important to add include patterns before exclude patters because rsync might ignore includes if you do otherwise.
    _gen_rsync_patterns_file(includes, "--include-from", args, cleanup)
    _gen_rsync_patterns_file(excludes, "--exclude-from", args, cleanup)

    args.extend((src, dst))

    logger.info("Starting sync with command %s", " ".join(args))
    with _measure_duration("Sync"):
        result = subprocess.run(args, stdout=sys.stdout, stderr=sys.stderr)

    for file in cleanup:
        file.unlink()

    if result.returncode != 0:
        raise RemoteConnectionError(f"Failed to sync files betwen {src} and {dst}. Is remote host reachable")


def prepare_shell_command(command: Union[str, Sequence[str]]) -> str:
    """Format command parts into one shell command"""
    if isinstance(command, str):
        return command
    # This means the whole command is already preformatted for us
    if len(command) == 1 and " " in command[0]:
        return command[0]

    result = []
    for item in command:
        if not item:
            continue
        if re.search(r"\s+", item):
            result.append(f"'{item}'")
        else:
            result.append(item)

    return " ".join(result)


def ssh(host: str, command: str, dry_run: bool = False, raise_on_error: bool = True):
    """Execute a command remotely using SSH and return it's exit code

    :param host: a name of the host that will be used for execution
    :param command: a command to execute
    :param dry_run: log command instead of executing it
    :param raise_on_error: raise an exception is remote execution

    :returns: exit code of remote command or 255 if connection didn't go through
    """
    subprocess_command = ["ssh", "-tKq", host, command]
    logger.info("Executing:\n%s %s %s <<EOS\n%sEOS", *subprocess_command)
    if dry_run:
        return 0

    with _measure_duration("Execution"):
        result = subprocess.run(subprocess_command, stdout=sys.stdout, stderr=sys.stderr, stdin=sys.stdin)

    if raise_on_error:
        # ssh exits with the exit status of the remote command or with 255 if an error occurred
        if result.returncode == 255:
            raise RemoteConnectionError(f"Failed to connect to {host}")
        elif result.returncode != 0:
            raise RemoteExecutionError(f'Failed to execute "{command}" on host {host} ({result.returncode})')
    return result.returncode
