import hashlib
import json
import sqlite3
from collections.abc import Sequence

from callboard.attachments import attachments_of
from callboard.conversations import conversation, conversation_of
from callboard.messages import message_of
from callboard.models import (
    Batch,
    Conversation,
    ConversationSummary,
    Page,
    Sequenced,
    Snapshot,
)
from callboard.store import read_transaction

MAX_BATCH = 200
MAX_BATCH_BODY_CHARS = 4_000_000


def _cursor(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'messages'").fetchone()
    return int(row[0]) if row else 0


def _sequenced(row: sqlite3.Row) -> Sequenced:
    return Sequenced(int(row["seq"]), message_of(row))


def _summaries(
    conn: sqlite3.Connection, conversations: Sequence[Conversation], upto: int | None = None
) -> list[ConversationSummary]:
    ids = json.dumps([item.id for item in conversations])
    members: dict[str, list[str]] = {item.id: [] for item in conversations}
    for row in conn.execute(
        "SELECT conversation_id, handle FROM members"
        " WHERE conversation_id IN (SELECT value FROM json_each(?)) ORDER BY handle",
        (ids,),
    ):
        members[row[0]].append(row[1])
    stats = {
        row[0]: (int(row[1]), int(row[2]), int(row[3]))
        for row in conn.execute(
            "SELECT conversation_id, count(*), min(seq), max(seq) FROM messages"
            " WHERE conversation_id IN (SELECT value FROM json_each(?))"
            " AND (? IS NULL OR seq <= ?) GROUP BY conversation_id",
            (ids, upto, upto),
        )
    }
    lasts = {
        row["conversation_id"]: _sequenced(row)
        for row in conn.execute(
            "SELECT * FROM messages WHERE seq IN (SELECT value FROM json_each(?))",
            (json.dumps([last for _, _, last in stats.values()]),),
        )
    }
    return [
        ConversationSummary(
            item,
            tuple(members[item.id]),
            stats[item.id][0] if item.id in stats else 0,
            stats[item.id][1] if item.id in stats else None,
            lasts.get(item.id),
        )
        for item in conversations
    ]


def _recency(summary: ConversationSummary) -> tuple[int, int, str]:
    if summary.last is None:
        return (1, 0, summary.conversation.id)
    return (0, -summary.last.seq, summary.conversation.id)


def _snapshot(conn: sqlite3.Connection) -> Snapshot:
    cursor = _cursor(conn)
    conversations = [conversation_of(row) for row in conn.execute("SELECT * FROM conversations")]
    summaries = _summaries(conn, conversations)
    return Snapshot(cursor, tuple(sorted(summaries, key=_recency)))


def snapshot(conn: sqlite3.Connection) -> Snapshot:
    with read_transaction(conn):
        return _snapshot(conn)


def snapshot_with_fingerprint(conn: sqlite3.Connection) -> tuple[Snapshot, str]:
    with read_transaction(conn):
        return _snapshot(conn), _fingerprint(conn)


def page(
    conn: sqlite3.Connection, conversation_id: str, before: int | None, limit: int
) -> Page | None:
    with read_transaction(conn):
        found = conversation(conn, conversation_id)
        if found is None:
            return None
        summary = _summaries(conn, [found])[0]
        rows = conn.execute(
            "SELECT * FROM (SELECT * FROM messages WHERE conversation_id = ?"
            " AND (? IS NULL OR seq < ?) ORDER BY seq DESC LIMIT ?) ORDER BY seq",
            (conversation_id, before, before, limit),
        )
        items = tuple(_sequenced(row) for row in rows)
        more = bool(items) and bool(
            conn.execute(
                "SELECT EXISTS (SELECT 1 FROM messages WHERE conversation_id = ? AND seq < ?)",
                (conversation_id, items[0].seq),
            ).fetchone()[0]
        )
        files = attachments_of(conn, [item.message.id for item in items])
    return Page(summary, items, files, more)


def _fingerprint(conn: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    conversations = conn.execute("SELECT id, created_at FROM conversations ORDER BY id")
    members = conn.execute(
        "SELECT conversation_id, handle FROM members ORDER BY conversation_id, handle"
    )
    digest.update(json.dumps([[*row] for row in conversations]).encode())
    digest.update(json.dumps([[*row] for row in members]).encode())
    return digest.hexdigest()


def fingerprint(conn: sqlite3.Connection) -> str:
    with read_transaction(conn):
        return _fingerprint(conn)


def _capped(rows: Sequence[sqlite3.Row]) -> list[sqlite3.Row]:
    taken: list[sqlite3.Row] = []
    chars = 0
    for row in rows[:MAX_BATCH]:
        chars += len(row["body"])
        if taken and chars > MAX_BATCH_BODY_CHARS:
            break
        taken.append(row)
    return taken


def batch(conn: sqlite3.Connection, cursor: int) -> tuple[Batch, str]:
    with read_transaction(conn):
        rows = conn.execute(
            "SELECT * FROM messages WHERE seq > ? ORDER BY seq LIMIT ?", (cursor, MAX_BATCH + 1)
        ).fetchall()
        items = tuple(_sequenced(row) for row in _capped(rows))
        last = items[-1].seq if items else cursor
        touched = [
            conversation_of(row)
            for row in conn.execute(
                "SELECT * FROM conversations WHERE id IN (SELECT value FROM json_each(?))",
                (json.dumps(sorted({item.message.conversation_id for item in items})),),
            )
        ]
        summaries = _summaries(conn, touched, last)
        files = attachments_of(conn, [item.message.id for item in items])
        found = _fingerprint(conn)
    full = len(items) < len(rows)
    return Batch(last, items, files, tuple(sorted(summaries, key=_recency)), full), found
