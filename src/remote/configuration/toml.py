"""
This module contains the medium for toml-based config that consists of global and local parts.

The global config is located in ~/.config/remote/defaults.toml and contains some machine-specific
connection settings that will be used by all workspaces if their own config doesn't overwrite it

    [general]
    no-config-workspaces = true
    remote-root = ".remotes"

    [[hosts]]
    host = "test-host.example.com"
    directory = ".remotes/workspace"
    default = true

    [push]
    # list of exclude patterns in rsync exclude syntax
    # describes the files and directories that we should exclude from pushing to remote host before execution
    exclude = ["env", ".git"]

    [pull]
    # list of exclude patterns in rsync exclude syntax
    # describes the files and directories that we should exclude from
    # pulling to local machine from remote host after execution
    exclude = ["src/generated"]

    [both]
    # list of exclude patterns in rsync exclude syntax
    # describes the files and directories that we should exclude from moving in both directions
    exclude = ["build"]

The workspace config is located in .remote.toml file and contains workspace-specific settings that can overwrite or
extend global ones:

    [[hosts]]
    host = "test-host.example.com"
    directory = ".remotes/workspace"

    [[hosts]]
    host = "other-host.example.com"
    directory = ".remotes/other-workspace"
    default = true

    [push]
    exclude = ["env", ".git"]

    [pull]
    exclude = ["src/generated"]

    [both]
    exclude = ["build"]

Instead of overwriting values, the workspace config can extend some values

    [[extends.hosts]]
    host = "other-host.example.com"
    directory = ".remotes/other-workspace"
    default = true

    [extends.push]
    exclude = ["workspace-specific-dir"]

"""
import re

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import toml

from pydantic import BaseModel, Field, ValidationError, validator

from remote.exceptions import ConfigurationError

from . import ConfigurationMedium, RemoteConfig, SyncIgnores, WorkspaceConfig
from .shared import DEFAULT_REMOTE_ROOT, HOST_REGEX, hash_path

WORKSPACE_CONFIG = ".remote.toml"
GLOBAL_CONFIG = ".config/remote/defaults.toml"


class ConfigModel(BaseModel):
    class Config:
        extra = "forbid"


class ConnectionConfig(ConfigModel):
    host: str
    directory: Optional[Path] = None
    default: bool = False

    @validator("host")
    def hostname_valid(cls, host):
        assert re.match(HOST_REGEX, host) is not None, "must be a valid host name"
        return host


class SyncRulesConfig(ConfigModel):
    exclude: List[str] = Field(default_factory=list)
    include_vsc_ignore_patterns: Optional[bool] = None

    def extend(self, other: "SyncRulesConfig") -> None:
        self.exclude.extend(other.exclude)
        if other.include_vsc_ignore_patterns is not None:
            self.include_vsc_ignore_patterns = other.include_vsc_ignore_patterns


class WorkCycleConfig(ConfigModel):
    hosts: Optional[List[ConnectionConfig]] = None
    push: Optional[SyncRulesConfig] = None
    pull: Optional[SyncRulesConfig] = None
    both: Optional[SyncRulesConfig] = None


def hosts_can_have_only_one_default(cls, hosts):
    if not hosts:
        return hosts

    defaults_num = len([h for h in hosts if h.default])
    assert defaults_num < 2, "can only have one default"
    return hosts


class GeneralConfig(ConfigModel):
    allow_uninitiated_workspaces: bool = Field(default=False)
    use_relative_remote_paths: bool = Field(default=False)
    remote_root: Path = Field(default=Path(DEFAULT_REMOTE_ROOT))


class GlobalConfig(WorkCycleConfig):
    general: GeneralConfig = Field(default_factory=GeneralConfig)

    hosts_default = validator("hosts", allow_reuse=True)(hosts_can_have_only_one_default)

    @validator("hosts")
    def no_directories_in_hosts(cls, hosts):
        if not hosts:
            return hosts

        for host in hosts:
            assert host.directory is None, "cannot specify directory in global host config"
        return hosts


class LocalConfig(WorkCycleConfig):
    extends: Optional[WorkCycleConfig] = None

    hosts_default = validator("hosts", allow_reuse=True)(hosts_can_have_only_one_default)


def _load_file(cls, path: Path):
    if not path.exists():
        return cls()

    with path.open() as f:
        try:
            config = toml.load(f)
        except ValueError as e:
            raise ConfigurationError(f"TOML file {path} is unparasble: {e}") from e

    try:
        return cls.parse_obj(config)
    except ValidationError as e:
        messages = []
        for err in e.errors():
            location = ".".join((str(x) for x in err["loc"]))
            reason = err["msg"]
            messages.append(f"  - {location}: {reason}")

        msg = "\n".join(messages)
        raise ConfigurationError(f"Invalid value in configuration file {path}:\n{msg}") from e


def load_global_config() -> GlobalConfig:
    config_file = Path.home() / GLOBAL_CONFIG
    return _load_file(GlobalConfig, config_file)


def load_local_config(workspace_root: Path) -> LocalConfig:
    config_file = workspace_root / WORKSPACE_CONFIG
    config = _load_file(LocalConfig, config_file)

    if config.extends is not None:
        duplicate_fields = []
        for field in WorkCycleConfig.__fields__:
            if getattr(config, field) and getattr(config.extends, field):
                duplicate_fields.append(field)

        if duplicate_fields:
            fields_str = ",".join(duplicate_fields)
            raise ConfigurationError(
                f"Following fields are specified in for overwrite and extend in {config_file} file: {fields_str}."
            )

    return config


def _merge_field(field: str, global_config: GlobalConfig, local_config: LocalConfig) -> Any:
    result = getattr(global_config, field)
    local_result = getattr(local_config, field)
    if local_result is not None:
        result = local_result

    if local_config.extends is None:
        return result

    extension = getattr(local_config.extends, field)
    if extension is not None:
        if result is None:
            result = extension
        else:
            result.extend(extension)

    return result


def _get_exclude(sync_rules: Optional[SyncRulesConfig], workspace_root: Path) -> List[str]:
    if sync_rules is None:
        return []
    exclude = sync_rules.exclude

    gitignore = workspace_root / ".gitignore"
    if sync_rules.include_vsc_ignore_patterns and gitignore.exists():
        with gitignore.open() as f:
            for line in f.readlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                exclude.append(line)
    return exclude


def _clean_up_dict(data_dict: Dict[str, Any]) -> None:
    for key in data_dict:
        if isinstance(data_dict[key], Path):
            data_dict[key] = str(data_dict[key])
        elif isinstance(data_dict[key], dict):
            _clean_up_dict(data_dict[key])
        elif isinstance(data_dict[key], (list, tuple)):
            for item in data_dict[key]:
                if isinstance(item, dict):
                    _clean_up_dict(item)


def _save_config_file(config: ConfigModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    dict_data = config.dict()
    # this changes make toml file parsable and more readable from human's point of view
    _clean_up_dict(dict_data)
    for item in dict_data.get("hosts", []):
        if not item["default"]:
            del item["default"]

    with path.open("w") as f:
        toml.dump(dict_data, f)


def save_global_config(config: GlobalConfig) -> None:
    _save_config_file(config, Path.home() / GLOBAL_CONFIG)


class TomlConfigurationMedium(ConfigurationMedium):
    def __init__(self) -> None:
        self._global_config: Optional[GlobalConfig] = None

    @property
    def global_config(self) -> GlobalConfig:
        if self._global_config is None:
            self._global_config = load_global_config()

        return self._global_config

    def load_config(self, workspace_root: Path) -> WorkspaceConfig:
        local_config = load_local_config(workspace_root)

        # We might accidentally modify config value, so we need to create a copy of it
        global_config = self.global_config.copy()
        config_dict = {field: _merge_field(field, global_config, local_config) for field in WorkCycleConfig.__fields__}
        merged_config = WorkCycleConfig.parse_obj(config_dict)

        if merged_config.hosts is None:
            raise ConfigurationError("You need to provide at least one remote host to connect")

        configurations = []
        configuration_index = 0
        for num, connection in enumerate(merged_config.hosts):
            if connection.default:
                configuration_index = num
            configurations.append(
                RemoteConfig(
                    host=connection.host,
                    directory=connection.directory or self._generate_remote_directory_from_path(workspace_root),
                )
            )
        ignores = SyncIgnores(
            pull=_get_exclude(merged_config.pull, workspace_root),
            push=_get_exclude(merged_config.push, workspace_root),
            both=_get_exclude(merged_config.both, workspace_root) + [WORKSPACE_CONFIG],
        )

        return WorkspaceConfig(
            root=workspace_root,
            configurations=configurations,
            default_configuration=configuration_index,
            ignores=ignores,
        )

    def save_config(self, config: WorkspaceConfig) -> None:
        """Save configuration to its root

        For now, this method don't have any smart merging of extension arguments.
        """
        config.ignores.add_ignores([WORKSPACE_CONFIG])

        local_config = LocalConfig()
        local_config.hosts = []
        for num, connection in enumerate(config.configurations):
            local_config.hosts.append(
                ConnectionConfig(
                    host=connection.host, directory=connection.directory, default=num == config.default_configuration
                )
            )
        for key, value in asdict(config.ignores).items():
            setattr(local_config, key, SyncRulesConfig(exclude=value))

        _save_config_file(local_config, config.root / WORKSPACE_CONFIG)

    def is_workspace_root(self, path: Path) -> bool:
        return (path / WORKSPACE_CONFIG).exists() or self.global_config.general.allow_uninitiated_workspaces

    def generate_remote_directory(self, config: WorkspaceConfig) -> Path:
        return self._generate_remote_directory_from_path(config.root)

    def _generate_remote_directory_from_path(self, path: Path) -> Path:
        if self.global_config.general.use_relative_remote_paths:
            try:
                relative_path = path.relative_to(Path.home())
            except ValueError:
                # the workspace is not under home directory
                relative_path = path.relative_to(Path("/"))
            return self.global_config.general.remote_root / relative_path
        else:
            md5 = hash_path(path)
            return Path(f"{self.global_config.general.remote_root}/{path.name}_{md5}")
