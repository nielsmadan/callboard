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
BLOB_NAME = re.compile(r"[0-9a-f]{64}")
PRUNE_GRACE_SECONDS = 3600.0


@dataclass(frozen=True)
class Blob:
    sha256: str
    size: int


@dataclass(frozen=True)
class Pruned:
    blobs: int
    blob_bytes: int
    temp_files: int


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
        target = directory / digest.hexdigest()
        if target.exists():
            os.unlink(temp)
            os.utime(target)
        else:
            os.rename(temp, target)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temp)
        raise
    return Blob(digest.hexdigest(), size)


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


def _stale(path: Path, now: float) -> bool:
    try:
        return now - path.stat().st_mtime > PRUNE_GRACE_SECONDS
    except FileNotFoundError:
        return False


def prune(conn: sqlite3.Connection, directory: Path, now: float) -> Pruned:
    referenced = {row[0] for row in conn.execute("SELECT DISTINCT sha256 FROM attachments")}
    entries = sorted(directory.iterdir()) if directory.is_dir() else []
    blobs = [
        entry
        for entry in entries
        if BLOB_NAME.fullmatch(entry.name) and entry.name not in referenced and _stale(entry, now)
    ]
    temps = [
        entry for entry in entries if entry.name.startswith(TEMP_PREFIX) and _stale(entry, now)
    ]
    blob_bytes = sum(entry.stat().st_size for entry in blobs)
    for entry in [*blobs, *temps]:
        with suppress(FileNotFoundError):
            entry.unlink()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return Pruned(len(blobs), blob_bytes, len(temps))
