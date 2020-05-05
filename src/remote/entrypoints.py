import logging
import re
import sys

from functools import wraps
from pathlib import Path
from typing import List

import click

from .configuration import WorkspaceConfig
from .configuration.discovery import get_configuration_medium, load_cwd_workspace_config, save_config
from .exceptions import RemoteError
from .workspace import SyncedWorkspace

BASE_LOGGING_FORMAT = "%(message)s"
CONNECTION_STRING_FORMAT_REGEX = re.compile(r"^[-\w]+(\.[-\w]+)*(:(/)?[-.\w\s]+(/[-.\w\s]+)*)?(/)?$")
DEFAULT_CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])
EXECUTION_CONTEXT_SETTINGS = dict(
    help_option_names=["-h", "--help"], ignore_unknown_options=True, allow_interspersed_args=False
)


def log_exceptions(f):
    """A decorator that prints the custom exceptions and exit, but propagates internal ones"""

    @wraps(f)
    def wrapper(*args, **kwards):
        try:
            f(*args, **kwards)
        except Exception as e:
            if isinstance(e, RemoteError):
                click.secho(str(e), fg="yellow")
                sys.exit(1)
            raise

    return wrapper


def validate_connection_string(ctx, param, value):
    matcher = CONNECTION_STRING_FORMAT_REGEX.match(value)
    if matcher is None:
        raise click.BadParameter(
            "Please fix value to match the specified format for connection string", ctx=ctx, param=param
        )
    return value


def _add_remote_host(config: WorkspaceConfig, connection: str):
    """Add a new remote host to the workspace config, check the connection, and save it if connection is ok

    :param config: the workspace config decription object
    :param connection: connection string in format of 'host-name[:remote_dir]'
    """
    parts = connection.split(":")
    remote_host = parts[0]
    config_medium = get_configuration_medium(config)
    remote_dir = config_medium.generate_remote_directory(config) if len(parts) == 1 else Path(parts[1])

    added, index = config.add_remote_host(remote_host, remote_dir)
    if not added:
        click.echo(f"{connection} already exists in config")
        sys.exit(0)

    # Check if we can connect to the remote host and create a directory there
    workspace = SyncedWorkspace.from_config(config, config.root, index)
    code = workspace.execute(f"mkdir -p {workspace.remote.directory}", simple=True, raise_on_error=False)
    if code != 0:
        click.secho(f"Failed to create {workspace.remote.directory} on remote host {remote_host}", fg="yellow")
        click.secho(f"Please check if host is accessible via SSH", fg="yellow")
        sys.exit(1)

    click.echo(f"Created remote directory at {workspace.remote.host}:{workspace.remote.directory}")
    click.echo(f"Remote is configured and ready to use")

    # No errors when executing the above code means we can save the config
    config_medium.save_config(config)


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("connection", metavar="host-name[:remote_dir]", callback=validate_connection_string)
@log_exceptions
def remote_add(connection: str):
    """Add one more host for remote connection to a config file"""

    config = load_cwd_workspace_config()
    _add_remote_host(config, connection)


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("connection", metavar="host-name[:remote_dir]", callback=validate_connection_string)
@log_exceptions
def remote_init(connection: str):
    """Initiate workspace for the remote execution in the current working directory"""

    try:
        load_cwd_workspace_config()
        click.secho("A configured workspace already exists in the current directory.", fg="yellow")
        click.secho("If you want to add a new host to it, please use remote-add.", fg="yellow")
        sys.exit(1)
    except RemoteError:
        # we expect it to fail. It means we don't overwrite an existing workspace
        pass

    config = WorkspaceConfig.empty(Path.cwd())
    _add_remote_host(config, connection)

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

    click.echo("Added '.remote*' to .gitignore")


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("ignore", nargs=-1, required=True)
@log_exceptions
def remote_ignore(ignore: List[str]):
    """Add new IGNORE patterns to the ignores list

    IGNORE pattern should be a string in rsync-friendly format.
    """

    config = load_cwd_workspace_config()
    config.ignores.add_ignores(ignore)
    save_config(config)


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@log_exceptions
def remote_host():
    """Print the default remote host in use and exit"""
    workspace = SyncedWorkspace.from_cwd()
    click.echo(workspace.remote.host)


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.argument("index", type=int)
@log_exceptions
def remote_set(index: int):
    """Set a new default remote host for the workspace

    INDEX is an index of host in config file to use by default (strating from 1)
    """

    config = load_cwd_workspace_config()
    if len(config.configurations) < index:
        click.secho(
            f"Index is too big ({index}). Only have {len(config.configurations)} hosts to choose from.", fg="yellow"
        )
        sys.exit(1)
    elif index < 1:
        click.secho(f"Index should be 1 or higher", fg="yellow")
        sys.exit(1)
    # we use 0-base index internally
    index = index - 1
    config.default_configuration = index
    save_config(config)

    click.echo(f"Remote host is set to {config.configurations[index].host}")


@click.command(context_settings=EXECUTION_CONTEXT_SETTINGS)
@click.option("-n", "--dry-run", is_flag=True, help="do a dry run of the whole cycle")
@click.option("-m", "--mirror", is_flag=True, help="mirror local files on the remote host")
@click.option("-v", "--verbose", is_flag=True, help="increase verbosity")
@click.option("-e", is_flag=True, help="(deprecated) kept for backward compatibility, noop")
@click.argument("command", nargs=-1, required=True)
@log_exceptions
def remote(command: List[str], dry_run: bool, mirror: bool, verbose: bool, e: bool):
    """Sync local workspace files to remote machine, execute the COMMAND and sync files back regardless of the result"""

    if verbose:
        logging.basicConfig(level=logging.INFO, format=BASE_LOGGING_FORMAT)

    workspace = SyncedWorkspace.from_cwd()
    exit_code = workspace.execute_in_synced_env(command, dry_run=dry_run, verbose=verbose, mirror=mirror)
    if exit_code != 0:
        click.secho(f"Remote command exited with {exit_code}", fg="yellow")

    sys.exit(exit_code)


@click.command(context_settings=EXECUTION_CONTEXT_SETTINGS)
@click.argument("command", nargs=-1, required=True)
@log_exceptions
def remote_quick(command: List[str]):
    """Execute the COMMAND remotely"""
    workspace = SyncedWorkspace.from_cwd()
    code = workspace.execute(command, raise_on_error=False)
    sys.exit(code)


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option("-n", "--dry-run", is_flag=True, help="do a dry run of a pull")
@click.option("-v", "--verbose", is_flag=True, help="increase verbosity")
@click.argument("path", nargs=-1)
@log_exceptions
def remote_pull(dry_run: bool, verbose: bool, path: List[str]):
    """Bring in files from the default remote directory to local workspace.
    Optionally bring in PATH instead of the whole workspace.

    PATH is a path of file or directory to bring back relative to the remote workspace root.
    All sync exclude rules will be omitted if PATH is provided.
    """

    if verbose:
        logging.basicConfig(level=logging.INFO, format=BASE_LOGGING_FORMAT)

    workspace = SyncedWorkspace.from_cwd()
    if not path:
        workspace.pull(info=True, verbose=verbose, dry_run=dry_run)
        return

    for subpath in path:
        workspace.pull(info=True, verbose=verbose, dry_run=dry_run, subpath=subpath)


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option("-n", "--dry-run", is_flag=True, help="do a dry run of a push")
@click.option("-m", "--mirror", is_flag=True, help="mirror local files on the remote host")
@click.option("-v", "--verbose", is_flag=True, help="increase verbosity")
@click.option(
    "--mass", is_flag=True, help="push files to all available remote workspaces instead of pushing to the default one"
)
@log_exceptions
def remote_push(dry_run: bool, mirror: bool, verbose: bool, mass: bool):
    """Push local workspace files to the remote directory"""

    if verbose:
        logging.basicConfig(level=logging.INFO, format=BASE_LOGGING_FORMAT)

    workspaces = SyncedWorkspace.from_cwd_mass() if mass else [SyncedWorkspace.from_cwd()]
    for workspace in workspaces:
        workspace.push(info=True, verbose=verbose, dry_run=dry_run, mirror=mirror)


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@log_exceptions
def remote_delete():
    """Delete the remote directory"""
    workspace = SyncedWorkspace.from_cwd()
    workspace.clear_remote()
    click.echo(f"Successfully deleted {workspace.remote.directory} on host {workspace.remote.host}")


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@log_exceptions
def remote_explain():
    click.secho("Sorry, remote-explain is not yet implemented in the new version of Remote.", fg="yellow")
    click.secho("Please use the old one if you need it", fg="yellow")
    sys.exit(1)


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@log_exceptions
def mremote():
    click.secho("Sorry, mremote is not yet implemented in the new version of Remote.", fg="yellow")
    click.secho("Please use the old one if you need it", fg="yellow")
    sys.exit(1)


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@log_exceptions
def mremote_push():
    click.secho("mremote-push is deprecated. Please use 'remote-push --mass' instead.", fg="yellow")
