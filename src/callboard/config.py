import tomllib
from dataclasses import dataclass
from pathlib import Path

from callboard.errors import CallboardError

DEFAULT_MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class Config:
    max_attachment_bytes: int = DEFAULT_MAX_ATTACHMENT_BYTES


def load_config(path: Path) -> Config:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Config()
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise CallboardError(f"cannot read {path}: {error}", code="invalid_config") from error
    limit = raw.get("max_attachment_bytes", DEFAULT_MAX_ATTACHMENT_BYTES)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise CallboardError(
            f"{path}: max_attachment_bytes must be a positive integer; got {limit!r}",
            code="invalid_config",
        )
    return Config(max_attachment_bytes=limit)
