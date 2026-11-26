import sqlite3
from collections.abc import Sequence

from callboard.errors import CallboardError
from callboard.models import Conversation, NewGroup
from callboard.refs import dm_id, ref_of
from callboard.store import participant, write


def conversation_of(row: sqlite3.Row) -> Conversation:
    return Conversation(
        row["id"],
        row["kind"],
        row["name"],
        row["subject"],
        row["project"],
        row["created_by"],
        row["created_at"],
    )


def conversation(conn: sqlite3.Connection, conversation_id: str) -> Conversation | None:
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    return None if row is None else conversation_of(row)


def members(conn: sqlite3.Connection, conversation_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT handle FROM members WHERE conversation_id = ? ORDER BY handle", (conversation_id,)
    )
    return [row["handle"] for row in rows]


def require_member(conn: sqlite3.Connection, conversation_id: str, handle: str) -> Conversation:
    found = conversation(conn, conversation_id)
    if found is None:
        raise CallboardError(
            f"no conversation {ref_of(conversation_id, handle)}", code="conversation_not_found"
        )
    if handle not in members(conn, conversation_id):
        raise CallboardError(
            f"'{handle}' is not a member of {ref_of(conversation_id, handle)}", code="not_a_member"
        )
    return found


def require_participants(conn: sqlite3.Connection, handles: Sequence[str]) -> None:
    unknown = [handle for handle in handles if participant(conn, handle) is None]
    if unknown:
        raise CallboardError(
            f"no participant {', '.join(repr(handle) for handle in unknown)}",
            code="unknown_handle",
        )


def ensure_dm(conn: sqlite3.Connection, sender: str, recipient: str, now: str) -> str:
    conversation_id = dm_id(sender, recipient)
    conn.execute(
        "INSERT INTO conversations (id, kind, created_by, created_at) VALUES (?, 'dm', ?, ?)"
        " ON CONFLICT (id) DO NOTHING",
        (conversation_id, sender, now),
    )
    conn.executemany(
        "INSERT INTO members (conversation_id, handle, role, joined_at) VALUES (?, ?, 'member', ?)"
        " ON CONFLICT (conversation_id, handle) DO NOTHING",
        [(conversation_id, handle, now) for handle in sorted({sender, recipient})],
    )
    return conversation_id


def create_group(
    conn: sqlite3.Connection, group: NewGroup, creator: str, handles: Sequence[str], now: str
) -> Conversation:
    conversation_id = f"group:{group.name}"
    everyone = sorted({creator, *handles})
    with write(conn):
        require_participants(conn, everyone)
        if conversation(conn, conversation_id) is not None:
            raise CallboardError(f"{conversation_id} already exists", code="group_exists")
        conn.execute(
            "INSERT INTO conversations (id, kind, name, project, created_by, created_at, open)"
            " VALUES (?, 'group', ?, ?, ?, ?, ?)",
            (conversation_id, group.name, group.project, creator, now, int(group.joinable)),
        )
        conn.executemany(
            "INSERT INTO members (conversation_id, handle, role, joined_at)"
            " VALUES (?, ?, 'member', ?)",
            [(conversation_id, handle, now) for handle in everyone],
        )
    return Conversation(conversation_id, "group", group.name, None, group.project, creator, now)


def add_member(conn: sqlite3.Connection, name: str, caller: str, handle: str, now: str) -> bool:
    conversation_id = f"group:{name}"
    with write(conn):
        require_member(conn, conversation_id, caller)
        require_participants(conn, [handle])
        cursor = conn.execute(
            "INSERT INTO members (conversation_id, handle, role, joined_at)"
            " VALUES (?, ?, 'member', ?) ON CONFLICT (conversation_id, handle) DO NOTHING",
            (conversation_id, handle, now),
        )
    return cursor.rowcount == 1


def join_group(conn: sqlite3.Connection, name: str, caller: str, now: str) -> bool:
    conversation_id = f"group:{name}"
    with write(conn):
        row = conn.execute(
            "SELECT open FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if row is None:
            raise CallboardError(
                f"no conversation {conversation_id}", code="conversation_not_found"
            )
        if caller in members(conn, conversation_id):
            return False
        if not row["open"]:
            raise CallboardError(
                f"{conversation_id} is not open; ask a member to run:"
                f" callboard group add {name} {caller}",
                code="group_closed",
            )
        conn.execute(
            "INSERT INTO members (conversation_id, handle, role, joined_at)"
            " VALUES (?, ?, 'member', ?)",
            (conversation_id, caller, now),
        )
    return True


def remove_member(conn: sqlite3.Connection, name: str, caller: str, handle: str) -> bool:
    conversation_id = f"group:{name}"
    with write(conn):
        require_member(conn, conversation_id, caller)
        cursor = conn.execute(
            "DELETE FROM members WHERE conversation_id = ? AND handle = ?",
            (conversation_id, handle),
        )
        if cursor.rowcount == 0:
            raise CallboardError(
                f"'{handle}' is not a member of {conversation_id}", code="not_a_member"
            )
        emptied = not members(conn, conversation_id)
        if emptied:
            _drop(conn, conversation_id)
    return emptied


DROP_CONVERSATION = (
    (
        "DELETE FROM mentions WHERE message_id IN"
        " (SELECT id FROM messages WHERE conversation_id = ?)"
    ),
    (
        "DELETE FROM receipts WHERE message_id IN"
        " (SELECT id FROM messages WHERE conversation_id = ?)"
    ),
    (
        "DELETE FROM attachments WHERE message_id IN"
        " (SELECT id FROM messages WHERE conversation_id = ?)"
    ),
    "DELETE FROM messages WHERE conversation_id = ?",
    "DELETE FROM conversations WHERE id = ?",
)


def _drop(conn: sqlite3.Connection, conversation_id: str) -> None:
    for statement in DROP_CONVERSATION:
        conn.execute(statement, (conversation_id,))
