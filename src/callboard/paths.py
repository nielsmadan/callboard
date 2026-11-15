from collections.abc import Mapping
from pathlib import Path

from callboard.errors import CallboardError


def data_dir(env: Mapping[str, str]) -> Path:
    raw = env.get("XDG_DATA_HOME", "")
    if not raw:
        home = env.get("HOME", "")
        return (Path(home) if home else Path.home()) / ".local" / "share" / "callboard"
    base = Path(raw)
    if not base.is_absolute():
        raise CallboardError(
            f"XDG_DATA_HOME must be an absolute path; got '{raw}'", code="invalid_environment"
        )
    return base / "callboard"


def store_path(env: Mapping[str, str]) -> Path:
    return data_dir(env) / "callboard.sqlite"
