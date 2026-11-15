import json
import sqlite3
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from callboard.bellhop_client import (
    Caller,
    Reply,
    call,
    error_message,
    parse_message,
    parse_status,
    warnings_of,
)
from callboard.errors import CallboardError
from callboard.models import BellhopMessage, PingState
from callboard.store import write

MAX_PARALLEL = 8
CONFIRM_SECONDS = 5
REFRESH_WINDOW = timedelta(minutes=15)
REFUSED_EXITS = frozenset({2, 3, 4})
READ_STATES = frozenset({"confirmed", "read"})


@dataclass(frozen=True)
class Ring:
    message_id: str
    recipient: str
    route: str
    level: str
    sender: str
    text: str


@dataclass(frozen=True)
class Rung:
    ring: Ring
    bellhop: BellhopMessage | None
    failed: bool
    warning: str | None


def label(kind: str, name: str | None, subject: str | None) -> str:
    if kind == "group":
        return f"group {name}"
    if kind == "mail":
        return f'mail "{subject}"'
    return "dm"


def _count(number: int, noun: str) -> str:
    return f"{number:,} {noun}{'' if number == 1 else 's'}"


def ping_text(
    message_id: str, sender: str, where: str, body: str, attachments: int, *, inline: bool
) -> str:
    if inline:
        return f"callboard {message_id} {where} from {sender}: {body}"
    size = _count(len(body), "char")
    files = f", {_count(attachments, 'attachment')}" if attachments else ""
    return (
        f"callboard {message_id} {where} from {sender} ({size}{files});"
        f" read: callboard read {message_id}"
    )


def send_arguments(ring: Ring) -> list[str]:
    wake = ["--wake"] if ring.level in {"idle", "now"} else []
    return [
        "send",
        ring.route,
        "--urgency",
        ring.level,
        *wake,
        "--or-hold",
        "--from",
        ring.sender,
        "--key",
        f"{ring.message_id}:{ring.recipient}",
        "--confirm",
        str(CONFIRM_SECONDS),
        "--json",
    ]


def pending_rings(conn: sqlite3.Connection, message_ids: Sequence[str] | None) -> list[Ring]:
    rows = conn.execute(
        """SELECT r.message_id, r.recipient, r.ping, r.inline, p.route, m.sender, m.body,
  c.kind, c.name, c.subject,
  (SELECT count(*) FROM attachments a WHERE a.message_id = m.id) AS attachments
FROM receipts r
JOIN messages m ON m.id = r.message_id
JOIN conversations c ON c.id = m.conversation_id
JOIN participants p ON p.handle = r.recipient
WHERE r.ping != 'none' AND r.ping_state = 'pending' AND r.bellhop_id IS NULL
  AND p.route IS NOT NULL
  AND (:all OR r.message_id IN (SELECT value FROM json_each(:ids)))
ORDER BY m.seq, r.recipient""",
        {"all": message_ids is None, "ids": json.dumps(list(message_ids or []))},
    )
    return [
        Ring(
            row["message_id"],
            row["recipient"],
            row["route"],
            row["ping"],
            row["sender"],
            ping_text(
                row["message_id"],
                row["sender"],
                label(row["kind"], row["name"], row["subject"]),
                row["body"],
                row["attachments"],
                inline=bool(row["inline"]),
            ),
        )
        for row in rows
    ]


def _from_reply(ring: Ring, reply: Reply) -> Rung:
    stored = parse_message(reply.payload.get("message"))
    who = f"ping {ring.recipient} for {ring.message_id}"
    if reply.payload.get("status") == "ok":
        if stored is None:
            return Rung(ring, None, False, f"{who}: bellhop send returned no message")
        degraded = stored.degraded_from
        note = f"{who}: held by bellhop; no usable route for {degraded}" if degraded else None
        return Rung(ring, stored, False, note)
    reason = f"{who}: bellhop send: {error_message(reply.payload)}"
    if stored is not None:
        return Rung(ring, stored, stored.state == "failed", reason)
    return Rung(ring, None, reply.exit_code in REFUSED_EXITS, reason)


def ring_one(ring: Ring, caller: Caller) -> Rung:
    try:
        reply = call(caller, send_arguments(ring), stdin=ring.text)
    except CallboardError as error:
        return Rung(ring, None, False, f"ping {ring.recipient} for {ring.message_id}: {error}")
    return _from_reply(ring, reply)


def ring_all(rings: Sequence[Ring], caller: Caller) -> list[Rung]:
    if not rings:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(rings))) as pool:
        return list(pool.map(lambda ring: ring_one(ring, caller), rings))


def _state(rung: Rung) -> PingState | None:
    if rung.bellhop is not None:
        return rung.bellhop.state
    return "failed" if rung.failed else None


def record(conn: sqlite3.Connection, rungs: Sequence[Rung], now: str) -> None:
    updates = [
        (
            rung.bellhop.id if rung.bellhop else None,
            _state(rung),
            now if rung.bellhop and rung.bellhop.state in READ_STATES else None,
            rung.ring.message_id,
            rung.ring.recipient,
        )
        for rung in rungs
        if _state(rung) is not None
    ]
    if not updates:
        return
    with write(conn):
        conn.executemany(
            "UPDATE receipts SET bellhop_id = coalesce(?, bellhop_id), ping_state = ?,"
            " read_at = CASE WHEN inline = 1 AND read_at IS NULL THEN ? ELSE read_at END"
            " WHERE message_id = ? AND recipient = ?",
            updates,
        )


def ring_messages(
    conn: sqlite3.Connection, message_ids: Sequence[str] | None, caller: Caller, now: str
) -> tuple[int, list[str]]:
    rungs = ring_all(pending_rings(conn, message_ids), caller)
    record(conn, rungs, now)
    return len(rungs), [rung.warning for rung in rungs if rung.warning]


def _cutoff(now: str) -> str:
    return (datetime.fromisoformat(now) - REFRESH_WINDOW).strftime("%Y-%m-%dT%H:%M:%SZ")


REFRESHABLE = {
    "recipient": "SELECT DISTINCT r.bellhop_id FROM receipts r"
    " JOIN messages m ON m.id = r.message_id WHERE r.recipient = ?",
    "message": "SELECT DISTINCT r.bellhop_id FROM receipts r"
    " JOIN messages m ON m.id = r.message_id WHERE r.message_id = ?",
}
REFRESHABLE_FILTER = (
    " AND r.bellhop_id IS NOT NULL AND r.ping != 'hold'"
    " AND r.ping_state IN ('pending', 'sending', 'sent') AND m.created_at >= ?"
    " ORDER BY r.bellhop_id"
)


def refresh(
    conn: sqlite3.Connection,
    scope: Literal["recipient", "message"],
    value: str,
    caller: Caller,
    now: str,
) -> list[str]:
    rows = conn.execute(REFRESHABLE[scope] + REFRESHABLE_FILTER, (value, _cutoff(now))).fetchall()
    ids = [row[0] for row in rows]
    if not ids:
        return []
    try:
        payload = call(caller, ["status", *ids, "--json"]).payload
        if payload.get("status") != "ok":
            return [f"refreshing receipts: bellhop status: {error_message(payload)}"]
        found = parse_status(payload)
    except CallboardError as error:
        return [f"refreshing receipts: {error}"]
    with write(conn):
        conn.executemany(
            "UPDATE receipts SET ping_state = ?,"
            " read_at = CASE WHEN inline = 1 AND read_at IS NULL THEN ? ELSE read_at END"
            " WHERE bellhop_id = ? AND ping_state IN ('pending', 'sending', 'sent')",
            [
                (item.state, now if item.state in READ_STATES else None, item.id)
                for item in found.values()
            ],
        )
    return [f"refreshing receipts: bellhop status: {item}" for item in warnings_of(payload)]
