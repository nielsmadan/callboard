import json
import os
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from typing import cast, get_args

from callboard.codes import HLS_UNAVAILABLE_EXIT, NOT_FOUND_EXIT
from callboard.errors import CallboardError
from callboard.models import BellhopMessage, BellhopSession, PingState
from callboard.text import shortened

STATES: frozenset[str] = frozenset(get_args(PingState.__value__))

POLL_SECONDS = 0.1
COMMAND_SECONDS = 10.0
TEXT_LIMIT = 300


class BellhopTimeout(CallboardError):
    pass


@dataclass(frozen=True)
class Reply:
    exit_code: int
    payload: dict[str, object]


@dataclass(frozen=True)
class Caller:
    command: tuple[str, ...]
    env: Mapping[str, str] = field(repr=False)
    deadline: float
    budget: float


def caller_for(
    command: Sequence[str],
    env: Mapping[str, str],
    budget: float,
    now: Callable[[], float] = time.monotonic,
) -> Caller:
    return Caller(tuple(command), env, now() + budget, budget)


def resumed(caller: Caller, paused_at: float, now: Callable[[], float] = time.monotonic) -> Caller:
    return replace(caller, deadline=caller.deadline + (now() - paused_at))


def executable(command: Sequence[str], env: Mapping[str, str]) -> str:
    first = command[0]
    if "/" in first:
        return first
    found = shutil.which(first, path=env.get("PATH", os.defpath))
    if found is None:
        raise CallboardError(f"{first} not found on PATH", code="bellhop_failed")
    return found


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def _wait(
    process: subprocess.Popen[bytes],
    data: bytes | None,
    timeout: float,
    cancel: threading.Event | None,
) -> tuple[bytes, bytes]:
    end = time.monotonic() + max(timeout, 0.001)
    first = data
    while True:
        try:
            return process.communicate(
                first, timeout=max(min(POLL_SECONDS, end - time.monotonic()), 0.001)
            )
        except subprocess.TimeoutExpired:
            first = None
            if time.monotonic() >= end:
                raise
            if cancel is not None and cancel.is_set():
                raise CallboardError("cancelled", code="interrupted") from None


def _exchange(
    argv: Sequence[str],
    env: Mapping[str, str],
    timeout: float,
    stdin: str | None,
    cancel: threading.Event | None,
) -> tuple[int, bytes, bytes]:
    with subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(env),
        start_new_session=True,
    ) as process:
        try:
            stdout, stderr = _wait(
                process, None if stdin is None else stdin.encode(), timeout, cancel
            )
        except BaseException:
            _kill_group(process)
            raise
        return process.returncode, stdout, stderr


def _last_line(raw: bytes) -> str:
    lines = [line for line in raw.decode(errors="replace").splitlines() if line.strip()]
    return f": {shortened(lines[-1].strip(), TEXT_LIMIT)}" if lines else ""


def run(
    command: Sequence[str],
    arguments: Sequence[str],
    env: Mapping[str, str],
    timeout: float,
    stdin: str | None = None,
    cancel: threading.Event | None = None,
) -> Reply:
    name = f"bellhop {arguments[0]}"
    found = executable(command, env)
    try:
        returncode, raw, errors = _exchange(
            [found, *command[1:], *arguments], env, timeout, stdin, cancel
        )
        text = raw.decode()
    except subprocess.TimeoutExpired as error:
        raise BellhopTimeout(
            f"{name} timed out after {timeout:.1f}s", code="bellhop_failed"
        ) from error
    except OSError as error:
        raise CallboardError(f"cannot run {name}: {error}", code="bellhop_failed") from error
    except UnicodeDecodeError as error:
        raise CallboardError(
            f"{name} printed output that is not UTF-8", code="bellhop_failed"
        ) from error
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise CallboardError(
            f"{name} printed no schema_version 1 JSON (exit {returncode}){_last_line(errors)}",
            code="bellhop_failed",
        )
    return Reply(returncode, payload)


def call(
    caller: Caller,
    arguments: Sequence[str],
    stdin: str | None = None,
    now: Callable[[], float] = time.monotonic,
    cancel: threading.Event | None = None,
    worst: float = COMMAND_SECONDS,
) -> Reply:
    remaining = caller.deadline - now()
    if remaining <= 0:
        raise CallboardError(
            f"bellhop {arguments[0]}: no time left before the deadline", code="bellhop_failed"
        )
    limit = max(remaining, min(worst, caller.budget))
    return run(caller.command, arguments, caller.env, limit, stdin, cancel)


def error_code(payload: Mapping[str, object]) -> str | None:
    error = payload.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else None


def error_message(payload: Mapping[str, object]) -> str:
    error = payload.get("error")
    message = error.get("message") if isinstance(error, dict) else None
    return shortened(message, TEXT_LIMIT) if isinstance(message, str) else "no message"


def _candidates(payload: Mapping[str, object]) -> bool:
    error = payload.get("error")
    found = error.get("candidates") if isinstance(error, dict) else None
    return isinstance(found, list) and bool(found)


def require_ok(reply: Reply, name: str) -> dict[str, object]:
    if reply.payload.get("status") == "ok":
        return reply.payload
    message = f"bellhop {name}: {error_message(reply.payload)}"
    if reply.exit_code == NOT_FOUND_EXIT and _candidates(reply.payload):
        raise CallboardError(message, code="identity_ambiguous")
    if reply.exit_code == NOT_FOUND_EXIT:
        raise CallboardError(message, code="not_in_session")
    if reply.exit_code == HLS_UNAVAILABLE_EXIT:
        raise CallboardError(message, code="hls_unavailable")
    raise CallboardError(message, code="bellhop_failed")


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def warnings_of(payload: Mapping[str, object]) -> list[str]:
    found = payload.get("warnings")
    items = found if isinstance(found, list) else []
    return [shortened(item, TEXT_LIMIT) for item in items if isinstance(item, str)]


def parse_whoami(payload: Mapping[str, object]) -> BellhopSession:
    session = payload.get("session")
    if not isinstance(session, dict) or not isinstance(session.get("session_id"), str):
        raise CallboardError("bellhop whoami returned no session", code="bellhop_failed")
    return BellhopSession(
        session_id=session["session_id"],
        agent=_text(session.get("agent")),
    )


def _entries(payload: Mapping[str, object], key: str, name: str) -> list[dict[str, object]]:
    found = payload.get(key)
    if not isinstance(found, list):
        raise CallboardError(f"bellhop {name} returned no {key}", code="bellhop_failed")
    return [entry for entry in found if isinstance(entry, dict)]


def parse_sessions(payload: Mapping[str, object]) -> frozenset[str]:
    return frozenset(
        value
        for entry in _entries(payload, "sessions", "sessions")
        for value in (entry.get("session_id"), entry.get("agent"))
        if isinstance(value, str)
    )


def parse_agents(payload: Mapping[str, object]) -> frozenset[str]:
    return frozenset(
        name
        for entry in _entries(payload, "agents", "agents")
        if isinstance(name := entry.get("agent"), str)
    )


def parse_message(value: object) -> BellhopMessage | None:
    if not isinstance(value, dict):
        return None
    identifier, state = value.get("id"), value.get("state")
    if not isinstance(identifier, str) or state not in STATES:
        return None
    return BellhopMessage(
        identifier,
        cast("PingState", state),
        _text(value.get("urgency")),
        _text(value.get("detail")),
    )


def parse_status(payload: Mapping[str, object]) -> dict[str, BellhopMessage]:
    parsed = [parse_message(entry) for entry in _entries(payload, "messages", "status")]
    return {message.id: message for message in parsed if message is not None}
