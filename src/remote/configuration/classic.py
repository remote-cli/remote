"""
A module that contains utility functions to load the 'classical' workspace configuration.
This configuration may have three meaningful files:
.remote (required) - information about the connection options
.remoteindex (optional) - information about which connection from options above to use
.remoteignore (optional) - information about files that should be ignore when syncing files
"""
import os
import re

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from remote.exceptions import ConfigurationError

from . import RemoteConfig, SyncIgnores, WorkspaceConfig

CONFIG_FILE_NAME = ".remote"
INDEX_FILE_NAME = ".remoteindex"
IGNORE_FILE_NAME = ".remoteignore"
IGNORE_SECTION_REGEX = re.compile(r"^(push|pull|both)\s*:$")
BASE_IGNORES = (CONFIG_FILE_NAME, INDEX_FILE_NAME, IGNORE_FILE_NAME)


def _resolve_workspace_root(working_dir: Path) -> Optional[Path]:
    """Find and return the directory in this tree that has remote-ing set up"""
    possible_directory = working_dir
    root = Path("/")
    while not possible_directory == root:
        cfg_file = possible_directory / CONFIG_FILE_NAME
        if cfg_file.is_file():
            return possible_directory
        possible_directory = possible_directory.parent

    return None


def _load_configurations(workspace_root: Path) -> List[RemoteConfig]:
    config_file = workspace_root / CONFIG_FILE_NAME

    configurations = []
    for line in config_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue

        # The line should look like this:
        # sdas-ld2:.remotes/814f27f15f4e7a0842cada353dfc765a RSHELL=zsh
        entry, *env_items = line.split()
        env: Dict[str, str] = dict((item.split("=") for item in env_items))  # type: ignore
        # TODO: these shell types are not used in new implementation, need to remove them
        shell = env.pop("RSHELL", "sh")
        shell_options = env.pop("RSHELL_OPTS", "")
        if env:
            raise ConfigurationError(
                f"Config line {line} contains unexpected env variables: {env}. Only RSHELL and RSHELL_OPTS can be used"
            )
        host, directory = entry.split(":")
        rc = RemoteConfig(host=host, directory=Path(directory), shell=shell, shell_options=shell_options)
        configurations.append(rc)

    return configurations


def _load_default_configuration_num(workspace_root: Path) -> int:
    # If REMOTE_HOST_INDEX is set, that overrides settings in .remoteindex
    env_index = os.environ.get("REMOTE_HOST_INDEX")
    if env_index:
        return int(env_index)

    index_file = workspace_root / INDEX_FILE_NAME
    if not index_file.exists():
        return 0
    # Configuration uses 1-base index and we need to have 0-based
    return int(index_file.read_text().strip()) - 1


def _postprocess(ignores):
    pull = ignores.pop("pull", [])
    push = ignores.pop("push", [])
    both = ignores.pop("both", [])
    if ignores:
        raise ConfigurationError(
            f"{IGNORE_FILE_NAME} file has unexpected sections: {', '.join(ignores.keys())}. Please remove them"
        )
    return SyncIgnores(pull=pull, push=push, both=both)


def _load_ignores(workspace_root: Path) -> SyncIgnores:
    ignores: Dict[str, List[str]] = defaultdict(list)
    ignores["both"].extend(BASE_IGNORES)

    ignore_file = workspace_root / IGNORE_FILE_NAME
    if not ignore_file.exists():
        return _postprocess(ignores)

    active_section = "both"
    is_new_format = None
    for line in ignore_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        matcher = IGNORE_SECTION_REGEX.match(line)
        if matcher is None:
            if is_new_format is None:
                is_new_format = False
            ignores[active_section].append(line)
        else:
            if is_new_format is None:
                is_new_format = True
            elif not is_new_format:
                raise ConfigurationError(
                    f"Few ignore patters were listed in {IGNORE_FILE_NAME} before the first section {matcher.group(1)} appeared. "
                    "Please list all ignored files after a section declaraion if you use new ignore format"
                )
            active_section = matcher.group(1)

    return _postprocess(ignores)


def load_workspace_config(working_dir: Path) -> WorkspaceConfig:
    """Load the classic workspace config for the provided working directory"""
    workspace_root = _resolve_workspace_root(working_dir)
    if workspace_root is None:
        raise ConfigurationError(f"Cannot resolve the remote workspace in {working_dir}")
    configurations = _load_configurations(workspace_root)
    configuration_index = _load_default_configuration_num(workspace_root)
    if configuration_index > len(configurations) - 1:
        raise ConfigurationError(
            f"Configuration #{configuration_index + 1} requested but there are only {len(configurations)} declared"
        )
    ignores = _load_ignores(workspace_root)

    return WorkspaceConfig(
        root=workspace_root, configurations=configurations, default_configuration=configuration_index, ignores=ignores,
    )


def save_general_config(config_file: Path, configurations: List[RemoteConfig]):
    with config_file.open("w") as f:
        for item in configurations:
            f.write(f"{item.host}:{item.directory}")
            if item.shell != "sh":
                f.write(f" RSHELL={item.shell}")
            if item.shell_options:
                f.write(f" RSHELL_OPTS={item.shell_options}")
            f.write("\n")


def save_ignores(config_file: Path, ignores: SyncIgnores):
    ignores.both.extend(BASE_IGNORES)

    if ignores.is_empty():
        if config_file.exists():
            config_file.unlink()
        return

    with config_file.open("w") as f:
        for name in ("both", "push", "pull"):
            f.write(f"{name}:\n")
            for item in sorted(set(getattr(ignores, name))):
                f.write(f"{item}\n")


def save_index(config_file: Path, index: int):
    if index == 0:
        # We delete file when index is default
        if config_file.exists():
            config_file.unlink()
    else:
        config_file.write_text(f"{index + 1}\n")


def save_config(config: WorkspaceConfig):
    """Save the classic workspace config into workspace's root.
    This method might delete config files if they contain only default values
    """
    save_general_config(config.root / CONFIG_FILE_NAME, config.configurations)
    save_ignores(config.root / IGNORE_FILE_NAME, config.ignores)
    save_index(config.root / INDEX_FILE_NAME, config.default_configuration)
