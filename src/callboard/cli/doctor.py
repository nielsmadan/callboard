import argparse
import os
import shutil
import sqlite3
import stat
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from callboard.attachments import Pruned, prune
from callboard.cli.presentation import diagnostic, emit
from callboard.errors import CallboardError
from callboard.identity import live_routes
from callboard.jsonout import error_payload, ok_payload
from callboard.models import Participant, Runtime
from callboard.paths import attachments_dir, data_dir, store_path
from callboard.store import (
    MIGRATIONS,
    connect_readonly,
    open_store,
    participants,
    schema_version,
)

type CheckStatus = Literal["ok", "warn", "fail"]


@dataclass(frozen=True)
class Check:
    name: str
    status: CheckStatus
    detail: str


ABSENT = (FileNotFoundError, NotADirectoryError)


def check_data_dir(path: Path, uid: int) -> Check:
    try:
        info = path.stat()
    except ABSENT:
        return Check("data_dir", "warn", f"{path} absent; created by the first callboard join")
    except OSError as error:
        return Check("data_dir", "fail", f"cannot access {path}: {error.strerror}")
    if not stat.S_ISDIR(info.st_mode):
        return Check("data_dir", "fail", f"{path} is not a directory")
    owner = info.st_uid
    if owner != uid:
        return Check("data_dir", "fail", f"{path} is owned by uid {owner}, not {uid}")
    if not os.access(path, os.W_OK | os.X_OK):
        return Check("data_dir", "fail", f"{path} is not writable")
    return Check("data_dir", "ok", str(path))


def check_store(path: Path) -> tuple[Check, list[Participant]]:
    try:
        path.stat()
    except ABSENT:
        return Check("store", "warn", f"{path} absent; created by the first callboard join"), []
    except OSError as error:
        return Check("store", "fail", f"cannot access {path}: {error.strerror}"), []
    current = len(MIGRATIONS)
    try:
        with closing(connect_readonly(path)) as conn:
            version = schema_version(conn)
            members = participants(conn) if version == current else []
    except sqlite3.Error as error:
        return Check("store", "fail", f"cannot read {path}: {error}"), []
    if version > current:
        return Check(
            "store", "fail", f"schema version {version} is newer than this callboard ({current})"
        ), []
    if version < current:
        return Check(
            "store", "warn", f"schema version {version}; migrates to {current} on next use"
        ), []
    return Check("store", "ok", f"schema version {version}, {len(members)} participants"), members


def check_bellhop(env: Mapping[str, str]) -> Check:
    found = shutil.which("bellhop", path=env.get("PATH", os.defpath))
    if found is None:
        return Check("bellhop", "fail", "bellhop not found on PATH")
    return Check("bellhop", "ok", found)


def check_routes(
    members: Sequence[Participant], live: Callable[[], frozenset[str]]
) -> tuple[Check, list[Participant]]:
    routed = [member for member in members if member.kind == "agent" and member.route]
    if not routed:
        return Check("routes", "ok", "no agent routes to check"), []
    try:
        resolvable = live()
    except CallboardError as error:
        return Check("routes", "warn", f"cannot check routes; {error}"), []
    unresolved = [member for member in routed if member.route not in resolvable]
    if unresolved:
        detail = f"{len(unresolved)} of {len(routed)} routes no longer resolve"
        return Check("routes", "warn", detail), unresolved
    return Check("routes", "ok", f"{len(routed)} routes resolve"), []


def _lines(checks: Sequence[Check], unresolved: Sequence[Participant]) -> list[str]:
    return [f"{check.status:<4}  {check.name:<8}  {check.detail}" for check in checks] + [
        f"unresolved: {member.handle} (route {member.route})" for member in unresolved
    ]


def _epoch(stamp: str) -> float:
    return datetime.fromisoformat(stamp).timestamp()


def _prune(runtime: Runtime) -> Pruned:
    with closing(open_store(store_path(runtime.env))) as conn:
        return prune(conn, attachments_dir(runtime.env), _epoch(runtime.clock()))


def _pruned_json(pruned: Pruned) -> dict[str, object]:
    return {
        "blobs": pruned.blobs,
        "blob_bytes": pruned.blob_bytes,
        "temp_files": pruned.temp_files,
        "wal_truncated": True,
    }


def _pruned_line(pruned: Pruned | None) -> str:
    if pruned is None:
        return "prune skipped; the store is not ok"
    return (
        f"pruned {pruned.blobs} unreferenced attachment files ({pruned.blob_bytes} bytes)"
        f" and {pruned.temp_files} temp files; truncated the WAL"
    )


def doctor(args: argparse.Namespace, runtime: Runtime) -> int:
    env = runtime.env
    store_check, members = check_store(store_path(env))
    bellhop_check = check_bellhop(env)
    routes_check, unresolved = check_routes(members, lambda: live_routes(env))
    checks = [check_data_dir(data_dir(env), os.getuid()), store_check, bellhop_check, routes_check]
    fields: dict[str, object] = {
        "checks": [
            {"name": check.name, "status": check.status, "detail": check.detail} for check in checks
        ],
        "unresolved": [{"handle": member.handle, "route": member.route} for member in unresolved],
    }
    lines = _lines(checks, unresolved)
    if args.prune:
        pruned = _prune(runtime) if store_check.status == "ok" else None
        fields["pruned"] = None if pruned is None else _pruned_json(pruned)
        lines.append(_pruned_line(pruned))
    failed = [check.name for check in checks if check.status == "fail"]
    if not failed:
        emit(ok_payload(fields), lines, json_mode=args.json)
        return 0
    error = CallboardError(
        f"{len(failed)} check{'s' if len(failed) > 1 else ''} failed: {', '.join(failed)}",
        code="doctor_failed",
    )
    emit({**error_payload(error), **fields}, lines, json_mode=args.json)
    if not args.json:
        diagnostic(str(error))
    return error.exit_code
