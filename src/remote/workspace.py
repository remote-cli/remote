import logging

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

from .configuration import RemoteConfig, SyncIgnores, WorkspaceConfig
from .configuration.discovery import load_cwd_workspace_config
from .util import prepare_shell_command, rsync, ssh

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
    ignores: SyncIgnores

    @classmethod
    def from_config(
        cls, config: WorkspaceConfig, working_dir: Path, config_num: Optional[int] = None
    ) -> "SyncedWorkspace":
        """Create a workspace from configuration object

        :param config: workspace config
        :param working_dir: a working directory inside the workspace config
        :param config_num: if present, overrides the default remote host to use
        """
        working_dir = working_dir.relative_to(config.root)
        if config_num is None:
            config_num = config.default_configuration
        remote_config = config.configurations[config_num]
        remote_working_dir = remote_config.directory / working_dir

        return cls(
            local_root=config.root, remote=remote_config, remote_working_dir=remote_working_dir, ignores=config.ignores,
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

    def _generate_command(self, command: str) -> str:
        return f"""\
if [ -f {self.remote.directory}/.remoteenv ]; then
  source {self.remote.directory}/.remoteenv 2>/dev/null 1>/dev/null
fi
cd {self.remote_working_dir}
{command}
"""

    def execute_in_synced_env(
        self, command: Union[str, List[str]], simple=False, verbose=False, dry_run=False, mirror=False
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

        :returns: an exit code of a remote process
        """

        self.push(dry_run=dry_run, verbose=verbose, mirror=mirror)
        exit_code = self.execute(command, simple=simple, dry_run=dry_run, raise_on_error=False)
        if exit_code != 0:
            logger.info(f"Remote command exited with {exit_code}")
        self.pull(dry_run=dry_run, verbose=verbose)
        return exit_code

    def execute(self, command: Union[str, List[str]], simple=False, dry_run=False, raise_on_error=True) -> int:
        """Execute a command remotely using ssh

        :param command: a command to be executed or its parts
        :param simple: True if command don't need to be preformatted and wrapped before execution.
                       commands with simple will be executed from user's remote home directory
        :param dry_run: log the command to be executed but don't run it
        :param raise_on_error: raise exception if error code was other than 0

        :returns: an exit code of a remote process
        """
        formatted_command = prepare_shell_command(command)
        if not simple:
            formatted_command = self._generate_command(formatted_command)

        return ssh(self.remote.host, formatted_command, dry_run=dry_run, raise_on_error=raise_on_error)

    def push(self, info=False, verbose=False, dry_run=False, mirror=False):
        """Push local workspace files to remote directory

        :param info: use info logging when running rsync
        :param verbose: use verbose logging when running rsync
        :param dry_run: use dry_run parameter when running rsync
        :param mirror: mirror local files remotely. It will remove ALL the remote files in the directory
                       that weren't synced from local workspace
        """
        src = f"{self.local_root}/"
        dst = f"{self.remote.host}:{self.remote.directory}"
        ignores = self.ignores.compile_push_ignores()
        rsync(src, dst, info=info, verbose=verbose, dry_run=dry_run, mirror=mirror, excludes=ignores)

    def pull(self, info=False, verbose=False, dry_run=False, subpath=None):
        """Pull remote files to local workspace

        :param info: use info logging when running rsync
        :param verbose: use verbose logging when running rsync
        :param dry_run: use dry_run parameter when running rsync
        :param subpath: a specific path to bring in. If provided, subpath will be synced
                        even if it is ignored by workspace rules
        """
        if subpath is not None:
            src = f"{self.remote.host}:{self.remote.directory}/{subpath}"
            dst = str(self.local_root / subpath)
            rsync(src, dst, info=info, verbose=verbose, dry_run=dry_run)
            return

        src = f"{self.remote.host}:{self.remote.directory}/"
        dst = str(self.local_root)
        ignores = self.ignores.compile_pull_ignores()
        rsync(src, dst, info=info, verbose=verbose, dry_run=dry_run, excludes=ignores)

    def clear_remote(self):
        """Remove remote directory"""
        self.execute(f"rm -rf {self.remote.directory}", simple=True)
