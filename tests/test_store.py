import sqlite3
import stat
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from callboard.errors import CallboardError
from callboard.store import (
    BUSY_TIMEOUT_SECONDS,
    MIGRATIONS,
    WAL_RETRY_SECONDS,
    connect,
    enable_wal,
    migrate,
    open_store,
    schema_version,
    write,
)

TABLES = [
    "attachments",
    "conversations",
    "members",
    "mentions",
    "messages",
    "meta",
    "participants",
    "receipts",
]


def _tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        " ORDER BY name"
    )
    return [row[0] for row in rows]


def test_open_creates_a_private_store_at_the_current_schema(tmp_path: Path) -> None:
    path = tmp_path / "data" / "callboard.sqlite"
    conn = open_store(path)
    try:
        assert schema_version(conn) == len(MIGRATIONS)
        assert _tables(conn) == TABLES
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
    finally:
        conn.close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_reopening_keeps_rows_and_version(tmp_path: Path) -> None:
    path = tmp_path / "callboard.sqlite"
    conn = open_store(path)
    conn.execute(
        "INSERT INTO participants (handle, kind, route, created_at) VALUES ('a', 'human', NULL, 't')"
    )
    conn.close()
    conn = open_store(path)
    try:
        assert schema_version(conn) == len(MIGRATIONS)
        assert [row["handle"] for row in conn.execute("SELECT handle FROM participants")] == ["a"]
    finally:
        conn.close()


def test_a_later_migration_is_applied_forward_once(tmp_path: Path) -> None:
    conn = open_store(tmp_path / "callboard.sqlite")
    later = (*MIGRATIONS, ("ALTER TABLE participants ADD COLUMN note TEXT",))
    try:
        migrate(conn, later)
        migrate(conn, later)
        assert schema_version(conn) == len(MIGRATIONS) + 1
        columns = [row[1] for row in conn.execute("PRAGMA table_info(participants)")]
        assert columns[-1] == "note"
    finally:
        conn.close()


def test_a_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "callboard.sqlite"
    conn = open_store(path)
    conn.execute("UPDATE meta SET value = '7' WHERE key = 'schema_version'")
    conn.close()
    with pytest.raises(CallboardError) as caught:
        open_store(path)
    assert (caught.value.code, caught.value.exit_code, str(caught.value)) == (
        "schema_too_new",
        1,
        "store schema version 7 is newer than this callboard supports (2); upgrade callboard",
    )


def test_an_unwritable_directory_makes_the_store_unavailable(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    with pytest.raises(CallboardError) as caught:
        open_store(locked / "callboard.sqlite")
    assert (caught.value.code, caught.value.exit_code) == ("store_unavailable", 1)
    assert str(caught.value).startswith(f"cannot open store {locked / 'callboard.sqlite'}: ")


def test_a_corrupt_file_makes_the_store_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "callboard.sqlite"
    path.write_bytes(b"not a database, just some bytes that are long enough" * 20)
    with pytest.raises(CallboardError) as caught:
        open_store(path)
    assert caught.value.code == "store_unavailable"


def test_a_failed_write_rolls_back(tmp_path: Path) -> None:
    conn = open_store(tmp_path / "callboard.sqlite")
    try:
        with pytest.raises(sqlite3.IntegrityError), write(conn):
            conn.execute(
                "INSERT INTO participants (handle, kind, route, created_at)"
                " VALUES ('a', 'human', NULL, 't')"
            )
            conn.execute(
                "INSERT INTO participants (handle, kind, route, created_at)"
                " VALUES ('a', 'human', NULL, 't')"
            )
        assert conn.execute("SELECT count(*) FROM participants").fetchone()[0] == 0
        assert not conn.in_transaction
    finally:
        conn.close()


def test_an_existing_directory_and_file_are_made_private(tmp_path: Path) -> None:
    directory = tmp_path / "data"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    path = directory / "callboard.sqlite"
    path.touch(mode=0o644)
    path.chmod(0o644)
    open_store(path).close()
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_failed_commit_rolls_back(tmp_path: Path) -> None:
    conn = open_store(tmp_path / "callboard.sqlite")
    try:
        with pytest.raises(sqlite3.IntegrityError), write(conn):
            conn.execute("PRAGMA defer_foreign_keys = ON")
            conn.execute(
                "INSERT INTO conversations (id, kind, created_by, created_at)"
                " VALUES ('dm:a:b', 'dm', 'nobody', 't')"
            )
        assert not conn.in_transaction
        assert conn.execute("SELECT count(*) FROM conversations").fetchone()[0] == 0
    finally:
        conn.close()


def test_a_migration_applied_meanwhile_by_another_process_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "callboard.sqlite"
    later = (*MIGRATIONS, ("ALTER TABLE participants ADD COLUMN note TEXT",))
    slow = open_store(path)
    fast = open_store(path)

    class Racing(tuple[tuple[str, ...], ...]):
        def __iter__(self) -> Iterator[tuple[str, ...]]:
            migrate(fast, later)
            return super().__iter__()

    try:
        migrate(slow, Racing(later))
        assert schema_version(slow) == len(MIGRATIONS) + 1
        columns = [row[1] for row in slow.execute("PRAGMA table_info(participants)")]
        assert columns.count("note") == 1
    finally:
        slow.close()
        fast.close()


def _busy() -> sqlite3.OperationalError:
    error = sqlite3.OperationalError("database is locked")
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    return error


class _Flaky:
    def __init__(self, failures: list[sqlite3.OperationalError]) -> None:
        self.failures = failures
        self.calls: list[str] = []

    def execute(self, sql: str, /) -> object:
        self.calls.append(sql)
        if self.failures:
            raise self.failures.pop(0)
        return None


def test_switching_to_wal_retries_while_another_opener_holds_the_lock() -> None:
    conn = _Flaky([_busy(), _busy()])
    naps: list[float] = []
    enable_wal(conn, now=lambda: 0.0, sleep=naps.append)
    assert conn.calls == ["PRAGMA journal_mode = WAL"] * 3
    assert naps == [WAL_RETRY_SECONDS, WAL_RETRY_SECONDS]


def test_switching_to_wal_gives_up_at_the_busy_deadline() -> None:
    clock = iter([0.0, BUSY_TIMEOUT_SECONDS])
    with pytest.raises(sqlite3.OperationalError):
        enable_wal(_Flaky([_busy()]), now=lambda: next(clock), sleep=lambda _: None)


def test_switching_to_wal_does_not_retry_other_errors() -> None:
    conn = _Flaky([sqlite3.OperationalError("disk I/O error")])
    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        enable_wal(conn, now=lambda: 0.0, sleep=lambda _: None)
    assert len(conn.calls) == 1


def test_a_version_1_store_gains_the_lookup_indexes(tmp_path: Path) -> None:
    path = tmp_path / "callboard.sqlite"
    with closing(connect(path)) as conn:
        migrate(conn, MIGRATIONS[:1])
    with closing(open_store(path)) as conn:
        indexes = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }
        assert schema_version(conn) == len(MIGRATIONS)
    assert {"receipts_recipient", "attachments_message"} <= indexes
