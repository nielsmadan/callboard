import re
import sqlite3

from callboard.bellhop_client import (
    Caller,
    call,
    parse_agents,
    parse_sessions,
    parse_whoami,
    require_ok,
)
from callboard.errors import CallboardError
from callboard.models import BellhopSession, Participant
from callboard.store import participant, participants_with_route

HANDLE = re.compile(r"[a-z0-9][a-z0-9_-]*")
JOIN_HINT = "run: callboard join <handle>"


def validate_handle(handle: str, source: str = "handle") -> str:
    if HANDLE.fullmatch(handle) is None:
        raise CallboardError(
            f"{source} '{handle}' is not a valid handle; use lowercase letters, digits, '_' and"
            " '-', starting with a letter or digit",
            code="usage",
        )
    return handle


def _bellhop(name: str, caller: Caller) -> dict[str, object]:
    return require_ok(call(caller, [name, "--json"]), name)


def whoami(caller: Caller) -> BellhopSession:
    return parse_whoami(_bellhop("whoami", caller))


def live_routes(caller: Caller) -> frozenset[str]:
    return parse_sessions(_bellhop("sessions", caller)) | parse_agents(_bellhop("agents", caller))


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


def resolve_caller(conn: sqlite3.Connection, as_handle: str | None, caller: Caller) -> Participant:
    if as_handle:
        return _explicit(conn, as_handle, "--as")
    if caller.env.get("CALLBOARD_AS"):
        return _explicit(conn, caller.env["CALLBOARD_AS"], "CALLBOARD_AS")
    try:
        session = whoami(caller)
    except CallboardError as error:
        if error.code != "not_in_session":
            raise
        raise CallboardError(
            f"cannot tell who you are; {error}; {JOIN_HINT}", code="identity_not_found"
        ) from error
    return _joined(conn, session)
