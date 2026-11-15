import json
import os
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import cast, get_args

from callboard.codes import HLS_UNAVAILABLE_EXIT, NOT_FOUND_EXIT
from callboard.errors import CallboardError
from callboard.models import BellhopMessage, BellhopSession, PingState

STATES: frozenset[str] = frozenset(get_args(PingState.__value__))

POLL_SECONDS = 0.1


@dataclass(frozen=True)
class Reply:
    exit_code: int
    payload: dict[str, object]


@dataclass(frozen=True)
class Caller:
    command: tuple[str, ...]
    env: Mapping[str, str]
    deadline: float


def caller_for(
    command: Sequence[str],
    env: Mapping[str, str],
    budget: float,
    now: Callable[[], float] = time.monotonic,
) -> Caller:
    return Caller(tuple(command), env, now() + budget)


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
) -> bytes:
    end = time.monotonic() + max(timeout, 0.001)
    first = data
    while True:
        try:
            stdout, _ = process.communicate(
                first, timeout=max(min(POLL_SECONDS, end - time.monotonic()), 0.001)
            )
            return stdout
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
) -> tuple[int, bytes]:
    with subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(env),
        start_new_session=True,
    ) as process:
        try:
            stdout = _wait(process, None if stdin is None else stdin.encode(), timeout, cancel)
        except BaseException:
            _kill_group(process)
            raise
        return process.returncode, stdout


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
        returncode, raw = _exchange([found, *command[1:], *arguments], env, timeout, stdin, cancel)
        text = raw.decode()
    except subprocess.TimeoutExpired as error:
        raise CallboardError(
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
            f"{name} printed no schema_version 1 JSON (exit {returncode})",
            code="bellhop_failed",
        )
    return Reply(returncode, payload)


def call(
    caller: Caller,
    arguments: Sequence[str],
    stdin: str | None = None,
    now: Callable[[], float] = time.monotonic,
    cancel: threading.Event | None = None,
) -> Reply:
    remaining = caller.deadline - now()
    if remaining <= 0:
        raise CallboardError(
            f"bellhop {arguments[0]}: no time left before the deadline", code="bellhop_failed"
        )
    return run(caller.command, arguments, caller.env, remaining, stdin, cancel)


def error_code(payload: Mapping[str, object]) -> str | None:
    error = payload.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else None


def error_message(payload: Mapping[str, object]) -> str:
    error = payload.get("error")
    message = error.get("message") if isinstance(error, dict) else None
    return message if isinstance(message, str) else "no message"


def require_ok(reply: Reply, name: str) -> dict[str, object]:
    if reply.payload.get("status") == "ok":
        return reply.payload
    message = f"bellhop {name}: {error_message(reply.payload)}"
    if reply.exit_code == NOT_FOUND_EXIT:
        raise CallboardError(message, code="not_in_session")
    if reply.exit_code == HLS_UNAVAILABLE_EXIT:
        raise CallboardError(message, code="hls_unavailable")
    raise CallboardError(message, code="bellhop_failed")


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def warnings_of(payload: Mapping[str, object]) -> list[str]:
    found = payload.get("warnings")
    return [item for item in found if isinstance(item, str)] if isinstance(found, list) else []


def parse_whoami(payload: Mapping[str, object]) -> BellhopSession:
    session = payload.get("session")
    if not isinstance(session, dict) or not isinstance(session.get("session_id"), str):
        raise CallboardError("bellhop whoami returned no session", code="bellhop_failed")
    return BellhopSession(
        session_id=session["session_id"],
        harness=str(session.get("harness")),
        title=_text(session.get("title")),
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
        _text(value.get("degraded_from")),
        _text(value.get("detail")),
    )


def parse_status(payload: Mapping[str, object]) -> dict[str, BellhopMessage]:
    parsed = [parse_message(entry) for entry in _entries(payload, "messages", "status")]
    return {message.id: message for message in parsed if message is not None}
