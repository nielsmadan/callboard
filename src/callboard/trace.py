import contextlib
import json
import os
import stat
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from callboard.models import Emit, quiet
from callboard.paths import data_dir

FILE_NAME = "trace.jsonl"
OLD_NAME = "trace.jsonl.1"
ENV = "CALLBOARD_TRACE"
OFF = "off"
FILE_LIMIT = 4 << 20
TEXT_LIMIT = 300
READ_LIMIT = FILE_LIMIT * 2


def utc_now() -> datetime:
    return datetime.now(UTC)


def trace_path(env: Mapping[str, str]) -> Path:
    return data_dir(env) / FILE_NAME


def clipped(value: object) -> object:
    if isinstance(value, str) and len(value) > TEXT_LIMIT:
        return f"{value[:TEXT_LIMIT]}… ({len(value)} characters)"
    if isinstance(value, list | tuple):
        return [clipped(item) for item in value]
    if isinstance(value, dict):
        return {str(key): clipped(item) for key, item in value.items()}
    return value


def record(pid: int, at: datetime, event: str, fields: Mapping[str, object]) -> dict[str, object]:
    head: dict[str, object] = {
        "at": at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "pid": pid,
        "event": event,
    }
    return head | {name: clipped(value) for name, value in fields.items() if value is not None}


def open_private(path: Path, flags: int) -> int:
    descriptor = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
    info = os.fstat(descriptor)
    if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid():
        return descriptor
    os.close(descriptor)
    raise PermissionError(f"{path} is not a private regular file")


def working_directory() -> str | None:
    try:
        return os.getcwd()
    except OSError:
        return None


def rotate(path: Path, limit: int = FILE_LIMIT) -> None:
    try:
        if path.lstat().st_size <= limit:
            return
    except OSError:
        return
    try:
        os.replace(path, path.with_name(OLD_NAME))
    except OSError:
        with contextlib.suppress(OSError):
            os.close(open_private(path, os.O_WRONLY | os.O_TRUNC))


def append(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    rotate(path)
    descriptor = open_private(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
    try:
        os.write(descriptor, text.encode())
    finally:
        os.close(descriptor)


def tracer(env: Mapping[str, str], *, now: Callable[[], datetime] = utc_now) -> Emit:
    if env.get(ENV) == OFF:
        return quiet

    def emit(event: str, /, **fields: object) -> None:
        try:
            line = json.dumps(
                record(os.getpid(), now(), event, fields), ensure_ascii=False, default=str
            )
            append(trace_path(env), f"{line}\n")
        except Exception:  # noqa: BLE001, S110
            pass

    return emit


def read_lines(path: Path) -> list[str]:
    try:
        descriptor = open_private(path, os.O_RDONLY)
    except OSError:
        return []
    with os.fdopen(descriptor, "rb") as handle:
        handle.seek(max(0, os.fstat(descriptor).st_size - READ_LIMIT))
        return handle.read(READ_LIMIT).decode("utf-8", errors="replace").splitlines()


def parsed(line: str) -> dict[str, object] | None:
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def failed(event: Mapping[str, object]) -> bool:
    return bool(event.get("error") or event.get("warnings") or event.get("exit") not in (None, 0))


def read_events(
    env: Mapping[str, str], *, count: int, words: Sequence[str] = (), failures: bool = False
) -> list[dict[str, object]]:
    path = trace_path(env)
    lines = [*read_lines(path.with_name(OLD_NAME)), *read_lines(path)]
    events = [parsed(line) for line in lines if all(word in line for word in words)]
    found = [event for event in events if event is not None]
    return [event for event in found if not failures or failed(event)][-count:]
