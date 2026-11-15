from collections.abc import Mapping
from pathlib import Path

from callboard.errors import CallboardError


def _xdg(env: Mapping[str, str], name: str, fallback: tuple[str, ...]) -> Path:
    raw = env.get(name, "")
    if not raw:
        home = env.get("HOME", "")
        return (Path(home) if home else Path.home()).joinpath(*fallback)
    base = Path(raw)
    if not base.is_absolute():
        raise CallboardError(
            f"{name} must be an absolute path; got '{raw}'", code="invalid_environment"
        )
    return base


def data_dir(env: Mapping[str, str]) -> Path:
    return _xdg(env, "XDG_DATA_HOME", (".local", "share")) / "callboard"


def store_path(env: Mapping[str, str]) -> Path:
    return data_dir(env) / "callboard.sqlite"


def attachments_dir(env: Mapping[str, str]) -> Path:
    return data_dir(env) / "attachments"


def config_path(env: Mapping[str, str]) -> Path:
    return _xdg(env, "XDG_CONFIG_HOME", (".config",)) / "callboard" / "config.toml"
