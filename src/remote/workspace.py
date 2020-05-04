import logging
import subprocess
import sys
import time

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Union

from .configuration import RemoteConfig, SyncIgnores, WorkspaceConfig
from .configuration.discovery import load_cwd_workspace_config
from .exceptions import RemoteConnectionError, RemoteExecutionError
from .util import rsync

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

    @staticmethod
    def _prepare_command(command: Sequence[str]) -> str:
        # This means the whole command is already preformatted for us
        if len(command) == 1 and " " in command[0]:
            return command[0]

        result = []
        for item in command:
            if not item:
                continue
            if " " in item:
                result.append(f"'{item}'")
            else:
                result.append(item)

        return " ".join(result)

    def _generate_command(self, command: str) -> str:
        return f"""\
if [ -f {self.remote.directory}/.remoteenv ]; then
  source {self.remote.directory}/.remoteenv 2>/dev/null 1>/dev/null
fi
cd {self.remote_working_dir}
{command}
"""

    def execute(self, command: Union[str, List[str]], simple=False, dry_run=False, raise_on_error=True) -> int:
        """Execute a command remotely using ssh

        :param command: a command to be executed or its parts
        :param simple: True if command don't need to be preformatted and wrapped before execution.
                       commands with simple will be executed from user's remote home directory
        :param dry_run: log the command to be executed but don't run it
        :param raise_on_error: raise exception if error code was other than 0

        :returns: an exit code of a remote process
        """
        if isinstance(command, list):
            command = self._prepare_command(command)
        if not simple:
            command = self._generate_command(command)

        subprocess_command = ["ssh", "-tKq", self.remote.host, command]
        logger.info("Executing:\n%s %s %s <<EOS\n%sEOS", *subprocess_command)
        if dry_run:
            return 0

        start = time.time()
        result = subprocess.run(subprocess_command, stdout=sys.stdout, stderr=sys.stderr, stdin=sys.stdin)
        runtime = time.time() - start
        logger.info("Execution done in %.2f seconds", runtime)
        if raise_on_error:
            # ssh exits with the exit status of the remote command or with 255 if an error occurred
            if result.returncode == 255:
                raise RemoteConnectionError(f"Failed to connect to {self.remote.host}")
            elif result.returncode != 0:
                raise RemoteExecutionError(
                    f'Failed to execute "{command}" on host {self.remote.host} ({result.returncode})'
                )
        return result.returncode

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
