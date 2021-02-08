import logging
import re
import sys

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import List, Optional, Union

import click

from .configuration import WorkspaceConfig
from .configuration.discovery import get_configuration_medium, load_cwd_workspace_config, save_config
from .configuration.shared import HOST_REGEX, PATH_REGEX
from .exceptions import InvalidInputError, RemoteError
from .explain import explain
from .util import CommunicationOptions, ForwardingOption
from .workspace import SyncedWorkspace

BASE_LOGGING_FORMAT = "%(message)s"
CONNECTION_STRING_FORMAT_REGEX = re.compile(f"^{HOST_REGEX}(:{PATH_REGEX})?$")
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


def int_or_str_label(label: Optional[str]) -> Optional[Union[int, str]]:
    """Try to convert the label to int and return the result, if it's not successful, return the label"""
    if label is None:
        return None
    try:
        # Users enter indexes starting with 1 and internally we use indexes starting with 0
        return int(label) - 1
    except ValueError:
        return label


def check_command(command: List[str]):
    if command and command[0].startswith("-"):
        # Our execution entry points use ignore_unknown_options=True and allow_interspersed_args=False
        # to be able to stream the command to the remote machine. However, there is a downside.
        # If user runs this command with an unknown option, this option will become a part of the command.
        # That's why we need to manually check if the command starts with an unknown option and print an
        # error message in this case.
        ctx = click.get_current_context()
        click.echo(ctx.get_usage())
        click.echo(f"Try '{ctx.info_name} -h' for help\n\nError: no such option {command[0]}")
        sys.exit(2)


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
    try:
        workspace.create_remote()
    except RemoteError:
        click.secho(f"Failed to create {workspace.remote.directory} on remote host {remote_host}", fg="yellow")
        click.secho("Please check if host is accessible via SSH", fg="yellow")
        sys.exit(1)

    click.echo(f"Created remote directory at {workspace.remote.host}:{workspace.remote.directory}")
    click.echo("Remote is configured and ready to use")

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
        workspace = load_cwd_workspace_config()
        if workspace.root == Path.cwd():
            click.secho("A configured workspace already exists in the current working directory.", fg="yellow")
        else:
            click.secho(
                f"A configured workspace already initiated in the current working directory's parent {workspace.root}.",
                fg="yellow",
            )
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
@click.option(
    "-p", "--push", is_flag=True, help="add IGNORE pattern to push ignore list (mutually exclusive with '--pull')"
)
@click.option(
    "-l", "--pull", is_flag=True, help="add IGNORE pattern to pull ignore list (mutually exclusive with '--push')"
)
@click.argument("ignore", nargs=-1, required=True)
@log_exceptions
def remote_ignore(ignore: List[str], push: bool, pull: bool):
    """Add new IGNORE patterns to the ignores list

    IGNORE pattern should be a string in rsync-friendly format.
    If no options provided these patterns will be ignored on both push and pull
    """

    config = load_cwd_workspace_config()
    if not push and not pull:
        config.ignores.add(ignore)
    elif pull and not push:
        config.ignores.pull.add(ignore)
    elif push and not pull:
        config.ignores.push.add(ignore)
    else:
        raise InvalidInputError("You cannot use both '--pull' and '--push' flags")
    config.ignores.trim()

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
        click.secho("Index should be 1 or higher", fg="yellow")
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
@click.option(
    "-t",
    "--tunnel",
    "port_args",
    type=str,
    multiple=True,
    help="Enable local port forwarding. Pass value as <remote port>:<local port>. \
If local port is not passed, the local port value would be set to <remote port> value by default",
)
@click.option(
    "-s",
    "--stream-changes",
    default=False,
    is_flag=True,
    help="Resync local changes if any while the command is being run remotely",
)
@click.option("-l", "--label", help="use the host that has corresponding label for the remote execution")
@click.option("--multi", is_flag=True, help="sync and run the remote commands on each remote host from config")
@click.option(
    "--log",
    type=click.Path(file_okay=False, resolve_path=True),
    help="Write sync and remote command output to the log file instead of stdout. "
    "Log file will be located inside DIRECTORY/<timestamp>/<host>_output.log",
)
@click.argument("command", nargs=-1, required=True)
@log_exceptions
def remote(
    command: List[str],
    dry_run: bool,
    mirror: bool,
    verbose: bool,
    e: bool,
    port_args: List[str],
    label: Optional[str],
    stream_changes: bool,
    log: Optional[str],
    multi: bool,
):
    """Sync local workspace files to remote machine, execute the COMMAND and sync files back regardless of the result"""

    check_command(command)
    if verbose:
        logging.basicConfig(level=logging.INFO, format=BASE_LOGGING_FORMAT)

    ports = [ForwardingOption.from_string(port_arg) for port_arg in port_args]

    if multi and label:
        raise InvalidInputError("--multi and --label options cannot be used together")

    workspaces = SyncedWorkspace.from_cwd_mass() if multi else [SyncedWorkspace.from_cwd(int_or_str_label(label))]
    with ThreadPoolExecutor(max_workers=len(workspaces)) as executor:
        futures = {}
        descriptors = []
        start_timestamp = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
        for workspace in workspaces:
            host = workspace.remote.host
            if multi or log:
                # We save logs into the <log_dir>/<timestamp>/<hostname>_output.log
                log_dir = Path(log) if log else (workspace.local_root / "logs")
                log_dir = log_dir / start_timestamp
                log_dir.mkdir(parents=True, exist_ok=True)

                try:
                    # If the logs are enabled and they are inside the workspace root, we need to exclude them from
                    # syncing
                    relative_path = log_dir.relative_to(workspace.local_root)

                    log_path = f"{relative_path}/*_output.log"
                    workspace.pull_rules.excludes.append(log_path)
                    workspace.push_rules.excludes.append(log_path)
                except ValueError:
                    # Value error means that logs are placed outside of the workspace root
                    pass
                fd = (log_dir / f"{host}_output.log").open("w")
                descriptors.append(fd)
                workspace.communication = CommunicationOptions(stdin=None, stdout=fd, stderr=fd)

            future = executor.submit(
                workspace.execute_in_synced_env,
                command,
                dry_run=dry_run,
                verbose=verbose,
                mirror=mirror,
                ports=ports,
                stream_changes=stream_changes,
            )
            futures[future] = workspace

        final_exit_code = 0
        for future in as_completed(list(futures.keys())):
            workspace = futures[future]
            try:
                exit_code = future.result(timeout=0)
                if exit_code != 0:
                    click.secho(f"Remote command on {workspace.remote.host} exited with {exit_code}", fg="yellow")
                    final_exit_code = exit_code
            except Exception as e:  # noqa: F841
                class_name = e.__class__.__name__
                click.secho(f"{class_name}: {e}", fg="yellow")
                final_exit_code = 255

        for fd in descriptors:
            fd.close()

    sys.exit(final_exit_code)


@click.command(context_settings=EXECUTION_CONTEXT_SETTINGS)
@click.option(
    "-t",
    "--tunnel",
    "port_args",
    type=str,
    multiple=True,
    help="Enable local port forwarding. Pass value as <remote port>:<local port>. \
If local port is not passed, the local port value would be set to <remote port> value by default",
)
@click.option("-l", "--label", help="use the host that has corresponding label for the remote execution")
@click.argument("command", nargs=-1, required=True)
@log_exceptions
def remote_quick(
    command: List[str], port_args: List[str], label: Optional[str],
):
    """Execute the COMMAND remotely, without syncing any files"""
    check_command(command)

    ports = [ForwardingOption.from_string(port_arg) for port_arg in port_args]

    workspace = SyncedWorkspace.from_cwd(int_or_str_label(label))
    code = workspace.execute(command, ports=ports, raise_on_error=False)
    sys.exit(code)


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option("-n", "--dry-run", is_flag=True, help="do a dry run of a pull")
@click.option("-v", "--verbose", is_flag=True, help="increase verbosity")
@click.option("-l", "--label", help="use the host that has corresponding label for the remote execution")
@click.argument("path", nargs=-1)
@log_exceptions
def remote_pull(dry_run: bool, verbose: bool, path: List[str], label: Optional[str]):
    """Bring in files from the default remote directory to local workspace.
    Optionally bring in PATH instead of the whole workspace.

    PATH is a path of file or directory to bring back relative to the remote workspace root.
    All sync exclude rules will be omitted if PATH is provided.
    """

    if verbose:
        logging.basicConfig(level=logging.INFO, format=BASE_LOGGING_FORMAT)

    workspace = SyncedWorkspace.from_cwd(int_or_str_label(label))
    if not path:
        workspace.pull(info=True, verbose=verbose, dry_run=dry_run)
        return

    for subpath in path:
        workspace.pull(info=True, verbose=verbose, dry_run=dry_run, subpath=Path(subpath))


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option("-n", "--dry-run", is_flag=True, help="do a dry run of a push")
@click.option("-m", "--mirror", is_flag=True, help="mirror local files on the remote host")
@click.option("-v", "--verbose", is_flag=True, help="increase verbosity")
@click.option("-l", "--label", help="use the host that has corresponding label for the remote execution")
@click.option(
    "--multi", is_flag=True, help="push files to all available remote workspaces instead of pushing to the default one"
)
@log_exceptions
def remote_push(dry_run: bool, mirror: bool, verbose: bool, multi: bool, label: Optional[str]):
    """Push local workspace files to the remote directory"""

    if verbose:
        logging.basicConfig(level=logging.INFO, format=BASE_LOGGING_FORMAT)

    if multi and label:
        raise InvalidInputError("--multi and --label options cannot be used together")

    workspaces = SyncedWorkspace.from_cwd_mass() if multi else [SyncedWorkspace.from_cwd(int_or_str_label(label))]
    for workspace in workspaces:
        workspace.push(info=True, verbose=verbose, dry_run=dry_run, mirror=mirror)


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option("-l", "--label", help="use the host that has corresponding label for the remote execution")
@log_exceptions
def remote_delete(label: Optional[str]):
    """Delete the remote directory"""
    workspace = SyncedWorkspace.from_cwd(int_or_str_label(label))
    workspace.clear_remote()
    click.echo(f"Successfully deleted {workspace.remote.directory} on host {workspace.remote.host}")


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@click.option("-l", "--label", help="use the host that has corresponding label for the remote execution")
@click.option("-d", "--deep", is_flag=True, help="check latency and download/upload speed if connection is ok")
@log_exceptions
def remote_explain(label: Optional[str], deep: bool):
    """Print out various debug information to debug the workspace"""
    logging.basicConfig(level=logging.INFO, format=BASE_LOGGING_FORMAT)

    workspace = SyncedWorkspace.from_cwd(int_or_str_label(label))
    explain(workspace, deep)


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@log_exceptions
def mremote():
    click.secho("mremote is deprecated. Please use 'remote --multi' instead.", fg="yellow")
    sys.exit(1)


@click.command(context_settings=DEFAULT_CONTEXT_SETTINGS)
@log_exceptions
def mremote_push():
    click.secho("mremote-push is deprecated. Please use 'remote-push --multi' instead.", fg="yellow")
    sys.exit(1)
