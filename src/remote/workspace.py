import logging

from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Optional, Tuple, Union

from remote.exceptions import InvalidRemoteHostLabel

from .configuration import RemoteConfig, SyncRules, WorkspaceConfig
from .configuration.discovery import load_cwd_workspace_config
from .util import ForwardingOptions, Ssh, prepare_shell_command, rsync

logger = logging.getLogger(__name__)


@dataclass
class SyncedWorkspace:
    """A configured remote execution workspace"""

    # absolute path to the root of the local project
    local_root: Path
    # information about the remote host to use
    remote: RemoteConfig
    # remote directory to use as working directory, relative to users home directory
    remote_working_dir: Path
    # sync ignore file patterns
    ignores: SyncRules
    # sync include file patterns
    includes: SyncRules

    @classmethod
    def from_config(
        cls, config: WorkspaceConfig, working_dir: Path, remote_host_id: Optional[Union[str, int]] = None
    ) -> "SyncedWorkspace":
        """Create a workspace from configuration object

        :param config: workspace config
        :param working_dir: a working directory inside the workspace config
        :param remote_host_id: if present, and is a string, filters by label
        """
        working_dir = working_dir.relative_to(config.root)
        if remote_host_id is None:
            index = config.default_configuration
        elif type(remote_host_id) == str:
            index = next(
                (
                    index
                    for index, remote_config in enumerate(config.configurations)
                    if remote_config.label == remote_host_id
                ),
                None,
            )
            if index is None:
                raise InvalidRemoteHostLabel(f"The label {remote_host_id} cannot be found in the configuration")
        else:
            index = remote_host_id
        remote_config = config.configurations[index]
        remote_working_dir = remote_config.directory / working_dir

        return cls(
            local_root=config.root,
            remote=remote_config,
            remote_working_dir=remote_working_dir,
            ignores=config.ignores,
            includes=config.includes,
        )

    @classmethod
    def from_cwd(cls) -> "SyncedWorkspace":
        """Load a workspace from current working directory of user"""
        config = load_cwd_workspace_config()
        return cls.from_config(config, Path.cwd())

    @classmethod
    def from_cwd_mass(cls) -> List["SyncedWorkspace"]:
        """Load all possible workspaces from current working directory of user"""
        config = load_cwd_workspace_config()

        workspaces = []
        for i in range(len(config.configurations)):
            workspaces.append(cls.from_config(config, Path.cwd(), i))

        return workspaces

    def get_ssh(self, port_forwarding: Optional[ForwardingOptions] = None):
        return Ssh(self.remote.host, use_gssapi_auth=self.remote.supports_gssapi, local_port_forwarding=port_forwarding)

    def get_ssh_for_rsync(self):
        ssh = self.get_ssh()
        return replace(ssh, force_tty=False)

    def _generate_command(self, command: str) -> str:
        return f"""\
if [ -f {self.remote.directory}/.remoteenv ]; then
  source {self.remote.directory}/.remoteenv 2>/dev/null 1>/dev/null
fi
cd {self.remote_working_dir}
{command}
"""

    def execute_in_synced_env(
        self,
        command: Union[str, List[str]],
        simple: bool = False,
        verbose: bool = False,
        dry_run: bool = False,
        mirror: bool = False,
        ports: Optional[Tuple[int, int]] = None,
    ) -> int:
        """Execute a command remotely using ssh. Push the local files to remote location before that and
        pull them back after command was executed regardless of the result.

        This command won't throw an exception if remote process fails

        :param command: a command to be executed or its parts
        :param simple: True if command don't need to be preformatted and wrapped before execution.
                       commands with simple will be executed from user's remote home directory
        :param dry_run: don't sync files. log the command to be executed but don't run it
        :param verbose: use verbose logging when running rsync and remote execution
        :param mirror: mirror local files remotely. It will remove ALL the remote files in the directory
                       that weren't synced from local workspace
        :param ports: A tuple of remote port,local port to enable local port forwarding
        :returns: an exit code of a remote process
        """

        self.push(dry_run=dry_run, verbose=verbose, mirror=mirror)
        exit_code = self.execute(command, simple=simple, dry_run=dry_run, raise_on_error=False, ports=ports)
        if exit_code != 0:
            logger.info(f"Remote command exited with {exit_code}")
        self.pull(dry_run=dry_run, verbose=verbose)
        return exit_code

    def execute(
        self,
        command: Union[str, List[str]],
        simple: bool = False,
        dry_run: bool = False,
        raise_on_error: bool = True,
        ports: Optional[Tuple[int, int]] = None,
    ) -> int:
        """Execute a command remotely using ssh

        :param command: a command to be executed or its parts
        :param simple: True if command don't need to be preformatted and wrapped before execution
                       commands with simple will be executed from user's remote home directory
        :param dry_run: log the command to be executed but don't run it.
        :param raise_on_error: raise exception if error code was other than 0.
        :param ports: A tuple of remote port, local port to enable local port forwarding

        :returns: an exit code of a remote process
        """
        formatted_command = prepare_shell_command(command)
        if not simple:
            formatted_command = self._generate_command(formatted_command)

        port_forwarding = ForwardingOptions(remote_port=ports[0], local_port=ports[1]) if ports else None
        ssh = self.get_ssh(port_forwarding)
        return ssh.execute(formatted_command, dry_run, raise_on_error)

    def push(self, info: bool = False, verbose: bool = False, dry_run: bool = False, mirror: bool = False) -> None:
        """Push local workspace files to remote directory

        :param info: use info logging when running rsync
        :param verbose: use verbose logging when running rsync
        :param dry_run: use dry_run parameter when running rsync
        :param mirror: mirror local files remotely. It will remove ALL the remote files in the directory
                       that weren't synced from local workspace
        """
        src = f"{self.local_root}/"
        dst = f"{self.remote.host}:{self.remote.directory}"
        ignores = self.ignores.compile_push()
        includes = self.includes.compile_push()
        # If remote directory structure is deep and it was deleted, we need an rsync-path to recreate it before copying
        extra_args = ["--rsync-path", f"mkdir -p {self.remote.directory} && rsync"]
        rsync(
            src,
            dst,
            self.get_ssh_for_rsync(),
            info=info,
            verbose=verbose,
            dry_run=dry_run,
            delete=True,  # We want to delete the remote file if it's local copy was removed
            mirror=mirror,
            includes=includes,
            excludes=ignores,
            extra_args=extra_args,
        )

    def pull(self, info: bool = False, verbose: bool = False, dry_run: bool = False, subpath: Path = None) -> None:
        """Pull remote files to local workspace

        :param info: use info logging when running rsync
        :param verbose: use verbose logging when running rsync
        :param dry_run: use dry_run parameter when running rsync
        :param subpath: a specific path to bring in. If provided, subpath will be synced
                        even if it is ignored by workspace rules
        """
        if subpath is not None:
            src = f"{self.remote.host}:{self.remote.directory}/{subpath}"
            dst_path = self.local_root / subpath.parent
            dst_path.mkdir(parents=True, exist_ok=True)
            dst = f"{dst_path}/"

            rsync(src, dst, self.get_ssh_for_rsync(), info=info, verbose=verbose, dry_run=dry_run)
            return

        src = f"{self.remote.host}:{self.remote.directory}/"
        dst = str(self.local_root)
        ignores = self.ignores.compile_pull()
        includes = self.includes.compile_pull()
        rsync(
            src,
            dst,
            self.get_ssh_for_rsync(),
            info=info,
            verbose=verbose,
            includes=includes,
            dry_run=dry_run,
            excludes=ignores,
        )

    def clear_remote(self) -> None:
        """Remove remote directory"""
        self.execute(f"rm -rf {self.remote.directory}", simple=True)

    def create_remote(self) -> None:
        """Remove remote directory"""
        self.execute(f"mkdir -p {self.remote.directory}", simple=True)
