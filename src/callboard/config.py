import tomllib
from dataclasses import dataclass
from pathlib import Path

from callboard.errors import CallboardError

DEFAULT_MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024


DEFAULT_PING_COMMAND = ("bellhop",)
KEYS = frozenset({"max_attachment_bytes", "ping_command"})


@dataclass(frozen=True)
class Config:
    max_attachment_bytes: int = DEFAULT_MAX_ATTACHMENT_BYTES
    ping_command: tuple[str, ...] = DEFAULT_PING_COMMAND


def load_config(path: Path) -> Config:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Config()
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise CallboardError(f"cannot read {path}: {error}", code="invalid_config") from error
    unknown = sorted(set(raw) - KEYS)
    if unknown:
        raise CallboardError(
            f"{path}: unknown key{'s' if len(unknown) > 1 else ''}"
            f" {', '.join(repr(key) for key in unknown)}",
            code="invalid_config",
        )
    limit = raw.get("max_attachment_bytes", DEFAULT_MAX_ATTACHMENT_BYTES)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise CallboardError(
            f"{path}: max_attachment_bytes must be a positive integer; got {limit!r}",
            code="invalid_config",
        )
    command = raw.get("ping_command", list(DEFAULT_PING_COMMAND))
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(part, str) and part for part in command)
    ):
        raise CallboardError(
            f"{path}: ping_command must be a non-empty list of strings; got {command!r}",
            code="invalid_config",
        )
    return Config(max_attachment_bytes=limit, ping_command=tuple(command))
