import json
import os
import re
import shutil
import sqlite3
import subprocess
from collections.abc import Mapping, Sequence

from callboard.codes import HLS_UNAVAILABLE_EXIT, NOT_FOUND_EXIT
from callboard.errors import CallboardError
from callboard.models import BellhopSession, Participant
from callboard.store import participant, participants_with_route

HANDLE = re.compile(r"[a-z0-9][a-z0-9_-]*")
BELLHOP_TIMEOUT_SECONDS = 20.0
JOIN_HINT = "run: callboard join <handle>"


def validate_handle(handle: str, source: str = "handle") -> str:
    if HANDLE.fullmatch(handle) is None:
        raise CallboardError(
            f"{source} '{handle}' is not a valid handle; use lowercase letters, digits, '_' and"
            " '-', starting with a letter or digit",
            code="usage",
        )
    return handle


def _run_bellhop(
    arguments: Sequence[str], env: Mapping[str, str], timeout: float
) -> tuple[int, dict[str, object]]:
    command = " ".join(arguments[:1])
    executable = shutil.which("bellhop", path=env.get("PATH", os.defpath))
    if executable is None:
        raise CallboardError("bellhop not found on PATH", code="bellhop_failed")
    try:
        result = subprocess.run(
            [executable, *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=dict(env),
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise CallboardError(
            f"bellhop {command} timed out after {timeout:g}s", code="bellhop_failed"
        ) from error
    except OSError as error:
        raise CallboardError(
            f"cannot run bellhop {command}: {error}", code="bellhop_failed"
        ) from error
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise CallboardError(
            f"bellhop {command} printed no schema_version 1 JSON (exit {result.returncode})",
            code="bellhop_failed",
        )
    return result.returncode, payload


def _error_message(payload: Mapping[str, object]) -> str:
    error = payload.get("error")
    message = error.get("message") if isinstance(error, dict) else None
    return message if isinstance(message, str) else "no message"


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _bellhop_ok(
    arguments: Sequence[str], env: Mapping[str, str], timeout: float
) -> dict[str, object]:
    exit_code, payload = _run_bellhop(arguments, env, timeout)
    if payload.get("status") == "ok":
        return payload
    message = f"bellhop {arguments[0]}: {_error_message(payload)}"
    if exit_code == NOT_FOUND_EXIT:
        raise CallboardError(message, code="not_in_session")
    if exit_code == HLS_UNAVAILABLE_EXIT:
        raise CallboardError(message, code="hls_unavailable")
    raise CallboardError(message, code="bellhop_failed")


def whoami(env: Mapping[str, str], timeout: float = BELLHOP_TIMEOUT_SECONDS) -> BellhopSession:
    session = _bellhop_ok(["whoami", "--json"], env, timeout).get("session")
    if not isinstance(session, dict) or not isinstance(session.get("session_id"), str):
        raise CallboardError("bellhop whoami returned no session", code="bellhop_failed")
    return BellhopSession(
        session_id=session["session_id"],
        harness=str(session.get("harness")),
        title=_optional_text(session.get("title")),
        agent=_optional_text(session.get("agent")),
    )


def live_routes(env: Mapping[str, str], timeout: float = BELLHOP_TIMEOUT_SECONDS) -> frozenset[str]:
    sessions = _bellhop_ok(["sessions", "--json"], env, timeout).get("sessions")
    if not isinstance(sessions, list):
        raise CallboardError("bellhop sessions returned no sessions", code="bellhop_failed")
    entries = [entry for entry in sessions if isinstance(entry, dict)]
    return frozenset(
        value
        for entry in entries
        for value in (entry.get("session_id"), entry.get("agent"))
        if isinstance(value, str)
    )


def route_of(session: BellhopSession) -> str:
    return session.agent or session.session_id


def _explicit(conn: sqlite3.Connection, handle: str, source: str) -> Participant:
    found = participant(conn, validate_handle(handle, source))
    if found is None:
        raise CallboardError(
            f"{source}: no participant '{handle}'; run: callboard join {handle}",
            code="unknown_handle",
        )
    return found


def _joined(conn: sqlite3.Connection, session: BellhopSession) -> Participant:
    routes = [route for route in (session.agent, session.session_id) if route]
    for route in routes:
        matches = participants_with_route(conn, route)
        if len(matches) > 1:
            handles = ", ".join(match.handle for match in matches)
            raise CallboardError(
                f"this session is joined as {handles}; pass --as HANDLE",
                code="identity_ambiguous",
            )
        if matches:
            return matches[0]
    raise CallboardError(
        f"this session has not joined callboard; {JOIN_HINT}", code="identity_not_found"
    )


def resolve_caller(
    conn: sqlite3.Connection,
    as_handle: str | None,
    env: Mapping[str, str],
    timeout: float = BELLHOP_TIMEOUT_SECONDS,
) -> Participant:
    if as_handle:
        return _explicit(conn, as_handle, "--as")
    if env.get("CALLBOARD_AS"):
        return _explicit(conn, env["CALLBOARD_AS"], "CALLBOARD_AS")
    try:
        session = whoami(env, timeout)
    except CallboardError as error:
        if error.code != "not_in_session":
            raise
        raise CallboardError(
            f"cannot tell who you are; {error}; {JOIN_HINT}", code="identity_not_found"
        ) from error
    return _joined(conn, session)
