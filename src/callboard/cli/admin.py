import argparse
import os
import select
import sqlite3
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TextIO

from callboard.cli.presentation import emit
from callboard.cli.rendering import (
    admin_messages_json,
    admin_messages_lines,
    summary_json,
    summary_lines,
    watch_message_line,
    watch_snapshot_line,
)
from callboard.errors import CallboardError
from callboard.jsonout import ok_payload, render
from callboard.models import Batch, Page, Runtime, Snapshot
from callboard.observe import batch, page, snapshot, snapshot_with_fingerprint
from callboard.paths import attachments_dir, store_path
from callboard.store import open_readonly


def conversations(args: argparse.Namespace, runtime: Runtime) -> int:
    path = store_path(runtime.env)
    conn = open_readonly(path)
    if conn is None:
        found = Snapshot(0, ())
    else:
        with closing(conn):
            found = snapshot(conn)
    payload = ok_payload(
        {
            "store": str(path),
            "cursor": found.cursor,
            "conversations": [summary_json(summary) for summary in found.conversations],
        }
    )
    emit(payload, summary_lines(found.conversations), json_mode=args.json)
    return 0


def _older(conversation_id: str, found: Page) -> list[str]:
    if not found.more:
        return []
    command = f"callboard admin history {conversation_id} --before {found.messages[0].seq}"
    return [f"older messages: {command}"]


def history(args: argparse.Namespace, runtime: Runtime) -> int:
    path = store_path(runtime.env)
    conn = open_readonly(path)
    found = None
    if conn is not None:
        with closing(conn):
            found = page(conn, args.conversation_id, args.before, args.limit)
    if found is None:
        raise CallboardError(
            f"no conversation {args.conversation_id}", code="conversation_not_found"
        )
    directory = attachments_dir(runtime.env)
    payload = ok_payload(
        {
            "store": str(path),
            "conversation": summary_json(found.summary),
            "messages": admin_messages_json(found.messages, found.files, directory),
            "more": found.more,
        }
    )
    empty = f"no messages in {args.conversation_id}"
    if args.before is not None:
        empty += f" before {args.before}"
    lines = admin_messages_lines(found.messages, found.files, directory) or [empty]
    emit(payload, [*lines, *_older(args.conversation_id, found)], json_mode=args.json)
    return 0


WATCH_BUSY_TIMEOUT = 1.0
BUSY_GIVE_UP_SECONDS = 30.0
EMPTY = Snapshot(0, ())

type Identity = tuple[int, int]


@dataclass(frozen=True)
class Seams:
    wait: Callable[[float], bool]
    write: Callable[[str], None]
    stat: Callable[[Path], Identity | None]
    open_store: Callable[[Path], sqlite3.Connection | None]
    clock: Callable[[], float] = time.monotonic


@dataclass(frozen=True)
class Formats:
    snapshot: Callable[[Snapshot], Sequence[str]]
    batch: Callable[[Batch], Sequence[str]]
    snapshot_replaces_batch: bool = True


@dataclass
class _Feed:
    conn: sqlite3.Connection | None = None
    identity: Identity | None = None
    live: bool | None = None
    synced: bool = False
    cursor: int = 0
    fingerprint: str = ""
    data_version: int = -1
    stale: bool = True

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
        self.conn = None
        self.synced = False


def _data_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA data_version").fetchone()[0])


def _show(lines: Sequence[str], seams: Seams) -> None:
    for line in lines:
        seams.write(line)


def _resync(feed: _Feed, conn: sqlite3.Connection, formats: Formats, seams: Seams) -> None:
    version = _data_version(conn)
    current, found = snapshot_with_fingerprint(conn)
    _show(formats.snapshot(current), seams)
    feed.live, feed.synced, feed.stale = True, True, True
    feed.cursor, feed.fingerprint, feed.data_version = current.cursor, found, version


def _reopen(feed: _Feed, path: Path, seams: Seams) -> None:
    identity = seams.stat(path)
    if identity != feed.identity:
        feed.close()
        feed.identity = identity
    if feed.conn is None and identity is not None:
        feed.conn = seams.open_store(path)


def _tick(feed: _Feed, path: Path, formats: Formats, seams: Seams) -> bool:
    _reopen(feed, path, seams)
    conn = feed.conn
    if conn is None:
        if feed.live is not False:
            _show(formats.snapshot(EMPTY), seams)
            feed.live = False
        return False
    if not feed.synced:
        _resync(feed, conn, formats, seams)
        return False
    version = _data_version(conn)
    if not feed.stale and version == feed.data_version:
        return False
    found, current = batch(conn, feed.cursor)
    if current != feed.fingerprint and formats.snapshot_replaces_batch:
        feed.synced = False
        _resync(feed, conn, formats, seams)
        return False
    if current != feed.fingerprint:
        _show(formats.snapshot(replace(snapshot(conn), cursor=found.cursor)), seams)
    if found.messages:
        _show(formats.batch(found), seams)
    feed.cursor, feed.fingerprint = found.cursor, current
    feed.data_version, feed.stale = version, found.full
    return found.full


def _busy(error: BaseException) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    if isinstance(error, sqlite3.OperationalError) and code is not None:
        return code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    return (
        isinstance(error, CallboardError) and error.__cause__ is not None and _busy(error.__cause__)
    )


def _stuck(path: Path) -> CallboardError:
    return CallboardError(
        f"store {path} stayed busy for {BUSY_GIVE_UP_SECONDS:g} seconds", code="store_unavailable"
    )


def stream(path: Path, interval: float, formats: Formats, seams: Seams) -> int:
    feed = _Feed()
    busy_since: float | None = None
    try:
        while True:
            try:
                full = _tick(feed, path, formats, seams)
                busy_since = None
            except (sqlite3.OperationalError, CallboardError) as error:
                if not _busy(error):
                    raise
                busy_since = seams.clock() if busy_since is None else busy_since
                if seams.clock() - busy_since >= BUSY_GIVE_UP_SECONDS:
                    raise _stuck(path) from error
                full = False
            if not seams.wait(0 if full else interval):
                return 0
    finally:
        feed.close()


def sleep_wait(seconds: float) -> bool:
    time.sleep(seconds)
    return True


def stdin_wait(stdin: TextIO | None) -> Callable[[float], bool]:
    try:
        descriptor = None if stdin is None or stdin.isatty() else stdin.fileno()
    except (OSError, ValueError):
        descriptor = None
    if descriptor is None:
        return sleep_wait
    fd = descriptor

    def wait(seconds: float) -> bool:
        try:
            ready, _, _ = select.select([fd], [], [], seconds)
            return not ready or os.read(fd, 4096) != b""
        except OSError:
            return False

    return wait


def print_line(line: str) -> None:
    print(line, flush=True)


def file_identity(path: Path) -> Identity | None:
    try:
        found = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as error:
        raise CallboardError(
            f"cannot stat store {path}: {error}", code="store_unavailable"
        ) from error
    return (found.st_dev, found.st_ino)


def open_watched(path: Path) -> sqlite3.Connection | None:
    return open_readonly(path, WATCH_BUSY_TIMEOUT)


def json_formats(path: Path, directory: Path) -> Formats:
    def snapshot_lines(found: Snapshot) -> list[str]:
        fields = {
            "event": "snapshot",
            "store": str(path),
            "cursor": found.cursor,
            "conversations": [summary_json(summary) for summary in found.conversations],
        }
        return [render(ok_payload(fields))]

    def batch_lines(found: Batch) -> list[str]:
        fields = {
            "event": "messages",
            "cursor": found.cursor,
            "messages": admin_messages_json(found.messages, found.files, directory),
            "conversations": [summary_json(summary) for summary in found.touched],
        }
        return [render(ok_payload(fields))]

    return Formats(snapshot_lines, batch_lines)


def text_formats(path: Path) -> Formats:
    return Formats(
        lambda found: [watch_snapshot_line(path, found)],
        lambda found: [watch_message_line(item) for item in found.messages],
        snapshot_replaces_batch=False,
    )


def watch(args: argparse.Namespace, runtime: Runtime) -> int:
    path = store_path(runtime.env)
    formats = json_formats(path, attachments_dir(runtime.env)) if args.json else text_formats(path)
    seams = Seams(stdin_wait(sys.stdin), print_line, file_identity, open_watched)
    return stream(path, args.interval, formats, seams)


ACTIONS: Mapping[str, Callable[[argparse.Namespace, Runtime], int]] = {
    "conversations": conversations,
    "history": history,
    "watch": watch,
}


def admin(args: argparse.Namespace, runtime: Runtime) -> int:
    if args.as_handle is not None:
        raise CallboardError("admin commands take no --as", code="usage")
    return ACTIONS[args.action](args, runtime)
