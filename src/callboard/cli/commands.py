import argparse
import sqlite3
from collections.abc import Sequence
from contextlib import closing

from callboard.bellhop_client import Caller
from callboard.cli.context import bellhop, settings
from callboard.cli.presentation import diagnostic, emit
from callboard.errors import CallboardError
from callboard.identity import resolve_caller, route_of, validate_handle, whoami
from callboard.jsonout import ok_payload
from callboard.models import BellhopSession, Participant, ParticipantKind, Runtime
from callboard.paths import store_path
from callboard.store import join_participant, open_store, participants


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
            f"{error}; to join without a session, run: callboard join <handle> --human",
            code="not_in_session",
        ) from error


def join(args: argparse.Namespace, runtime: Runtime) -> int:
    env = runtime.env
    handle = validate_handle(args.handle)
    kind: ParticipantKind = "human" if args.human else "agent"
    route = None if args.human else route_of(_session(bellhop(runtime, settings(runtime))))
    with closing(open_store(store_path(env))) as conn:
        outcome = join_participant(conn, handle, kind, route, runtime.clock())
    current, previous = outcome.current, outcome.previous
    for other in outcome.displaced:
        diagnostic(f"moved {describe(current)} from '{other}' to '{handle}'")
    if previous is not None and (previous.kind, previous.route) != (current.kind, current.route):
        diagnostic(f"rebound '{handle}' from {describe(previous)} to {describe(current)}")
    print(f"joined as {handle} ({describe(current)})")
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


def who(args: argparse.Namespace, runtime: Runtime) -> int:
    env = runtime.env
    with closing(open_store(store_path(env))) as conn:
        members = participants(conn)
        you, warnings = _caller(conn, args, bellhop(runtime, settings(runtime)))
    for warning in warnings:
        diagnostic(warning)
    payload = ok_payload(
        {"you": you, "participants": [_participant_json(member) for member in members]},
        warnings,
    )
    lines = (
        _who_lines(members, you)
        if members
        else ["no participants yet; run: callboard join <handle>"]
    )
    emit(payload, lines, json_mode=args.json)
    return 0
