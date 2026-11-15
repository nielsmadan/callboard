import hashlib
import json
import mimetypes
import os
import re
import sqlite3
import tempfile
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from callboard.errors import CallboardError
from callboard.models import Attachment

CHUNK_BYTES = 1024 * 1024
TEMP_PREFIX = ".tmp-"
PRUNE_PREFIX = f"{TEMP_PREFIX}prune-"
BLOB_NAME = re.compile(r"[0-9a-f]{64}")
PRUNE_GRACE_SECONDS = 3600.0
BLOB_MODE = 0o400


@dataclass(frozen=True)
class Blob:
    sha256: str
    size: int


@dataclass(frozen=True)
class Pruned:
    blobs: int
    blob_bytes: int
    temp_files: int
    wal_truncated: bool


COMPRESSED = {"gzip": "application/gzip", "bzip2": "application/x-bzip2", "xz": "application/x-xz"}


def media_type(filename: str) -> str:
    guessed, encoding = mimetypes.guess_type(filename)
    if encoding is not None:
        return COMPRESSED.get(encoding, "application/octet-stream")
    return guessed or "application/octet-stream"


def _too_large(label: str, limit: int) -> CallboardError:
    return CallboardError(f"--attach: {label} is larger than {limit} bytes", code="usage")


def store_blob(source: BinaryIO, directory: Path, limit: int, label: str) -> Blob:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=directory, prefix=TEMP_PREFIX)
    try:
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(handle, "wb") as out:
            while chunk := source.read(CHUNK_BYTES):
                size += len(chunk)
                if size > limit:
                    raise _too_large(label, limit)
                digest.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        _keep(temp, directory / digest.hexdigest())
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temp)
        raise
    return Blob(digest.hexdigest(), size)


def _keep(temp: str, target: Path) -> None:
    os.chmod(temp, BLOB_MODE)
    os.replace(temp, target)


def _checked(path: Path, limit: int) -> Path:
    try:
        info = path.stat()
    except OSError as error:
        raise CallboardError(
            f"--attach: cannot read {path}: {error.strerror}", code="usage"
        ) from error
    if not path.is_file():
        raise CallboardError(f"--attach: {path} is not a regular file", code="usage")
    if info.st_size > limit:
        raise _too_large(str(path), limit)
    return path


def copy_attachments(
    sources: Sequence[str], directory: Path, limit: int, token: Callable[[], str]
) -> list[Attachment]:
    paths = [_checked(Path(source), limit) for source in sources]
    copied = []
    for path in paths:
        try:
            with path.open("rb") as source:
                blob = store_blob(source, directory, limit, str(path))
        except OSError as error:
            raise CallboardError(
                f"--attach: cannot copy {path}: {error.strerror or error}", code="usage"
            ) from error
        copied.append(
            Attachment(f"at_{token()}", blob.sha256, path.name, media_type(path.name), blob.size)
        )
    return copied


def insert_attachments(
    conn: sqlite3.Connection, message_id: str, attachments: Sequence[Attachment]
) -> None:
    conn.executemany(
        "INSERT INTO attachments (id, message_id, sha256, filename, media_type, size)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [
            (item.id, message_id, item.sha256, item.filename, item.media_type, item.size)
            for item in attachments
        ],
    )


def _attachment_of(row: sqlite3.Row) -> Attachment:
    return Attachment(row["id"], row["sha256"], row["filename"], row["media_type"], row["size"])


def attachments_of(
    conn: sqlite3.Connection, message_ids: Sequence[str]
) -> dict[str, list[Attachment]]:
    found: dict[str, list[Attachment]] = {message_id: [] for message_id in message_ids}
    rows = conn.execute(
        "SELECT * FROM attachments WHERE message_id IN (SELECT value FROM json_each(?))"
        " ORDER BY rowid",
        (json.dumps(list(message_ids)),),
    )
    for row in rows:
        found[row["message_id"]].append(_attachment_of(row))
    return found


def attachment(conn: sqlite3.Connection, attachment_id: str) -> tuple[Attachment, str] | None:
    row = conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    return None if row is None else (_attachment_of(row), row["message_id"])


def _age(path: Path, now: float) -> tuple[float, int] | None:
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    return now - info.st_mtime, info.st_size


def _remove_if_stale(path: Path, now: float) -> int | None:
    found = _age(path, now)
    if found is None or found[0] <= PRUNE_GRACE_SECONDS:
        return None
    with suppress(FileNotFoundError):
        path.unlink()
    return found[1]


def _remove_orphan(path: Path, now: float) -> int | None:
    found = _age(path, now)
    if found is None or found[0] <= PRUNE_GRACE_SECONDS:
        return None
    held = path.with_name(f"{PRUNE_PREFIX}{path.name}")
    try:
        os.rename(path, held)
    except FileNotFoundError:
        return None
    try:
        size = _remove_if_stale(held, now)
    except BaseException:
        _put_back(held, path)
        raise
    if size is None:
        _put_back(held, path)
    return size


def _put_back(held: Path, path: Path) -> None:
    with suppress(FileNotFoundError):
        os.rename(held, path)


def _restore_interrupted(directory: Path) -> None:
    for held in sorted(directory.glob(f"{PRUNE_PREFIX}*")):
        name = held.name.removeprefix(PRUNE_PREFIX)
        if BLOB_NAME.fullmatch(name) and not (directory / name).exists():
            _put_back(held, directory / name)


def prune(conn: sqlite3.Connection, directory: Path, now: float) -> Pruned:
    if directory.is_dir():
        _restore_interrupted(directory)
    referenced = {row[0] for row in conn.execute("SELECT DISTINCT sha256 FROM attachments")}
    entries = sorted(directory.iterdir()) if directory.is_dir() else []
    orphans = [
        entry
        for entry in entries
        if BLOB_NAME.fullmatch(entry.name) and entry.name not in referenced
    ]
    temps = [entry for entry in entries if entry.name.startswith(TEMP_PREFIX)]
    removed = [size for entry in orphans if (size := _remove_orphan(entry, now)) is not None]
    stale_temps = [entry for entry in temps if _remove_if_stale(entry, now) is not None]
    return Pruned(len(removed), sum(removed), len(stale_temps), truncate_wal(conn))


def truncate_wal(conn: sqlite3.Connection) -> bool:
    previous = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    conn.execute("PRAGMA busy_timeout = 1000")
    try:
        busy = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
    finally:
        conn.execute(f"PRAGMA busy_timeout = {int(previous)}")
    return int(busy) == 0
