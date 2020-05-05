import pytest

from remote.configuration.classic import CONFIG_FILE_NAME, ClassicConfigurationMedium
from remote.configuration.discovery import get_configuration_medium, resolve_workspace_root


def test_resolve_workspace_root(tmp_path):
    work_dir = tmp_path / "foo" / "bar"
    work_dir.mkdir(parents=True)
    (tmp_path / CONFIG_FILE_NAME).write_text("my-host:some/dir")

    (medium, root) = resolve_workspace_root(work_dir)
    assert root == tmp_path
    assert isinstance(medium, ClassicConfigurationMedium)


@pytest.mark.parametrize("medium_class", [ClassicConfigurationMedium])
def test_get_configuration_medium(medium_class, workspace_config):
    medium_class().save_config(workspace_config)

    medium = get_configuration_medium(workspace_config)
    assert isinstance(medium, medium_class)
