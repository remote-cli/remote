from pathlib import Path

import pytest

from remote.configuration import RemoteConfig, SyncRules
from remote.configuration.classic import (
    CONFIG_FILE_NAME,
    IGNORE_FILE_NAME,
    INDEX_FILE_NAME,
    ClassicConfigurationMedium,
    parse_config_line,
)
from remote.exceptions import ConfigurationError


@pytest.mark.parametrize(
    "input_line, expected",
    [
        (
            "test-host.example.com:remote/dir",
            RemoteConfig(host="test-host.example.com", directory=Path("remote/dir"), shell="sh", shell_options=""),
        ),
        (
            "test-host.example.com:remote/dir RSHELL=bash",
            RemoteConfig(host="test-host.example.com", directory=Path("remote/dir"), shell="bash", shell_options=""),
        ),
        (
            "test-host.example.com:remote/dir RSHELL='bash'",
            RemoteConfig(host="test-host.example.com", directory=Path("remote/dir"), shell="bash", shell_options=""),
        ),
        (
            'test-host.example.com:remote/dir RSHELL="zsh"',
            RemoteConfig(host="test-host.example.com", directory=Path("remote/dir"), shell="zsh", shell_options=""),
        ),
        (
            'test-host.example.com:remote/dir RSHELL="zsh" RSHELL_OPTS=options',
            RemoteConfig(
                host="test-host.example.com", directory=Path("remote/dir"), shell="zsh", shell_options="options"
            ),
        ),
        (
            "test-host.example.com:remote/dir RSHELL=zsh RSHELL_OPTS='some other options'",
            RemoteConfig(
                host="test-host.example.com",
                directory=Path("remote/dir"),
                shell="zsh",
                shell_options="some other options",
            ),
        ),
    ],
)
def test_parse_config_line(input_line, expected):
    result = parse_config_line(input_line)
    assert result == expected


def test_parse_config_line_error():
    # line is corrupted, don't have closing " after zsh
    line = 'test-host.example.com:remote/dir RSHELL="zsh RSHELL_OPTS=options'
    with pytest.raises(ConfigurationError) as e:
        parse_config_line(line)

    assert f"Config line {line} is corrupted" in str(e.value)


def test_medium_is_workspace_root(tmp_path):
    medium = ClassicConfigurationMedium()
    assert not medium.is_workspace_root(tmp_path)
    (tmp_path / CONFIG_FILE_NAME).write_text("my-host:some/dir")

    assert medium.is_workspace_root(tmp_path)


def test_medium_generate_remote_directory(workspace_config):
    medium = ClassicConfigurationMedium()
    path = medium.generate_remote_directory(workspace_config)
    assert str(path).startswith(f".remotes/{workspace_config.root.name}_")


def test_medium_save_config_default(workspace_config):
    medium = ClassicConfigurationMedium()
    medium.save_config(workspace_config)

    root = workspace_config.root
    # it's default config so it should only create a .remote file and .remoteignore
    assert (root / CONFIG_FILE_NAME).exists()
    assert (root / CONFIG_FILE_NAME).read_text() == "test-host.example.com:remote/dir\n"
    assert not (root / INDEX_FILE_NAME).exists()
    assert (root / IGNORE_FILE_NAME).exists()
    assert (
        root / IGNORE_FILE_NAME
    ).read_text() == f"pull:\npush:\nboth:\n{CONFIG_FILE_NAME}\n{IGNORE_FILE_NAME}\n{INDEX_FILE_NAME}\n"


def test_medium_save_config_removes_index_if_default(workspace_config):
    root = workspace_config.root
    (root / IGNORE_FILE_NAME).write_text("1")

    medium = ClassicConfigurationMedium()
    medium.save_config(workspace_config)

    # it's default config so it should only create a .remote file and .remoteignore
    assert (root / CONFIG_FILE_NAME).exists()
    assert (root / CONFIG_FILE_NAME).read_text() == "test-host.example.com:remote/dir\n"
    assert not (root / INDEX_FILE_NAME).exists()
    assert (root / IGNORE_FILE_NAME).exists()
    assert (
        root / IGNORE_FILE_NAME
    ).read_text() == f"pull:\npush:\nboth:\n{CONFIG_FILE_NAME}\n{IGNORE_FILE_NAME}\n{INDEX_FILE_NAME}\n"


def test_medium_save_config_with_host_and_index(workspace_config):
    workspace_config.configurations.append(
        RemoteConfig(
            host="other-host.example.com", directory=Path("other/dir"), shell="bash", shell_options="some options"
        )
    )
    workspace_config.default_configuration = 1

    medium = ClassicConfigurationMedium()
    medium.save_config(workspace_config)

    root = workspace_config.root
    assert (root / CONFIG_FILE_NAME).exists()
    assert (
        (root / CONFIG_FILE_NAME).read_text()
        == """\
test-host.example.com:remote/dir
other-host.example.com:other/dir RSHELL=bash RSHELL_OPTS='some options'
"""
    )
    assert (root / INDEX_FILE_NAME).exists()
    assert (root / INDEX_FILE_NAME).read_text() == "2\n"
    assert (root / IGNORE_FILE_NAME).exists()
    assert (
        root / IGNORE_FILE_NAME
    ).read_text() == f"pull:\npush:\nboth:\n{CONFIG_FILE_NAME}\n{IGNORE_FILE_NAME}\n{INDEX_FILE_NAME}\n"


def test_medium_save_config_with_more_ignores(workspace_config):
    workspace_config.ignores.pull.extend(["src/generated"])
    workspace_config.ignores.push.extend([".git", "*.pyc", "__pycache__"])
    workspace_config.ignores.both.extend(["build", IGNORE_FILE_NAME])
    medium = ClassicConfigurationMedium()
    medium.save_config(workspace_config)

    root = workspace_config.root
    assert (root / CONFIG_FILE_NAME).exists()
    assert (root / CONFIG_FILE_NAME).read_text() == "test-host.example.com:remote/dir\n"
    assert not (root / INDEX_FILE_NAME).exists()
    assert (root / IGNORE_FILE_NAME).exists()
    assert (root / IGNORE_FILE_NAME).exists()
    assert (
        (root / IGNORE_FILE_NAME).read_text()
        == f"""\
pull:
src/generated
push:
*.pyc
.git
__pycache__
both:
{CONFIG_FILE_NAME}
{IGNORE_FILE_NAME}
{INDEX_FILE_NAME}
build
"""
    )


def test_medium_load_minimal_config(tmp_path):
    (tmp_path / CONFIG_FILE_NAME).write_text("test-host.example.com:remote/dir")
    medium = ClassicConfigurationMedium()

    config = medium.load_config(tmp_path)
    assert config.root == tmp_path
    assert config.default_configuration == 0
    assert len(config.configurations) == 1
    assert config.configurations[0] == RemoteConfig(
        host="test-host.example.com", directory=Path("remote/dir"), shell="sh", shell_options=""
    )
    # Ignore is always pre-populated even if it's empy in FS
    assert config.ignores == SyncRules(pull=[], push=[], both=[CONFIG_FILE_NAME, IGNORE_FILE_NAME, INDEX_FILE_NAME])


def test_medium_load_old_fashioned_ignore_config(tmp_path):
    (tmp_path / CONFIG_FILE_NAME).write_text("test-host.example.com:remote/dir")
    (tmp_path / IGNORE_FILE_NAME).write_text("build\n.git\n\n*.pyc")
    medium = ClassicConfigurationMedium()

    config = medium.load_config(tmp_path)
    assert config.root == tmp_path
    assert config.default_configuration == 0
    assert len(config.configurations) == 1
    assert config.configurations[0] == RemoteConfig(
        host="test-host.example.com", directory=Path("remote/dir"), shell="sh", shell_options=""
    )
    # Ignore is always pre-populated even if it's empy in FS
    assert config.ignores == SyncRules(
        pull=[], push=[], both=["build", ".git", "*.pyc", CONFIG_FILE_NAME, IGNORE_FILE_NAME, INDEX_FILE_NAME]
    )


def test_medium_load_extensive_config(tmp_path):
    (tmp_path / CONFIG_FILE_NAME).write_text(
        """\
# First host
test-host.example.com:remote/dir

# Second host
other-host.example.com:other/dir RSHELL=bash RSHELL_OPTS=options

# Third host
third-host.example.com:.remote/dir RSHELL=zsh
"""
    )
    (tmp_path / INDEX_FILE_NAME).write_text("3")
    (tmp_path / IGNORE_FILE_NAME).write_text(
        f"""\

push:
.git
*.pyc
__pycache__

pull:
src/generated

both:
build
{CONFIG_FILE_NAME}
{IGNORE_FILE_NAME}
"""
    )
    medium = ClassicConfigurationMedium()

    config = medium.load_config(tmp_path)
    assert config.root == tmp_path
    assert config.default_configuration == 2
    assert len(config.configurations) == 3
    assert config.configurations == [
        RemoteConfig(host="test-host.example.com", directory=Path("remote/dir"), shell="sh", shell_options=""),
        RemoteConfig(host="other-host.example.com", directory=Path("other/dir"), shell="bash", shell_options="options"),
        RemoteConfig(host="third-host.example.com", directory=Path(".remote/dir"), shell="zsh", shell_options=""),
    ]
    assert config.ignores == SyncRules(
        pull=["src/generated"],
        push=[".git", "*.pyc", "__pycache__"],
        both=["build", CONFIG_FILE_NAME, IGNORE_FILE_NAME, INDEX_FILE_NAME],
    )


def test_medium_load_config_connections_configuration_error(tmp_path):
    medium = ClassicConfigurationMedium()

    # Config is malformed
    (tmp_path / CONFIG_FILE_NAME).write_text("some-host")
    with pytest.raises(ConfigurationError) as e:
        medium.load_config(tmp_path)

    assert "The configuration string is malformed" in str(e.value)

    # Some unsupported env variables
    (tmp_path / CONFIG_FILE_NAME).write_text("some-host:some/dir SOME_ENV=123")
    with pytest.raises(ConfigurationError) as e:
        medium.load_config(tmp_path)

    assert "Config line some-host:some/dir SOME_ENV=123 contains unexpected env variables" in str(e.value)


def test_medium_load_config_index_configuration_error(tmp_path, monkeypatch):
    (tmp_path / CONFIG_FILE_NAME).write_text("test-host.example.com:remote/dir")
    medium = ClassicConfigurationMedium()

    # Index is too big
    (tmp_path / INDEX_FILE_NAME).write_text("2")
    with pytest.raises(ConfigurationError) as e:
        medium.load_config(tmp_path)

    assert "Configuration #2 requested but there are only 1 declared" in str(e.value)

    # Index is not a number
    (tmp_path / INDEX_FILE_NAME).write_text("d")
    with pytest.raises(ConfigurationError) as e:
        medium.load_config(tmp_path)

    assert "remoteindex contains symbols other than numbers: 'd'" in str(e.value)

    # Index is not a number in env variable
    monkeypatch.setenv("REMOTE_HOST_INDEX", "a")
    with pytest.raises(ConfigurationError) as e:
        medium.load_config(tmp_path)

    assert "REMOTE_HOST_INDEX env variable contains symbols other than numbers: 'a'" in str(e.value)


def test_medium_load_config_ingore_configuration_error(tmp_path):
    (tmp_path / CONFIG_FILE_NAME).write_text("test-host.example.com:remote/dir")
    (tmp_path / IGNORE_FILE_NAME).write_text("one\ntwo\nthree\nboth:\nbuild")
    medium = ClassicConfigurationMedium()

    with pytest.raises(ConfigurationError) as e:
        medium.load_config(tmp_path)

    assert "Few ignore patters were listed in .remoteignore before the first section both appeared" in str(e.value)
