import contextlib
import logging
import shlex

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional, Union

from .configuration import RemoteConfig, SyncRules, WorkspaceConfig
from .configuration.discovery import load_cwd_workspace_config
from .exceptions import InvalidRemoteHostLabel
from .file_changes import execute_on_file_change
from .util import CommunicationOptions, ForwardingOption, Ssh, VerbosityLevel, prepare_shell_command, rsync

logger = logging.getLogger(__name__)


@dataclass
class CompiledSyncRules:
    excludes: List[str]
    includes: List[str]

    @classmethod
    def push(cls, excludes: SyncRules, includes: SyncRules):
        return cls(excludes=excludes.compile_push(), includes=includes.compile_push())

    @classmethod
    def pull(cls, excludes: SyncRules, includes: SyncRules):
        return cls(excludes=excludes.compile_pull(), includes=includes.compile_pull())


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
    push_rules: CompiledSyncRules
    # sync include file patterns
    pull_rules: CompiledSyncRules
    # process communication options
    communication: CommunicationOptions = CommunicationOptions()

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

        push_rules = CompiledSyncRules.push(config.ignores, config.includes)
        push_rules.includes.append("/.remoteenv")
        return cls(
            local_root=config.root,
            remote=remote_config,
            remote_working_dir=remote_working_dir,
            push_rules=push_rules,
            pull_rules=CompiledSyncRules.pull(config.ignores, config.includes),
        )

    @classmethod
    def from_cwd(cls, remote_host_id: Optional[Union[str, int]] = None) -> "SyncedWorkspace":
        """Load a workspace from current working directory of user"""
        config = load_cwd_workspace_config()
        return cls.from_config(config, Path.cwd(), remote_host_id)

    @classmethod
    def from_cwd_mass(cls) -> List["SyncedWorkspace"]:
        """Load all possible workspaces from current working directory of user"""
        config = load_cwd_workspace_config()

        workspaces = []
        for i in range(len(config.configurations)):
            workspaces.append(cls.from_config(config, Path.cwd(), i))

        return workspaces

    def get_ssh(self, port_forwarding: List[ForwardingOption] = [], verbose: bool = False):
        return Ssh(
            self.remote.host,
            port=self.remote.port,
            use_gssapi_auth=self.remote.supports_gssapi,
            local_port_forwarding=list(port_forwarding),
            verbosity_level=VerbosityLevel.VERBOSE if verbose else VerbosityLevel.QUIET,
            communication=self.communication,
        )

    def get_ssh_for_rsync(self):
        ssh = self.get_ssh()
        return replace(ssh, force_tty=False)

    def _generate_command(self, command: str, env: Dict[str, str]) -> str:
        relative_path = self.remote_working_dir.relative_to(self.remote.directory)
        env_variables = "\n".join([f"export {shlex.quote(k)}={shlex.quote(env[k])}" for k in sorted(env.keys())])
        if env_variables:
            env_variables += "\n"

        return f"""\
cd {self.remote.directory}
if [ -f .remoteenv ]; then
  source .remoteenv
fi
cd {relative_path}
{env_variables}{command}
"""

    def execute_in_synced_env(
        self,
        command: Union[str, List[str]],
        simple: bool = False,
        verbose: bool = False,
        dry_run: bool = False,
        mirror: bool = False,
        ports: List[ForwardingOption] = [],
        stream_changes: bool = False,
        env: Optional[Dict[str, str]] = None,
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
        :param ports: Settings describing local port forwarding
        :param stream_changes: Resync local changes if any while the command is being run remotely
        :param env: shell environment variables to set remotely before executing the command. This will be
                    ignored if simple is True

        :returns: an exit code of a remote process
        """

        self.push(dry_run=dry_run, verbose=verbose, mirror=mirror)
        exit_code = self.execute(
            command, simple=simple, dry_run=dry_run, raise_on_error=False, ports=ports, stream_changes=stream_changes
        )
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
        verbose: bool = False,
        ports: List[ForwardingOption] = [],
        stream_changes: bool = False,
        env: Optional[Dict[str, str]] = None,
    ) -> int:
        """Execute a command remotely using ssh

        :param command: a command to be executed or its parts
        :param simple: True if command don't need to be preformatted and wrapped before execution
                       commands with simple will be executed from user's remote home directory
        :param dry_run: log the command to be executed but don't run it.
        :param raise_on_error: raise exception if error code was other than 0.
        :param ports: Settings describing local port forwarding
        :param stream_changes: Resync local changes if any while the command is being run remotely
        :param verbose: use verbose logging when running ssh
        :param env: shell environment variables to set remotely before executing the command. This will be
                    ignored if simple is True

        :returns: an exit code of a remote process
        """
        formatted_command = prepare_shell_command(command)
        if dry_run:
            formatted_command = f"echo {formatted_command}"
        elif not simple:
            formatted_command = self._generate_command(formatted_command, env or {})

        ssh = self.get_ssh(ports, verbose)

        with execute_on_file_change(
            local_root=self.local_root, callback=self.push, settle_time=1
        ) if stream_changes else contextlib.suppress():
            return ssh.execute(formatted_command, raise_on_error)

    def push(
        self,
        info: bool = False,
        verbose: bool = False,
        dry_run: bool = False,
        mirror: bool = False,
        subpath: Union[Path, str] = None,
    ) -> None:
        """Push local workspace files to remote directory

        :param info: use info logging when running rsync
        :param verbose: use verbose logging when running rsync
        :param dry_run: use dry_run parameter when running rsync
        :param mirror: mirror local files remotely. It will remove ALL the remote files in the directory
                       that weren't synced from local workspace
        """
        if subpath is not None:
            src = str(self.local_root / self.remote_working_dir.relative_to(self.remote.directory) / subpath)
            dst_path = self.remote_working_dir / subpath
            dst = f"{self.remote.host}:{dst_path.parent}/"

            rsync(src, dst, self.get_ssh_for_rsync(), info=info, verbose=verbose, dry_run=dry_run, delete=True)
            return

        src = f"{self.local_root}/"
        dst = f"{self.remote.host}:{self.remote.directory}"
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
            includes=self.push_rules.includes,
            excludes=self.push_rules.excludes,
            extra_args=extra_args,
            communication=self.communication,
        )

    def pull(
        self, info: bool = False, verbose: bool = False, dry_run: bool = False, subpath: Union[Path, str] = None
    ) -> None:
        """Pull remote files to local workspace

        :param info: use info logging when running rsync
        :param verbose: use verbose logging when running rsync
        :param dry_run: use dry_run parameter when running rsync
        :param subpath: a specific path to bring in. If provided, subpath will be synced
                        even if it is ignored by workspace rules
        """
        if subpath is not None:
            src = f"{self.remote.host}:{self.remote_working_dir}/{subpath}"
            local_subpath = self.remote_working_dir.relative_to(self.remote.directory) / subpath
            dst_path = self.local_root / local_subpath.parent
            dst_path.mkdir(parents=True, exist_ok=True)
            dst = f"{dst_path}/"

            rsync(
                src,
                dst,
                self.get_ssh_for_rsync(),
                info=info,
                verbose=verbose,
                dry_run=dry_run,
                communication=self.communication,
            )
            return

        src = f"{self.remote.host}:{self.remote.directory}/"
        dst = str(self.local_root)
        rsync(
            src,
            dst,
            self.get_ssh_for_rsync(),
            info=info,
            verbose=verbose,
            includes=self.pull_rules.includes,
            dry_run=dry_run,
            excludes=self.pull_rules.excludes,
            communication=self.communication,
        )

    def clear_remote(self) -> None:
        """Remove remote directory"""
        self.execute(f"rm -rf {self.remote.directory}", simple=True)

    def create_remote(self) -> None:
        """Remove remote directory"""
        self.execute(f"mkdir -p {self.remote.directory}", simple=True)
