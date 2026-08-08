import json
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


FIELD_TYPES = {
    "app": {"appId": str, "appSecret": str},
    "recipient": {"openId": str},
    "notification": {"autoNotify": bool},
}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    app_id: str
    app_secret: str
    receive_open_id: str
    auto_notify: bool


ENVIRONMENT_FIELDS = {
    "FEISHU_APP_ID": "app.appId",
    "FEISHU_APP_SECRET": "app.appSecret",
    "FEISHU_RECEIVE_OPEN_ID": "recipient.openId",
    "FEISHU_AUTO_NOTIFY": "notification.autoNotify",
}
REQUIRED_FIELDS = ("app.appId", "app.appSecret", "recipient.openId")
DIAGNOSTIC_FIELDS = (
    "app.appId",
    "app.appSecret",
    "recipient.openId",
    "notification.autoNotify",
)
REDACTED_DIAGNOSTIC_FIELDS = {"app.appSecret", "recipient.openId"}


@dataclass(frozen=True)
class ConfigPaths:
    global_file: Path
    project_file: Path
    legacy_env_file: Path


@dataclass(frozen=True)
class ResolvedSettings:
    values: Mapping[str, object]
    sources: Mapping[str, str]


@dataclass(frozen=True)
class ResolvedConfig:
    config: Config
    sources: Mapping[str, str]


def parse_bool(value, key):
    if not isinstance(value, str):
        raise ConfigError("%s must be true or false" % key)
    _validate_unicode_scalar(value)
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ConfigError("%s must be true or false" % key)


def _validate_unicode_scalar(value):
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ConfigError(
            "configuration text must contain valid Unicode scalar values"
        ) from exc


def _resolve_path(path):
    try:
        return Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ConfigError("unable to resolve configuration path") from exc


def _same_config_path(first, second):
    _resolve_path(first)
    _resolve_path(second)
    try:
        first_path = os.path.normcase(os.path.abspath(os.fspath(first)))
        second_path = os.path.normcase(os.path.abspath(os.fspath(second)))
    except (OSError, ValueError, TypeError) as exc:
        raise ConfigError("unable to resolve configuration path") from exc
    return first_path == second_path


def _same_existing_directory(first, second):
    try:
        if not Path(first).is_dir() or not Path(second).is_dir():
            return False
        return Path(first).samefile(second)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ConfigError("unable to resolve configuration path") from exc


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        _validate_unicode_scalar(key)
        if key in result:
            raise ConfigError("duplicate JSON key in configuration")
        result[key] = value
    return result


def _read_json_object(path, source):
    path = Path(path)
    try:
        if not path.exists():
            return None
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw, object_pairs_hook=_json_object)
    except (
        OSError,
        UnicodeDecodeError,
        ValueError,
        RecursionError,
        json.JSONDecodeError,
    ) as exc:
        raise ConfigError("unable to read valid %s JSON configuration" % source) from exc
    if not isinstance(payload, dict):
        raise ConfigError("%s configuration root must be an object" % source)
    return payload


def validate_global_secret_permissions(path):
    if os.name != "posix":
        return
    try:
        mode = stat.S_IMODE(Path(path).stat().st_mode)
    except OSError as exc:
        raise ConfigError("unable to inspect global configuration permissions") from exc
    if mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
        raise ConfigError(
            "global configuration containing app.appSecret must be private; "
            "run chmod 600 on the file"
        )


def load_json_fields(path, source, allow_app_secret):
    payload = _read_json_object(path, source)
    if payload is None:
        return {}
    if (
        source == "global"
        and isinstance(payload.get("app"), dict)
        and "appSecret" in payload["app"]
    ):
        validate_global_secret_permissions(path)
    values = {}
    for group, group_value in payload.items():
        if group not in FIELD_TYPES:
            raise ConfigError("unknown top-level configuration field")
        if not isinstance(group_value, dict):
            raise ConfigError("%s must be an object" % group)
        for leaf, value in group_value.items():
            dotted = "%s.%s" % (group, leaf)
            if leaf not in FIELD_TYPES[group]:
                raise ConfigError("unknown field in %s configuration" % group)
            if dotted == "app.appSecret" and not allow_app_secret:
                raise ConfigError(
                    "project configuration must not contain app.appSecret"
                )
            if value is None:
                raise ConfigError("%s must not be null" % dotted)
            expected_type = FIELD_TYPES[group][leaf]
            if not isinstance(value, expected_type):
                expected_name = "a boolean" if expected_type is bool else "a string"
                raise ConfigError("%s must be %s" % (dotted, expected_name))
            if expected_type is str:
                _validate_unicode_scalar(value)
                value = value.strip()
                if not value:
                    raise ConfigError("%s must not be empty" % dotted)
            values[dotted] = value
    return values


def resolve_project_root(explicit_project_root, cwd, git_runner=subprocess.run):
    cwd = _resolve_path(cwd)
    if explicit_project_root is not None:
        root = _resolve_path(explicit_project_root)
        if not root.is_dir():
            raise ConfigError("--project-root must name an existing directory")
        return root
    argv = ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"]
    try:
        result = git_runner(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except UnicodeError as exc:
        raise ConfigError("unable to determine project root from Git") from exc
    except OSError:
        return cwd
    if result.returncode == 0 and result.stdout.strip():
        return _resolve_path(result.stdout.strip())
    return cwd


def build_config_paths(
    explicit_project_root=None,
    cwd=None,
    home=None,
    git_runner=subprocess.run,
    connector_root=None,
):
    cwd = Path.cwd() if cwd is None else Path(cwd)
    home = _resolve_path(Path.home() if home is None else home)
    connector_root = (
        Path(__file__).resolve().parents[1]
        if connector_root is None
        else Path(connector_root)
    )
    project_root = resolve_project_root(
        explicit_project_root, cwd, git_runner=git_runner
    )
    global_file = home / ".config" / "feishu-connector" / "config.json"
    project_file = (
        project_root / ".config" / "feishu-connector" / "config.json"
    )
    if _same_existing_directory(home, project_root):
        project_file = global_file
    return ConfigPaths(
        global_file=global_file,
        project_file=project_file,
        legacy_env_file=connector_root / ".env",
    )


def _environment_value(environment_name, dotted, value):
    if dotted == "notification.autoNotify":
        return parse_bool(value, environment_name)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("%s must not be empty" % environment_name)
    _validate_unicode_scalar(value)
    return value.strip()


def resolve_settings(paths, environ):
    values = {}
    sources = {}
    layers = [("global", load_json_fields(paths.global_file, "global", True))]
    if not _same_config_path(paths.global_file, paths.project_file):
        layers.append(
            ("project", load_json_fields(paths.project_file, "project", False))
        )
    for source, fields in layers:
        for dotted, value in fields.items():
            values[dotted] = value
            sources[dotted] = source
    for environment_name, dotted in ENVIRONMENT_FIELDS.items():
        if environment_name in environ:
            values[dotted] = _environment_value(
                environment_name, dotted, environ[environment_name]
            )
            sources[dotted] = "environment"
    if "notification.autoNotify" not in values:
        values["notification.autoNotify"] = False
        sources["notification.autoNotify"] = "default"
    return ResolvedSettings(values=values, sources=sources)


def missing_required_fields(settings):
    return tuple(field for field in REQUIRED_FIELDS if field not in settings.values)


def config_from_settings(settings):
    missing = missing_required_fields(settings)
    if missing:
        raise ConfigError("missing required configuration: %s" % ", ".join(missing))
    config = Config(
        app_id=settings.values["app.appId"],
        app_secret=settings.values["app.appSecret"],
        receive_open_id=settings.values["recipient.openId"],
        auto_notify=settings.values["notification.autoNotify"],
    )
    return ResolvedConfig(config=config, sources=settings.sources)


def load_config(paths, environ):
    return config_from_settings(resolve_settings(paths, environ))


def auto_notify_enabled(paths, environ):
    return bool(resolve_settings(paths, environ).values["notification.autoNotify"])


def format_source_diagnostics(resolution):
    lines = []
    for dotted in DIAGNOSTIC_FIELDS:
        source = resolution.sources[dotted]
        suffix = " (redacted)" if dotted in REDACTED_DIAGNOSTIC_FIELDS else ""
        lines.append("%s: %s%s" % (dotted, source, suffix))
    return "\n".join(lines)


def legacy_migration_message(legacy_env_file):
    try:
        exists = Path(legacy_env_file).is_file()
    except OSError:
        exists = False
    if not exists:
        return None
    return (
        "Legacy feishu-connector/.env detected but Phase 2 configuration is "
        "incomplete or invalid. Move appSecret to the global JSON or process "
        "environment, move project overrides to "
        ".config/feishu-connector/config.json, and remove the old file after "
        "migration. The legacy .env was not read."
    )
