import argparse
import logging
import sys

from functools import wraps

from .configuration import WorkspaceConfig
from .configuration.classic import save_config
from .configuration.discovery import load_cwd_workspace_config
from .exceptions import RemoteError
from .workspace import SyncedWorkspace

BASE_LOGGING_FORMAT = "%(message)s"


def log_exceptions(f):
    """A decorator that prints the custom exceptions and exit, but propagates internal ones"""

    @wraps(f)
    def wrapper(*args, **kwards):
        try:
            f(*args, **kwards)
        except Exception as e:
            if isinstance(e, RemoteError):
                print(str(e))
                sys.exit(1)
            raise

    return wrapper


def _add_remote_host(config: WorkspaceConfig, connection: str):
    """Add a new remote host to the workspace config, check the connection, and save it if connection is ok

    :param config: the workspace config decription object
    :param connection: connection string in format of 'host-name[:remote_dir]'
    """
    parts = connection.split(":")
    if len(parts) > 2:
        print(f"Please use 'host-name[:remote_dir]' format for connection string")
        sys.exit(1)
    remote_host = parts[0]
    remote_dir = None if len(parts) == 1 else parts[1]

    added, index = config.add_remote_host(remote_host, remote_dir)
    if not added:
        print(f"{connection} already exists in config")
        sys.exit(0)

    # Check if we can connect to the remote host and create a directory there
    workspace = SyncedWorkspace.from_config(config, config.root, index)
    workspace.execute(f"mkdir -p {workspace.remote.directory}", simple=True)
    print(f"Created remote directory at {workspace.remote.host}:{workspace.remote.directory}")

    # No errors when executing the above code means we can save the config
    save_config(config)


@log_exceptions
def remote_add():
    parser = argparse.ArgumentParser(description="Add one more host for remote connection to a config file")
    parser.add_argument(
        "connection", metavar="host-name[:remote_dir]", type=str, help="a connection string for new remote directory"
    )
    args = parser.parse_args()

    config = load_cwd_workspace_config()
    _add_remote_host(config, args.connection)


@log_exceptions
def remote_init():
    parser = argparse.ArgumentParser(
        description="Initiate workspace for the remote execution in the current working directory"
    )
    parser.add_argument(
        "connection", metavar="host-name[:remote_dir]", type=str, help="a connection string for new remote directory"
    )
    args = parser.parse_args()

    config = WorkspaceConfig.empty()
    _add_remote_host(config, args.connection)

    # help out with .gitignore if we are in a git repository
    if not (config.root / ".git").exists():
        return

    # make sure we don't keep adding to .gitignore
    gitignore = config.root / ".gitignore"
    if gitignore.exists():
        for line in gitignore.read_text().splitlines():
            if line.startswith(".remote"):
                return

    with gitignore.open("a") as f:
        f.write("\n")
        f.write(".remote*")
        f.write("\n")

    print("Added '.remote*' to .gitignore")


@log_exceptions
def remote_ignore():
    parser = argparse.ArgumentParser(description="Add more patterns to the ignores list")
    parser.add_argument("ignore", type=str, nargs="+", help="a pattern describing a file to ignore in rsync format")
    args = parser.parse_args()

    config = load_cwd_workspace_config()
    config.ignores.add_ignores(args.ignore)
    save_config(config)


@log_exceptions
def remote_host():
    """Print the remote host in use and exit"""
    workspace = SyncedWorkspace.from_cwd()
    print(workspace.remote.host)


@log_exceptions
def remote_set():
    parser = argparse.ArgumentParser(description="Set a new default remote host for the workspace")
    parser.add_argument("index", type=int, help="an index of host in config file to use by default (strating from 1)")
    args = parser.parse_args()

    config = load_cwd_workspace_config()
    if len(config.configurations) < args.index:
        print(f"Index is too big ({args.index}). Only have {len(config.configurations)} hosts to choose from.")
        sys.exit(1)
    elif args.index < 1:
        print(f"Index should be 1 or higher")
        sys.exit(1)
    # we use 0-base index internally
    index = args.index - 1
    config.default_configuration = index
    save_config(config)

    print(f"Remote host is set to {config.configurations[index].host}")


@log_exceptions
def remote():
    parser = argparse.ArgumentParser(
        description="Sync local workspace with remote directory and execute the command remotely"
    )
    parser.add_argument("-n", "--dry-run", action="store_true", help="do a dry run of a pull")
    parser.add_argument("-m", "--mirror", action="store_true", help="mirror local files on remote host")
    parser.add_argument("-v", "--verbose", action="store_true", help="increase verbosity")
    parser.add_argument(
        "-e", action="store_true", help="(deprecated) no effect in the new implementation",
    )
    parser.add_argument("command", type=str, nargs=argparse.REMAINDER, help="a command to execute")
    args = parser.parse_args()

    if not args.command:
        print("Missing command")
        sys.exit(1)

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format=BASE_LOGGING_FORMAT)

    workspace = SyncedWorkspace.from_cwd()
    workspace.push(dry_run=args.dry_run, verbose=args.verbose, mirror=args.mirror)
    exit_code = workspace.execute(args.command, dry_run=args.dry_run, raise_on_error=False)
    if exit_code != 0:
        print(f"Remote command exited with {exit_code}")
    workspace.pull(dry_run=args.dry_run, verbose=args.verbose)

    sys.exit(exit_code)


@log_exceptions
def remote_quick():
    """Execute the command remotely"""
    workspace = SyncedWorkspace.from_cwd()
    workspace.execute(sys.argv[1:])


@log_exceptions
def remote_pull():
    parser = argparse.ArgumentParser(description="Bring in files from remote directory to local workspace")
    parser.add_argument("-n", "--dry-run", action="store_true", help="do a dry run of a pull")
    parser.add_argument("-v", "--verbose", action="store_true", help="increase verbosity")
    parser.add_argument(
        "path", type=str, nargs="?", default=None, help="a relative path of file or directory to bring back"
    )
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format=BASE_LOGGING_FORMAT)

    workspace = SyncedWorkspace.from_cwd()
    workspace.pull(info=True, verbose=args.verbose, dry_run=args.dry_run, subpath=args.path)


@log_exceptions
def remote_push(mass=False):
    parser = argparse.ArgumentParser(description="Push local files to remote directory")
    parser.add_argument("-n", "--dry-run", action="store_true", help="do a dry run of a push")
    parser.add_argument("-m", "--mirror", action="store_true", help="mirror local files on remote host")
    parser.add_argument("-v", "--verbose", action="store_true", help="increase verbosity")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format=BASE_LOGGING_FORMAT)

    workspaces = SyncedWorkspace.from_cwd_mass() if mass else [SyncedWorkspace.from_cwd()]
    for workspace in workspaces:
        workspace.push(info=True, verbose=args.verbose, dry_run=args.dry_run, mirror=args.mirror)


@log_exceptions
def mremote_push():
    """Same as remote_push, but will push files to all possible remote locations configured for workspace"""
    remote_push(mass=True)


@log_exceptions
def remote_delete():
    """Delete remote directory"""
    workspace = SyncedWorkspace.from_cwd()
    workspace.clear_remote()
    print(f"Successfully deleted {workspace.remote.directory} on host {workspace.remote.host}")


@log_exceptions
def remote_explain():
    print("Sorry, remote-explain is not yet implemented in the new version of Remote.")
    print("Please use the old one if you need it")
    sys.exit(1)


@log_exceptions
def mremote():
    print("Sorry, mremote is not yet implemented in the new version of Remote.")
    print("Please use the old one if you need it")
    sys.exit(1)
