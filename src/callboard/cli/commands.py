import argparse
import sqlite3
from collections.abc import Sequence
from contextlib import closing

from callboard.bellhop_client import Caller
from callboard.cli.context import bellhop, settings
from callboard.cli.presentation import diagnostic, emit
from callboard.errors import CallboardError
from callboard.identity import (
    identity_source,
    live_routes,
    resolve_caller,
    route_of,
    session_routes,
    validate_handle,
    whoami,
)
from callboard.jsonout import ok_payload
from callboard.models import BellhopSession, Participant, ParticipantKind, Runtime
from callboard.paths import store_path
from callboard.store import Session, join_participant, open_store, participant, participants


def describe(member: Participant) -> str:
    if member.route:
        return f"route {member.route}"
    return "human, no route" if member.kind == "human" else "no route"


def _session(bell: Caller) -> BellhopSession:
    try:
        return whoami(bell)
    except CallboardError as error:
        if error.code != "not_in_session":
            raise
        raise CallboardError(
            f"{error}; if you are a person at a terminal, run: callboard join <handle> --human",
            code="not_in_session",
        ) from error


def _checked(
    routes: tuple[str, ...], previous: Participant | None, human: bool, runtime: Runtime
) -> Session:
    if not human or previous is None or previous.kind != "agent" or not previous.route:
        return Session(routes)
    try:
        return Session(routes, live_routes(bellhop(runtime, settings(runtime))))
    except CallboardError as error:
        return Session(routes, None, str(error))


def join(args: argparse.Namespace, runtime: Runtime) -> int:
    if args.as_handle:
        raise CallboardError(
            "join does not take --as; it joins the session it runs in", code="usage"
        )
    env = runtime.env
    handle = validate_handle(args.handle)
    kind: ParticipantKind = "human" if args.human else "agent"
    session = None if args.human else _session(bellhop(runtime, settings(runtime)))
    route = None if session is None else route_of(session)
    routes = () if session is None else session_routes(session)
    with closing(open_store(store_path(env))) as conn:
        checked = _checked(routes, participant(conn, handle), args.human, runtime)
        outcome = join_participant(conn, handle, kind, route, runtime.clock(), checked)
    current, previous = outcome.current, outcome.previous
    rebound = previous is not None and (previous.kind, previous.route) != (
        current.kind,
        current.route,
    )
    notices = [
        *(
            f"moved this session from '{other}' to '{handle}' ({describe(current)})"
            for other in outcome.displaced
        ),
        *(
            [f"rebound '{handle}' from {describe(previous)} to {describe(current)}"]
            if previous is not None and rebound
            else []
        ),
    ]
    for notice in notices:
        diagnostic(notice)
    payload = ok_payload(
        {
            "participant": _participant_json(current),
            "previous": None if previous is None else _participant_json(previous),
            "displaced": list(outcome.displaced),
        },
        notices,
    )
    emit(payload, [f"joined as {handle} ({describe(current)})"], json_mode=args.json)
    return 0


def _caller(
    conn: sqlite3.Connection, args: argparse.Namespace, bell: Caller
) -> tuple[str | None, list[str]]:
    try:
        return resolve_caller(conn, args.as_handle, bell).handle, []
    except CallboardError as error:
        if error.code == "identity_not_found":
            return None, []
        if error.code in {"identity_ambiguous", "hls_unavailable", "bellhop_failed"}:
            return None, [str(error)]
        raise


def _participant_json(member: Participant) -> dict[str, object]:
    return {
        "handle": member.handle,
        "kind": member.kind,
        "route": member.route,
        "created_at": member.created_at,
    }


def _who_lines(members: Sequence[Participant], you: str | None) -> list[str]:
    rows = [("", "handle", "kind", "route")] + [
        ("*" if member.handle == you else "", member.handle, member.kind, member.route or "-")
        for member in members
    ]
    widths = [max(len(row[index]) for row in rows) for index in range(3)]
    return [
        "  ".join(
            [*(cell.ljust(width) for cell, width in zip(row[:3], widths, strict=True)), row[3]]
        )
        for row in rows
    ]


def _source_line(source: str | None) -> list[str]:
    if source == "--as":
        return ["* is you through --as"]
    if source == "CALLBOARD_AS":
        return ["* is you through $CALLBOARD_AS; unset it if this is not you"]
    return []


def who(args: argparse.Namespace, runtime: Runtime) -> int:
    env = runtime.env
    with closing(open_store(store_path(env))) as conn:
        members = participants(conn)
        you, warnings = _caller(conn, args, bellhop(runtime, settings(runtime)))
    for warning in warnings:
        diagnostic(warning)
    source = identity_source(args.as_handle, env) if you else None
    payload = ok_payload(
        {
            "you": you,
            "you_from": source,
            "participants": [_participant_json(member) for member in members],
        },
        warnings,
    )
    lines = (
        [*_who_lines(members, you), *_source_line(source)]
        if members
        else ["no participants yet; run: callboard join <handle>"]
    )
    emit(payload, lines, json_mode=args.json)
    return 0
