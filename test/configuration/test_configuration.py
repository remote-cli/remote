from pathlib import Path

from remote.configuration import RemoteConfig, SyncRules, WorkspaceConfig


def test_empty_ignore():
    # new ignores object is created empty
    ignores = SyncRules.new()
    assert not ignores.pull
    assert not ignores.push
    assert not ignores.both
    assert ignores.is_empty()
    assert not ignores.compile_push()
    assert not ignores.compile_pull()

    # if we add something it is not empty anymore
    ignores.pull.append("my_pattern")
    assert not ignores.is_empty()


def test_ignores_compilation():
    # Each collection should extend from both when compiling
    ignores = SyncRules(push=["push_1", "push_2"], pull=["pull_1", "both_1"], both=["both_1", "both_2"])
    assert ignores.compile_pull() == ["both_1", "both_2", "pull_1"]
    assert ignores.compile_push() == ["both_1", "both_2", "push_1", "push_2"]


def test_check_adding_patter_extends_both():
    ignores = SyncRules(push=["push_1", "push_2"], pull=["pull_1", "both_1"], both=["both_1", "both_3"])
    ignores.add(["both_2"])
    assert ignores.pull == ["both_1", "pull_1"]
    assert ignores.push == ["push_1", "push_2"]
    assert ignores.both == ["both_1", "both_2", "both_3"]


def test_add_host_to_workspace(tmp_path):
    config = WorkspaceConfig.empty(tmp_path)
    added, index = config.add_remote_host("test-host", Path("remote/dir"))
    assert added
    assert index == 0
    assert config.default_configuration == 0
    assert len(config.configurations) == 1
    assert config.configurations[0] == RemoteConfig(
        host="test-host", directory=Path("remote/dir"), shell="sh", shell_options=""
    )
