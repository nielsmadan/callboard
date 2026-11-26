import os
import sqlite3
import stat
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from callboard.errors import CallboardError
from callboard.models import JoinOutcome, Participant, ParticipantKind

BUSY_TIMEOUT_SECONDS = 30.0
WAL_RETRY_SECONDS = 0.02

SCHEMA_V1: tuple[str, ...] = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE participants (
  handle TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('agent', 'human')),
  route TEXT,
  created_at TEXT NOT NULL
)""",
    """CREATE TABLE conversations (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('dm', 'group', 'mail', 'topic')),
  name TEXT,
  subject TEXT,
  project TEXT,
  created_by TEXT NOT NULL REFERENCES participants (handle),
  created_at TEXT NOT NULL
)""",
    """CREATE TABLE members (
  conversation_id TEXT NOT NULL REFERENCES conversations (id),
  handle TEXT NOT NULL REFERENCES participants (handle),
  role TEXT NOT NULL CHECK (role IN ('member', 'from', 'to', 'cc', 'subscriber')),
  joined_at TEXT NOT NULL,
  PRIMARY KEY (conversation_id, handle)
)""",
    """CREATE TABLE messages (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  conversation_id TEXT NOT NULL REFERENCES conversations (id),
  sender TEXT NOT NULL REFERENCES participants (handle),
  body TEXT NOT NULL,
  parent_id TEXT REFERENCES messages (id),
  created_at TEXT NOT NULL
)""",
    "CREATE INDEX messages_conversation ON messages (conversation_id, seq)",
    """CREATE TABLE receipts (
  message_id TEXT NOT NULL REFERENCES messages (id),
  recipient TEXT NOT NULL REFERENCES participants (handle),
  ping TEXT NOT NULL CHECK (ping IN ('none', 'hold', 'idle', 'now')),
  ping_state TEXT CHECK (ping_state IN ('pending', 'sending', 'sent', 'confirmed', 'read', 'failed')),
  bellhop_id TEXT,
  inline INTEGER NOT NULL DEFAULT 0,
  read_at TEXT,
  PRIMARY KEY (message_id, recipient)
)""",
    """CREATE TABLE mentions (
  message_id TEXT NOT NULL REFERENCES messages (id),
  handle TEXT NOT NULL REFERENCES participants (handle),
  PRIMARY KEY (message_id, handle)
)""",
    """CREATE TABLE attachments (
  id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL REFERENCES messages (id),
  sha256 TEXT NOT NULL,
  filename TEXT NOT NULL,
  media_type TEXT NOT NULL,
  size INTEGER NOT NULL
)""",
)

SCHEMA_V2: tuple[str, ...] = (
    "CREATE INDEX receipts_recipient ON receipts (recipient, read_at)",
    "CREATE INDEX attachments_message ON attachments (message_id)",
)

SCHEMA_V3: tuple[str, ...] = (
    "ALTER TABLE conversations ADD COLUMN open INTEGER NOT NULL DEFAULT 0",
)

MIGRATIONS: tuple[tuple[str, ...], ...] = (SCHEMA_V1, SCHEMA_V2, SCHEMA_V3)


class _Executes(Protocol):
    def execute(self, sql: str, /) -> object: ...


def enable_wal(
    conn: _Executes,
    *,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    deadline = now() + BUSY_TIMEOUT_SECONDS
    while True:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as error:
            busy = getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_BUSY
            if not busy or now() >= deadline:
                raise
        sleep(WAL_RETRY_SECONDS)


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None)
    try:
        enable_wal(conn)
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        conn.close()
        raise
    conn.row_factory = sqlite3.Row
    return conn


def connect_readonly(path: Path, busy_timeout: float = BUSY_TIMEOUT_SECONDS) -> sqlite3.Connection:
    conn = sqlite3.connect(
        path.absolute().as_uri() + "?mode=ro",
        uri=True,
        timeout=busy_timeout,
        isolation_level=None,
    )
    try:
        conn.execute("PRAGMA query_only = ON")
    except BaseException:
        conn.close()
        raise
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def write(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


@contextmanager
def read_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def schema_version(conn: sqlite3.Connection) -> int:
    meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
    ).fetchone()
    if meta is None:
        return 0
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row[0]) if row else 0


def _apply(conn: sqlite3.Connection, version: int, statements: Sequence[str]) -> None:
    with write(conn):
        if schema_version(conn) >= version:
            return
        for statement in statements:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (str(version),),
        )


def too_new(current: int, supported: int) -> CallboardError:
    return CallboardError(
        f"store schema version {current} is newer than this callboard supports"
        f" ({supported}); upgrade callboard",
        code="schema_too_new",
    )


def migrate(conn: sqlite3.Connection, migrations: Sequence[Sequence[str]] = MIGRATIONS) -> None:
    current = schema_version(conn)
    if current > len(migrations):
        raise too_new(current, len(migrations))
    for version, statements in enumerate(migrations, start=1):
        if current < version:
            _apply(conn, version, statements)


def _keep_private(path: Path) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        path.chmod(mode & 0o700)


def open_store(path: Path) -> sqlite3.Connection:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _keep_private(path.parent)
        os.close(os.open(path, os.O_CREAT | os.O_RDWR, 0o600))
        _keep_private(path)
        conn = connect(path)
    except (OSError, sqlite3.Error) as error:
        raise CallboardError(
            f"cannot open store {path}: {error}", code="store_unavailable"
        ) from error
    try:
        migrate(conn)
    except sqlite3.Error as error:
        conn.close()
        raise CallboardError(
            f"cannot migrate store {path}: {error}", code="store_unavailable"
        ) from error
    except CallboardError:
        conn.close()
        raise
    return conn


def open_readonly(
    path: Path, busy_timeout: float = BUSY_TIMEOUT_SECONDS
) -> sqlite3.Connection | None:
    try:
        if not path.exists():
            return None
        conn = connect_readonly(path, busy_timeout)
    except (OSError, sqlite3.Error) as error:
        raise CallboardError(
            f"cannot open store {path}: {error}", code="store_unavailable"
        ) from error
    try:
        current = schema_version(conn)
    except sqlite3.Error as error:
        conn.close()
        raise CallboardError(
            f"cannot read store {path}: {error}", code="store_unavailable"
        ) from error
    except BaseException:
        conn.close()
        raise
    if current > len(MIGRATIONS):
        conn.close()
        raise too_new(current, len(MIGRATIONS))
    if current == 0:
        conn.close()
        return None
    return conn


def _participant(row: sqlite3.Row) -> Participant:
    return Participant(row["handle"], row["kind"], row["route"], row["created_at"])


def participant(conn: sqlite3.Connection, handle: str) -> Participant | None:
    row = conn.execute("SELECT * FROM participants WHERE handle = ?", (handle,)).fetchone()
    return None if row is None else _participant(row)


def participants(conn: sqlite3.Connection) -> list[Participant]:
    return [_participant(row) for row in conn.execute("SELECT * FROM participants ORDER BY handle")]


def participants_with_route(conn: sqlite3.Connection, route: str) -> list[Participant]:
    rows = conn.execute("SELECT * FROM participants WHERE route = ? ORDER BY handle", (route,))
    return [_participant(row) for row in rows]


def taken(
    handle: str, kind: ParticipantKind, previous: Participant | None, session: "Session"
) -> str | None:
    if previous is None:
        return None
    if kind == "agent" and previous.kind == "human":
        return f"handle '{handle}' is taken by a human; pick another handle"
    if kind != "human" or previous.kind != "agent" or not previous.route:
        return None
    if session.live_routes is None:
        return (
            f"handle '{handle}' is taken by agent route {previous.route}, and bellhop cannot say"
            f" whether that route still resolves ({session.unknown}); pick another handle"
        )
    if previous.route in session.live_routes:
        return (
            f"handle '{handle}' is taken by agent route {previous.route}, which bellhop still"
            " knows; pick another handle"
        )
    return None


@dataclass(frozen=True)
class Session:
    routes: tuple[str, ...] = ()
    live_routes: frozenset[str] | None = None
    unknown: str = "not checked"


def join_participant(
    conn: sqlite3.Connection,
    handle: str,
    kind: ParticipantKind,
    route: str | None,
    now: str,
    session: Session = Session(),
) -> JoinOutcome:
    routes = dict.fromkeys([*([route] if route else []), *session.routes])
    with write(conn):
        previous = participant(conn, handle)
        refusal = taken(handle, kind, previous, session)
        if refusal:
            raise CallboardError(refusal, code="handle_taken")
        displaced = tuple(
            dict.fromkeys(
                other.handle
                for each in routes
                for other in participants_with_route(conn, each)
                if other.handle != handle
            )
        )
        conn.executemany(
            "UPDATE participants SET route = NULL WHERE handle = ?",
            [(other,) for other in displaced],
        )
        conn.execute(
            "INSERT INTO participants (handle, kind, route, created_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (handle) DO UPDATE SET kind = excluded.kind, route = excluded.route",
            (handle, kind, route, now),
        )
    created_at = previous.created_at if previous else now
    return JoinOutcome(Participant(handle, kind, route, created_at), previous, displaced)
