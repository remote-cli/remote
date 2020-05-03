import logging
import subprocess
import sys
import tempfile
import time

from pathlib import Path
from typing import List

from .exceptions import RemoteConnectionError

logger = logging.getLogger(__name__)


def _temp_file(lines: List[str]) -> Path:
    """Create a temporary file with provided content and return its path

    :param lines: list of lines to be written in the file
    """
    tmpfile = Path(tempfile.mktemp(prefix="remote.", dir="/tmp"))
    tmpfile.write_text("\n".join(lines) + "\n")

    return tmpfile


def rsync(
    src: str,
    dst: str,
    info=False,
    verbose=False,
    dry_run=False,
    mirror=False,
    excludes=None,
    includes=None,
    extra_args=None,
):
    """Run rsync to sync files from src into dst"""

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
    cleanup = []
    if excludes:
        exclude_file = _temp_file(excludes)
        cleanup.append(exclude_file)
        args.extend(("--exclude-from", str(exclude_file)))
        logger.info("Excluded patterns:")
        for p in excludes:
            logger.info("  - %s", p)
    if includes:
        include_file = _temp_file(includes)
        cleanup.append(include_file)
        args.extend(("--include-from", str(include_file)))
        logger.info("Included patterns:")
        for p in excludes:
            logger.info("  - %s", p)

    args.extend((src, dst))

    logger.info("Starting sync with command %s", " ".join(args))
    start = time.time()
    try:
        result = subprocess.run(args, stdout=sys.stdout, stderr=sys.stderr)
        if result.returncode != 0:
            raise RemoteConnectionError(f"Failed to sync files betwen {src} and {dst}. Is remote host reachable")
    finally:
        for file in cleanup:
            file.unlink()
        runtime = time.time() - start
    logger.info("Sync done in %.2f seconds", runtime)
