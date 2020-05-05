from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class RemoteConfig:
    """Single remote connection description"""

    # remote machine's hostname
    host: str
    # relative path to the working directory on remote machine starting from user home dir
    directory: Path
    # a shell to use on remote machine
    shell: str
    # shell options to use on remote machine
    shell_options: str


@dataclass
class SyncIgnores:
    """Patterns used to ignore files when syncing with remote location"""

    # patterns to ignore while pulling from remote
    pull: List[str]
    # patterns to ignore while pushing from local
    push: List[str]
    # patterns to ignore while transferring files in both directions
    both: List[str]

    def __post_init__(self):
        self.trim()

    def compile_push_ignores(self):
        result = set()
        result.update(self.push)
        result.update(self.both)
        return sorted(result)

    def compile_pull_ignores(self):
        result = set()
        result.update(self.pull)
        result.update(self.both)
        return sorted(result)

    def add_ignores(self, ignores: List[str]):
        new_ignores = set()
        new_ignores.update(ignores)
        new_ignores.update(self.both)
        self.both = sorted(new_ignores)

    def trim(self):
        self.pull = sorted(set(self.pull))
        self.push = sorted(set(self.push))
        self.both = sorted(set(self.both))

    def is_empty(self):
        return not (self.pull or self.push or self.both)

    @classmethod
    def new(cls) -> "SyncIgnores":
        return cls([], [], [])


@dataclass
class WorkspaceConfig:
    """Complete remote workspace config"""

    # absolute path to the workspace root
    root: Path
    # remote host connection options that can be used in this workspace
    configurations: List[RemoteConfig]
    # index of default remote host connection
    default_configuration: int
    # patterns to ignore while syncing the workspace
    ignores: SyncIgnores

    @classmethod
    def empty(cls, root: Path) -> "WorkspaceConfig":
        return cls(root=root, configurations=[], default_configuration=0, ignores=SyncIgnores.new())

    def add_remote_host(
        self, host: str, directory: Path, shell: Optional[str] = None, shell_options: Optional[str] = None
    ) -> Tuple[bool, int]:
        remote_config = RemoteConfig(
            host=host, directory=directory, shell=shell or "sh", shell_options=shell_options or "",
        )
        for num, cfg in enumerate(self.configurations):
            if cfg.host == remote_config.host and cfg.directory == remote_config.directory:
                return False, num
        self.configurations.append(remote_config)
        return True, len(self.configurations) - 1


class ConfigurationMedium(metaclass=ABCMeta):
    """A medium class that knows how to load, save, or process a certain type of configuration layout"""

    @abstractmethod
    def load_config(self, workspace_root: Path) -> WorkspaceConfig:
        """Load configuration for the workspace that is located in provided root directory.
        If this method is called, we could assume that check in `is_workspace_root` passed
        """

    @abstractmethod
    def save_config(self, config: WorkspaceConfig):
        """Save configuration to its root"""

    @abstractmethod
    def is_workspace_root(self, path: Path) -> bool:
        """Return true is the path provided contains a configured workspace that can be loaded by this medium"""

    @abstractmethod
    def generate_remote_directory(self, config: WorkspaceConfig) -> Path:
        """Renerate a default remote directory path for the workspace with provided configuration"""
