import sqlite3
from collections.abc import Mapping, Sequence

from callboard.conversations import conversation_of
from callboard.models import InboxEntry, Message, Ping, Receipt


def ring_level(*, now: bool) -> Ping:
    return "now" if now else "idle"


def ping_for(level: Ping, route: str | None) -> Ping:
    return "none" if route is None else level


INLINE_LIMIT = 500


def is_inline(ping: Ping, body: str, *, attached: bool) -> bool:
    return ping in {"idle", "now"} and len(body) <= INLINE_LIMIT and not attached


def insert_receipts(
    conn: sqlite3.Connection, message: Message, pings: Mapping[str, Ping], *, attached: bool
) -> None:
    conn.executemany(
        "INSERT INTO receipts (message_id, recipient, ping, ping_state, inline)"
        " VALUES (?, ?, ?, ?, ?)",
        [
            (
                message.id,
                recipient,
                ping,
                None if ping == "none" else "pending",
                int(is_inline(ping, message.body, attached=attached)),
            )
            for recipient, ping in sorted(pings.items())
        ],
    )


def receipts(conn: sqlite3.Connection, message_id: str) -> list[Receipt]:
    rows = conn.execute(
        "SELECT * FROM receipts WHERE message_id = ? ORDER BY recipient", (message_id,)
    )
    return [
        Receipt(
            row["message_id"],
            row["recipient"],
            row["ping"],
            row["ping_state"],
            row["bellhop_id"],
            bool(row["inline"]),
            row["read_at"],
        )
        for row in rows
    ]


def mark_read(
    conn: sqlite3.Connection, message_ids: Sequence[str], recipient: str, now: str
) -> None:
    conn.executemany(
        "UPDATE receipts SET read_at = ? WHERE message_id = ? AND recipient = ?"
        " AND read_at IS NULL",
        [(now, message_id, recipient) for message_id in message_ids],
    )


def inbox(conn: sqlite3.Connection, recipient: str) -> list[InboxEntry]:
    rows = conn.execute(
        """SELECT c.*, count(*) AS unread,
  sum(EXISTS (SELECT 1 FROM mentions x WHERE x.message_id = m.id AND x.handle = :me)) AS mentioned,
  max(m.seq) AS latest,
  m.sender AS latest_sender
FROM receipts r
JOIN messages m ON m.id = r.message_id
JOIN conversations c ON c.id = m.conversation_id
JOIN members mb ON mb.conversation_id = c.id AND mb.handle = :me
WHERE r.recipient = :me AND r.read_at IS NULL
GROUP BY c.id
ORDER BY mentioned > 0 DESC, latest DESC""",
        {"me": recipient},
    )
    return [
        InboxEntry(conversation_of(row), row["unread"], row["mentioned"], row["latest_sender"])
        for row in rows
    ]
