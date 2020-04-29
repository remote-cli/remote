from pathlib import Path

from . import WorkspaceConfig
from .classic import load_workspace_config


def load_cwd_workspace_config() -> WorkspaceConfig:
    """Determine current working directory's workspace config type and load it

    Supports only classical config layout now, but will be extended once the new type is added
    """
    working_dir = Path.cwd()
    return load_workspace_config(working_dir)
