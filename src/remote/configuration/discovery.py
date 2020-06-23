from pathlib import Path
from typing import List, Tuple

from remote.exceptions import ConfigurationError

from . import ConfigurationMedium, WorkspaceConfig
from .classic import ClassicConfigurationMedium
from .toml import TomlConfigurationMedium

CONFIG_MEDIUMS: List[ConfigurationMedium] = [ClassicConfigurationMedium(), TomlConfigurationMedium()]


def resolve_workspace_root(working_dir: Path) -> Tuple[ConfigurationMedium, Path]:
    """Find and return the directory in this tree that has remote-ing set up"""
    possible_directory = working_dir
    root = Path("/")
    while possible_directory != root:
        for meduim in CONFIG_MEDIUMS:
            if meduim.is_workspace_root(possible_directory):
                return meduim, possible_directory
        possible_directory = possible_directory.parent

    raise ConfigurationError(f"Cannot resolve the remote workspace in {working_dir}")


def load_cwd_workspace_config() -> WorkspaceConfig:
    """Determine current working directory's workspace config type and load it

    Supports only classical config layout now, but will be extended once the new type is added
    """
    working_dir = Path.cwd()
    medium, root = resolve_workspace_root(working_dir)
    return medium.load_config(root)


def get_configuration_medium(config: WorkspaceConfig) -> ConfigurationMedium:
    """We have only one medium for now"""
    for medium in CONFIG_MEDIUMS:
        if medium.is_workspace_root(config.root):
            return medium

    # If there is no medium found, the config is newly created, so we return a default one
    return TomlConfigurationMedium()


def save_config(config: WorkspaceConfig):
    """Save config using the proper medium"""
    config_medium = get_configuration_medium(config)
    config_medium.save_config(config)
