import sqlite3
from collections.abc import Sequence

from callboard.attachments import insert_attachments
from callboard.conversations import ensure_dm, members, require_member, require_participants
from callboard.errors import CallboardError
from callboard.mentions import mentioned
from callboard.models import Attachment, Message
from callboard.receipts import insert_receipts, mark_read, ping_for, ring_level
from callboard.store import participant, write


def message_of(row: sqlite3.Row) -> Message:
    return Message(
        row["id"],
        row["conversation_id"],
        row["sender"],
        row["body"],
        row["parent_id"],
        row["created_at"],
    )


def message(conn: sqlite3.Connection, message_id: str) -> Message | None:
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    return None if row is None else message_of(row)


def require_message(conn: sqlite3.Connection, message_id: str, caller: str) -> Message:
    found = message(conn, message_id)
    if found is None:
        raise CallboardError(f"no message {message_id}", code="message_not_found")
    require_member(conn, found.conversation_id, caller)
    return found


def check_parent(conn: sqlite3.Connection, parent_id: str | None, conversation_id: str) -> None:
    if parent_id is None:
        return
    parent = message(conn, parent_id)
    if parent is None:
        raise CallboardError(f"--reply-to: no message {parent_id}", code="message_not_found")
    if parent.conversation_id != conversation_id:
        raise CallboardError(
            f"--reply-to: {parent_id} is in another conversation ({parent.conversation_id})",
            code="usage",
        )


def insert_message(
    conn: sqlite3.Connection, draft: Message, attachments: Sequence[Attachment] = ()
) -> None:
    conn.execute(
        "INSERT INTO messages (id, conversation_id, sender, body, parent_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            draft.id,
            draft.conversation_id,
            draft.sender,
            draft.body,
            draft.parent_id,
            draft.created_at,
        ),
    )
    insert_attachments(conn, draft.id, attachments)


def send_direct(
    conn: sqlite3.Connection,
    draft: Message,
    recipient: str,
    attachments: Sequence[Attachment] = (),
    *,
    rings: bool,
    now: bool,
) -> Message:
    with write(conn):
        require_participants(conn, [recipient])
        conversation_id = ensure_dm(conn, draft.sender, recipient, draft.created_at)
        stored = Message(
            draft.id, conversation_id, draft.sender, draft.body, draft.parent_id, draft.created_at
        )
        check_parent(conn, stored.parent_id, conversation_id)
        insert_message(conn, stored, attachments)
        level = ring_level(now=now) if rings else "none"
        insert_receipts(
            conn, stored.id, {recipient: ping_for(level, route_of_handle(conn, recipient))}
        )
    return stored


def route_of_handle(conn: sqlite3.Connection, handle: str) -> str | None:
    found = participant(conn, handle)
    return found.route if found else None


def send_group(
    conn: sqlite3.Connection,
    draft: Message,
    attachments: Sequence[Attachment] = (),
    *,
    now: bool,
) -> tuple[Message, tuple[str, ...]]:
    with write(conn):
        require_member(conn, draft.conversation_id, draft.sender)
        check_parent(conn, draft.parent_id, draft.conversation_id)
        handles = members(conn, draft.conversation_id)
        tagged = mentioned(draft.body, handles, draft.sender)
        insert_message(conn, draft, attachments)
        conn.executemany(
            "INSERT INTO mentions (message_id, handle) VALUES (?, ?)",
            [(draft.id, handle) for handle in tagged],
        )
        insert_receipts(
            conn,
            draft.id,
            {
                handle: ping_for(
                    ring_level(now=now) if handle in tagged else "none",
                    route_of_handle(conn, handle),
                )
                for handle in handles
                if handle != draft.sender
            },
        )
    return draft, tagged


def history(conn: sqlite3.Connection, conversation_id: str, limit: int) -> list[Message]:
    rows = conn.execute(
        "SELECT * FROM (SELECT * FROM messages WHERE conversation_id = ? ORDER BY seq DESC"
        " LIMIT ?) ORDER BY seq",
        (conversation_id, limit),
    )
    return [message_of(row) for row in rows]


def read_conversation(
    conn: sqlite3.Connection, conversation_id: str, caller: str, now: str, *, peek: bool
) -> list[Message]:
    with write(conn):
        require_member(conn, conversation_id, caller)
        rows = conn.execute(
            "SELECT m.* FROM messages m JOIN receipts r ON r.message_id = m.id"
            " WHERE m.conversation_id = ? AND r.recipient = ? AND r.read_at IS NULL"
            " ORDER BY m.seq",
            (conversation_id, caller),
        )
        unread = [message_of(row) for row in rows]
        if not peek:
            mark_read(conn, [item.id for item in unread], caller, now)
    return unread


def read_message(
    conn: sqlite3.Connection, message_id: str, caller: str, now: str, *, peek: bool
) -> Message:
    with write(conn):
        found = require_message(conn, message_id, caller)
        if not peek:
            mark_read(conn, [found.id], caller, now)
    return found
