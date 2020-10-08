"""
This module contains the medium for toml-based config that consists of global and local parts.

See the README.md file for details
"""
import re

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Type, TypeVar, Union

import toml

from pydantic import BaseModel, Field, ValidationError, validator

from remote.exceptions import ConfigurationError

from . import ConfigurationMedium, RemoteConfig, SyncRules, WorkspaceConfig
from .shared import DEFAULT_REMOTE_ROOT, HOST_REGEX, hash_path

WORKSPACE_CONFIG = ".remote.toml"
WORKSPACE_SYNC_CONFIG = ".remoteignore.toml"
GLOBAL_CONFIG = ".config/remote/defaults.toml"


class ConfigModel(BaseModel):
    class Config:
        extra = "forbid"


class ConnectionConfig(ConfigModel):
    host: str
    port: Optional[int] = Field(default=None, gt=1, le=65535)
    directory: Optional[Path] = None
    default: bool = False
    label: Optional[str] = None
    # True if remote host supports gssapi-* auth methods. Should de disable if it isn't because it might result
    # in connection hanging for some time before establishing
    # The default is True for backward compatibility, we might reconsider this in next major version
    supports_gssapi_auth: bool = Field(default=True)

    @validator("host")
    def hostname_valid(cls, host):
        assert re.match(HOST_REGEX, host) is not None, "must be a valid host name"
        return host


class SyncRulesConfig(ConfigModel):
    exclude: List[str] = Field(default_factory=list)
    include: List[str] = Field(default_factory=list)
    include_vcs_ignore_patterns: Optional[bool] = None

    def extend(self, other: "SyncRulesConfig") -> None:
        self.exclude.extend(other.exclude)
        self.include.extend(other.include)
        if other.include_vcs_ignore_patterns is not None:
            self.include_vcs_ignore_patterns = other.include_vcs_ignore_patterns


class AggregateSyncRulesConfig(ConfigModel):
    push: Optional[SyncRulesConfig] = None
    pull: Optional[SyncRulesConfig] = None
    both: Optional[SyncRulesConfig] = None


class LocalSyncRulesConfig(AggregateSyncRulesConfig):
    extends: Optional[AggregateSyncRulesConfig] = None


class WorkCycleConfig(AggregateSyncRulesConfig):
    hosts: Optional[List[ConnectionConfig]] = None


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


T = TypeVar("T", bound=ConfigModel)


def _load_file(cls: Type[T], path: Path) -> T:
    if not path.exists():
        return cls()

    with path.open() as f:
        try:
            config = toml.load(f)
        except ValueError as e:
            raise ConfigurationError(f"TOML file {path} is unparasble: {e}") from e

    # In previous versions of remote, `include_vcs_ignore_patterns` key was named with a typo
    # Now we need to check if config is using the old name to maintain backward compatibility
    _backward_compatible_sanitize(config, {"include_vsc_ignore_patterns": "include_vcs_ignore_patterns"})

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


def _backward_compatible_sanitize(data_dict: MutableMapping[str, Any], replacements: Dict[str, str]) -> None:
    for key in list(data_dict.keys()):
        if isinstance(data_dict[key], dict):
            _backward_compatible_sanitize(data_dict[key], replacements)
        if key in replacements:
            data_dict[replacements[key]] = data_dict.pop(key)


def load_global_config() -> GlobalConfig:
    config_file = Path.home() / GLOBAL_CONFIG
    return _load_file(GlobalConfig, config_file)


def load_local_ignores_config(workspace_root: Path) -> LocalSyncRulesConfig:
    config_file = workspace_root / WORKSPACE_SYNC_CONFIG
    return _load_file(LocalSyncRulesConfig, config_file)


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


def _merge_field(
    field: str, global_config: GlobalConfig, local_config: LocalConfig, local_ignores_config: LocalSyncRulesConfig
) -> Any:
    result = getattr(global_config, field)

    cfg: Union[LocalConfig, LocalSyncRulesConfig]
    for cfg in (local_config, local_ignores_config):  # type: ignore
        if not hasattr(cfg, field):
            continue

        local_result = getattr(cfg, field)
        if local_result is not None:
            result = local_result

        if cfg.extends is None:
            continue

        extension = getattr(cfg.extends, field)
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
    if sync_rules.include_vcs_ignore_patterns and gitignore.exists():
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
        local_ignores_config = load_local_ignores_config(workspace_root)

        # We might accidentally modify config value, so we need to create a copy of it
        global_config = self.global_config.copy()
        config_dict = {
            field: _merge_field(field, global_config, local_config, local_ignores_config)
            for field in WorkCycleConfig.__fields__
        }
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
                    supports_gssapi=connection.supports_gssapi_auth,
                    label=connection.label,
                    port=connection.port,
                )
            )
        ignores = SyncRules(
            pull=_get_exclude(merged_config.pull, workspace_root),
            push=_get_exclude(merged_config.push, workspace_root),
            both=_get_exclude(merged_config.both, workspace_root) + [WORKSPACE_CONFIG],
        )

        includes = SyncRules(
            pull=merged_config.pull.include if merged_config.pull else [],
            push=merged_config.push.include if merged_config.push else [],
            both=merged_config.both.include if merged_config.both else [],
        )

        return WorkspaceConfig(
            root=workspace_root,
            configurations=configurations,
            default_configuration=configuration_index,
            ignores=ignores,
            includes=includes,
        )

    def save_config(self, config: WorkspaceConfig) -> None:
        """Save configuration to its root

        For now, this method don't have any smart merging of extension arguments.
        """
        config.ignores.add([WORKSPACE_CONFIG])

        local_config = LocalConfig()
        local_config.hosts = []
        for num, connection in enumerate(config.configurations):
            local_config.hosts.append(
                ConnectionConfig(
                    host=connection.host,
                    directory=connection.directory,
                    default=num == config.default_configuration,
                    supports_gssapi_auth=connection.supports_gssapi,
                    label=connection.label,
                    port=connection.port,
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
