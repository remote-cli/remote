import hashlib

from pathlib import Path

DEFAULT_REMOTE_ROOT = ".remotes"
HOST_REGEX = r"[-\w]+(\.[-\w]+)*"
PATH_REGEX = r"/?[-.\w\s]+(/[-.\w\s]+)*/?"


def hash_path(path: Path):
    return hashlib.md5(str(path).encode()).hexdigest()[:8]
