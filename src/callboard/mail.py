import sqlite3
from collections.abc import Sequence

from callboard.conversations import members, require_member, require_participants
from callboard.errors import CallboardError
from callboard.messages import insert_message, message, route_of_handle
from callboard.models import Attachment, Conversation, MemberRole, Message, Ping
from callboard.receipts import insert_receipts, ping_for
from callboard.store import write


def mail_level(*, urgent: bool) -> Ping:
    return "idle" if urgent else "hold"


def addressees(sender: str, to: Sequence[str], cc: Sequence[str]) -> dict[str, MemberRole]:
    roles: dict[str, MemberRole] = {handle: "cc" for handle in cc if handle != sender}
    roles.update({handle: "to" for handle in to if handle != sender})
    if not roles:
        raise CallboardError("mail needs a recipient other than you", code="usage")
    return roles


def _ring_all(conn: sqlite3.Connection, draft: Message, *, urgent: bool, attached: bool) -> None:
    insert_receipts(
        conn,
        draft,
        {
            handle: ping_for(mail_level(urgent=urgent), route_of_handle(conn, handle))
            for handle in members(conn, draft.conversation_id)
            if handle != draft.sender
        },
        attached=attached,
    )


def send_mail(
    conn: sqlite3.Connection,
    draft: Message,
    subject: str,
    roles: dict[str, MemberRole],
    attachments: Sequence[Attachment] = (),
    *,
    urgent: bool,
) -> Message:
    with write(conn):
        require_participants(conn, sorted(roles))
        conn.execute(
            "INSERT INTO conversations (id, kind, subject, created_by, created_at)"
            " VALUES (?, 'mail', ?, ?, ?)",
            (draft.conversation_id, subject, draft.sender, draft.created_at),
        )
        conn.executemany(
            "INSERT INTO members (conversation_id, handle, role, joined_at) VALUES (?, ?, ?, ?)",
            [
                (draft.conversation_id, handle, role, draft.created_at)
                for handle, role in {draft.sender: "from", **roles}.items()
            ],
        )
        insert_message(conn, draft, attachments)
        _ring_all(conn, draft, urgent=urgent, attached=bool(attachments))
    return draft


def require_mail_thread(conn: sqlite3.Connection, parent_id: str, sender: str) -> Conversation:
    parent = message(conn, parent_id)
    if parent is None:
        raise CallboardError(f"no message {parent_id}", code="message_not_found")
    thread = require_member(conn, parent.conversation_id, sender)
    if thread.kind != "mail":
        raise CallboardError(f"{parent_id} is not mail; reply with dm or group send", code="usage")
    return thread


def reply_mail(
    conn: sqlite3.Connection,
    draft: Message,
    attachments: Sequence[Attachment] = (),
    *,
    urgent: bool,
) -> Message:
    parent_id = draft.parent_id or ""
    with write(conn):
        thread = require_mail_thread(conn, parent_id, draft.sender)
        stored = Message(draft.id, thread.id, draft.sender, draft.body, parent_id, draft.created_at)
        insert_message(conn, stored, attachments)
        _ring_all(conn, stored, urgent=urgent, attached=bool(attachments))
    return stored
