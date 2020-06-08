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
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Tuple

from remote.exceptions import ConfigurationError

from . import ConfigurationMedium, RemoteConfig, SyncRules, WorkspaceConfig
from .shared import DEFAULT_REMOTE_ROOT, hash_path

CONFIG_FILE_NAME = ".remote"
INDEX_FILE_NAME = ".remoteindex"
IGNORE_FILE_NAME = ".remoteignore"
IGNORE_SECTION_REGEX = re.compile(r"^(push|pull|both)\s*:$")
BASE_IGNORES = (CONFIG_FILE_NAME, INDEX_FILE_NAME, IGNORE_FILE_NAME)
DEFAULT_SHELL = "sh"
DEFAULT_SHELL_OPTIONS = ""


def _extract_shell_info(line: str, env_vars: List[str]) -> Tuple[str, str]:
    if not env_vars:
        return DEFAULT_SHELL, DEFAULT_SHELL_OPTIONS

    vars_string = env_vars[0]

    env = {}
    items = vars_string.split()
    index = 0
    while index < len(items):
        key, value = items[index].split("=")
        if value.startswith("'") or value.startswith('"'):
            control_character = value[0]
            while index < len(items) - 1:
                if value[-1] == control_character:
                    break
                index += 1
                value += " " + items[index]
            if not value[-1] == control_character:
                raise ConfigurationError(f"Config line {line} is corrupted. Cannot parse end {key}={value}")

        env[key] = value.strip("\"'")

        index += 1
    print(env)
    # TODO: these shell types are not used in new implementation, need to remove them
    shell = env.pop("RSHELL", DEFAULT_SHELL)
    shell_options = env.pop("RSHELL_OPTS", DEFAULT_SHELL_OPTIONS)
    if env:
        raise ConfigurationError(
            f"Config line {line} contains unexpected env variables: {env}. Only RSHELL and RSHELL_OPTS can be used"
        )
    return shell, shell_options


def parse_config_line(line: str) -> RemoteConfig:
    # The line should look like this:
    # sdas-ld2:.remotes/814f27f15f4e7a0842cada353dfc765a RSHELL=zsh
    entry, *env_items = line.split(maxsplit=1)
    shell, shell_options = _extract_shell_info(line, env_items)

    parts = entry.split(":")
    if len(parts) != 2:
        raise ConfigurationError(
            f"The configuration string is malformed: {parts}. Please use host-name:remote_dir format"
        )
    host, directory = parts
    return RemoteConfig(host=host, directory=Path(directory), shell=shell, shell_options=shell_options)


def load_configurations(workspace_root: Path) -> List[RemoteConfig]:
    config_file = workspace_root / CONFIG_FILE_NAME

    configurations = []
    for line in config_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        configurations.append(parse_config_line(line))

    return configurations


def load_default_configuration_num(workspace_root: Path) -> int:
    # If REMOTE_HOST_INDEX is set, that overrides settings in .remoteindex
    env_index = os.environ.get("REMOTE_HOST_INDEX")
    if env_index:
        try:
            return int(env_index)
        except ValueError:
            raise ConfigurationError(
                f"REMOTE_HOST_INDEX env variable contains symbols other than numbers: '{env_index}'. "
                "Please set the coorect index value to continue"
            )

    index_file = workspace_root / INDEX_FILE_NAME
    if not index_file.exists():
        return 0

    # Configuration uses 1-base index and we need to have 0-based
    text = index_file.read_text().strip()
    try:
        return int(text) - 1
    except ValueError:
        raise ConfigurationError(
            f"File {index_file} contains symbols other than numbers: '{text}'. "
            "Please remove it or replace the value to continue"
        )


def _postprocess(ignores):
    pull = ignores.pop("pull", [])
    push = ignores.pop("push", [])
    both = ignores.pop("both", [])
    if ignores:
        raise ConfigurationError(
            f"{IGNORE_FILE_NAME} file has unexpected sections: {', '.join(ignores.keys())}. Please remove them"
        )
    return SyncRules(pull=pull, push=push, both=both)


def load_ignores(workspace_root: Path) -> SyncRules:
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
                    "Please list all ignored files after a section declaration if you use new ignore format"
                )
            active_section = matcher.group(1)

    return _postprocess(ignores)


def save_general_config(config_file: Path, configurations: List[RemoteConfig]):
    with config_file.open("w") as f:
        for item in configurations:
            f.write(f"{item.host}:{item.directory}")
            if item.shell != "sh":
                f.write(f" RSHELL={item.shell}")
            if item.shell_options:
                f.write(f" RSHELL_OPTS='{item.shell_options}'")
            f.write("\n")


def save_ignores(config_file: Path, ignores: SyncRules):
    ignores.both.extend(BASE_IGNORES)
    ignores.trim()

    if ignores.is_empty():
        if config_file.exists():
            config_file.unlink()
        return

    with config_file.open("w") as f:
        for key, value in asdict(ignores).items():
            f.write(f"{key}:\n")
            for item in value:
                f.write(f"{item}\n")


def save_index(config_file: Path, index: int):
    if index == 0:
        # We delete file when index is default
        if config_file.exists():
            config_file.unlink()
    else:
        config_file.write_text(f"{index + 1}\n")


class ClassicConfigurationMedium(ConfigurationMedium):
    """A medium class that knows how to load and save the 'classical' workspace configuration.

    This configuration may have three meaningful files:
    .remote (required) - information about the connection options
    .remoteindex (optional) - information about which connection from options above to use
    .remoteignore (optional) - information about files that should be ignore when syncing files
    """

    def load_config(self, workspace_root: Path) -> WorkspaceConfig:
        configurations = load_configurations(workspace_root)
        configuration_index = load_default_configuration_num(workspace_root)
        if configuration_index > len(configurations) - 1:
            raise ConfigurationError(
                f"Configuration #{configuration_index + 1} requested but there are only {len(configurations)} declared"
            )
        ignores = load_ignores(workspace_root)

        return WorkspaceConfig(
            root=workspace_root,
            configurations=configurations,
            default_configuration=configuration_index,
            ignores=ignores,
            includes=SyncRules.new(),
        )

    def save_config(self, config: WorkspaceConfig) -> None:
        save_general_config(config.root / CONFIG_FILE_NAME, config.configurations)
        save_ignores(config.root / IGNORE_FILE_NAME, config.ignores)
        save_index(config.root / INDEX_FILE_NAME, config.default_configuration)

    def is_workspace_root(self, path: Path) -> bool:
        return (path / CONFIG_FILE_NAME).exists()

    def generate_remote_directory(self, config: WorkspaceConfig) -> Path:
        md5 = hash_path(config.root)
        return Path(f"{DEFAULT_REMOTE_ROOT}/{config.root.name}_{md5}")
