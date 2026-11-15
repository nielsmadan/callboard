import argparse
import os
import sqlite3
import stat
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from callboard.attachments import Pruned, prune
from callboard.bellhop_client import Caller, caller_for, executable
from callboard.cli.presentation import diagnostic, emit
from callboard.config import Config, load_config
from callboard.errors import CallboardError
from callboard.identity import live_routes
from callboard.jsonout import error_payload, ok_payload
from callboard.models import Participant, Runtime
from callboard.paths import attachments_dir, config_path, data_dir, store_path
from callboard.ping import ring_messages
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
        return Check("data_dir", "warn", f"{path} absent; created by the first callboard command")
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
        return Check("store", "warn", f"{path} absent; created by the first callboard command"), []
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


def check_config(path: Path) -> tuple[Config, Check]:
    try:
        config = load_config(path)
    except CallboardError as error:
        return Config(), Check("config", "fail", f"{error}; using the defaults")
    detail = str(path) if path.exists() else f"{path} absent; using the defaults"
    return config, Check("config", "ok", detail)


def check_bellhop(bell: Caller) -> Check:
    try:
        found = executable(bell.command, bell.env)
    except CallboardError as error:
        return Check("bellhop", "fail", str(error))
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


def _reping(runtime: Runtime, bell: Caller) -> tuple[int, list[str]]:
    with closing(open_store(store_path(runtime.env))) as conn:
        return ring_messages(conn, None, bell, runtime.clock())


def _prune(runtime: Runtime) -> Pruned:
    with closing(open_store(store_path(runtime.env))) as conn:
        return prune(conn, attachments_dir(runtime.env), _epoch(runtime.clock()))


def _pruned_json(pruned: Pruned) -> dict[str, object]:
    return {
        "blobs": pruned.blobs,
        "blob_bytes": pruned.blob_bytes,
        "temp_files": pruned.temp_files,
        "wal_truncated": pruned.wal_truncated,
    }


def _pruned_line(pruned: Pruned | None) -> str:
    if pruned is None:
        return "prune skipped; the store is not ok"
    wal = (
        "truncated the WAL"
        if pruned.wal_truncated
        else "could not truncate the WAL while another connection reads it"
    )
    return (
        f"pruned {pruned.blobs} unreferenced attachment files ({pruned.blob_bytes} bytes)"
        f" and {pruned.temp_files} temp files; {wal}"
    )


def doctor(args: argparse.Namespace, runtime: Runtime) -> int:
    env = runtime.env
    config, config_check = check_config(config_path(env))
    bell = caller_for(config.ping_command, env, runtime.deadline)
    store_check, members = check_store(store_path(env))
    bellhop_check = check_bellhop(bell)
    routes_check, unresolved = check_routes(members, lambda: live_routes(bell))
    checks = [
        check_data_dir(data_dir(env), os.getuid()),
        store_check,
        bellhop_check,
        routes_check,
        config_check,
    ]
    fields: dict[str, object] = {
        "checks": [
            {"name": check.name, "status": check.status, "detail": check.detail} for check in checks
        ],
        "unresolved": [{"handle": member.handle, "route": member.route} for member in unresolved],
    }
    lines = _lines(checks, unresolved)
    warnings: list[str] = []
    if args.reping:
        reping = _reping(runtime, bell) if store_check.status == "ok" else None
        fields["repinged"] = None if reping is None else reping[0]
        warnings = [] if reping is None else reping[1]
        lines.append(
            "reping skipped; the store is not ok"
            if reping is None
            else f"re-rang {reping[0]} receipts"
        )
        for warning in warnings:
            diagnostic(warning)
    if args.prune:
        pruned = _prune(runtime) if store_check.status == "ok" else None
        fields["pruned"] = None if pruned is None else _pruned_json(pruned)
        lines.append(_pruned_line(pruned))
    failed = [check.name for check in checks if check.status == "fail"]
    if not failed:
        emit(ok_payload(fields, warnings), lines, json_mode=args.json)
        return 0
    error = CallboardError(
        f"{len(failed)} check{'s' if len(failed) > 1 else ''} failed: {', '.join(failed)}",
        code="doctor_failed",
    )
    emit({**error_payload(error), "warnings": warnings, **fields}, lines, json_mode=args.json)
    if not args.json:
        diagnostic(str(error))
    return error.exit_code
