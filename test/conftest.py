from pathlib import Path

import pytest

from remote.configuration import RemoteConfig, WorkspaceConfig


@pytest.fixture
def workspace_config(tmp_path):
    # a workspace with one remote host and all default values
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config = WorkspaceConfig.empty(workspace_root)
    config.configurations.append(
        RemoteConfig(host="test-host.example.com", directory=Path("remote/dir"), shell="sh", shell_options="")
    )
    return config
