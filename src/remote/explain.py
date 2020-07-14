import subprocess
import sys

from typing import Optional
from uuid import uuid4

import click

from .util import pformat_dataclass
from .workspace import SyncedWorkspace

SPEED_TEST_FILE_SIZE_MB = 25


def explain(workspace: SyncedWorkspace, deep: bool, host_override: Optional[str] = None) -> None:
    """Print out various debug information to debug the workspace"""

    # First, print out the configuration in use
    click.secho("Configuration:", fg="yellow")
    click.echo(pformat_dataclass(workspace))
    click.echo()

    # Then, check if host is pingable
    # It might not be pingable if the user has ssh alias in configuration
    click.secho("Checking connection.", fg="yellow")
    remote_host = host_override or workspace.remote.host
    ping_result = subprocess.run(["ping", "-c", "1", remote_host], capture_output=True, text=True)
    if ping_result.returncode == 0:
        click.secho("The remote host is reachable", fg="green")
    else:
        click.secho("The remote host is unreachable:", fg="red")
        click.secho(f"{ping_result.stderr}", fg="red")
        click.echo("We will try to do an ssh connection anyway, since the host in config may be an ssh alias")

    # Then, try to execute a command remotely. It will show us if there are any ssh-related issues
    quick_exec_code = workspace.execute("test", simple=True, raise_on_error=False, verbose=True)
    if quick_exec_code == 255:
        click.secho(
            "The remote host is unreachable or doesn't support passwordless connection", fg="red",
        )
        sys.exit(1)

    click.secho("The remote host supports passwordless connection via SSH", fg="green")
    click.echo()

    # Then, do a sync dry-run. It will show us what wiles will be synced.
    click.secho("Doing a dry-run of a full execution cycle.", fg="yellow")
    execution_code = workspace.execute_in_synced_env(["Hello World"], verbose=True, dry_run=True)
    if execution_code != 0:
        click.secho(
            "Execution cycle failed", fg="red",
        )
        sys.exit(1)

    if not deep:
        return

    # If deep check is required, we will also check for average ping, download and upload speed
    click.echo()
    if ping_result.returncode == 0:
        # Only check for latency if the ping was successful before
        click.secho("Checking latency.", fg="yellow")
        ping_result = subprocess.run(["ping", "-c", "10", remote_host], capture_output=True, text=True)
        for line in ping_result.stdout.splitlines():
            if line.startswith("round-trip") or "transmitted" in line:
                click.echo(line)
    else:
        click.secho("Not checking latency since the previous ping attemp failed", fg="yellow")
    click.echo()

    # Create a file remotely and try to download it
    filename = f"speed_test_{uuid4()}"
    click.secho(
        f"Pulling {SPEED_TEST_FILE_SIZE_MB}MB file from the remote host to check the download speed.", fg="yellow"
    )
    workspace.execute(f"dd if=/dev/urandom of={filename} bs=1048576 count={SPEED_TEST_FILE_SIZE_MB} &>/dev/null")
    workspace.pull(info=True, verbose=True, subpath=filename)
    # Remove a file remotely to be able to upload it
    workspace.execute(f"rm {filename}")
    click.echo()

    # Upload the same file to the remote machine
    click.secho(f"Pushing {SPEED_TEST_FILE_SIZE_MB}MB file to the remote host to check the upload speed.", fg="yellow")
    workspace.push(info=True, verbose=True, subpath=filename)
    # Clean up the file locally and remotely
    if (workspace.local_root / filename).exists():
        (workspace.local_root / filename).unlink()
    workspace.execute(f"rm {filename}")
    click.echo()
