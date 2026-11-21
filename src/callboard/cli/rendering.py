from collections.abc import Mapping, Sequence
from pathlib import Path

from callboard.models import (
    Attachment,
    Conversation,
    ConversationSummary,
    InboxEntry,
    Message,
    Receipt,
    Sequenced,
    Snapshot,
)
from callboard.refs import ref_of
from callboard.text import one_line, shortened, visible

PREVIEW_CHARS = 140
ADMIN_BODY_CHARS = 65_536


def attachment_json(item: Attachment, directory: Path) -> dict[str, object]:
    return {
        "id": item.id,
        "filename": item.filename,
        "media_type": item.media_type,
        "size": item.size,
        "path": str(directory / item.sha256),
    }


def message_json(item: Message, files: Sequence[Attachment], directory: Path) -> dict[str, object]:
    return {
        "id": item.id,
        "conversation_id": item.conversation_id,
        "sender": item.sender,
        "body": item.body,
        "parent_id": item.parent_id,
        "created_at": item.created_at,
        "attachments": [attachment_json(file, directory) for file in files],
    }


def attachment_line(item: Attachment, directory: Path) -> str:
    return (
        f"  attachment {item.id}  {one_line(item.filename)}  {item.media_type}  {item.size} bytes"
        f"  {directory / item.sha256}"
    )


def message_lines(item: Message, files: Sequence[Attachment], directory: Path) -> list[str]:
    reply = f" (reply to {item.parent_id})" if item.parent_id else ""
    first, *rest = visible(item.body).split("\n")
    return [
        f"{item.id}  {item.created_at}  {item.sender}{reply}: {first}",
        *(f"  {line}" for line in rest),
        *(attachment_line(file, directory) for file in files),
    ]


def messages_json(
    items: Sequence[Message], files: Mapping[str, Sequence[Attachment]], directory: Path
) -> list[dict[str, object]]:
    return [message_json(item, files.get(item.id, ()), directory) for item in items]


def messages_lines(
    items: Sequence[Message], files: Mapping[str, Sequence[Attachment]], directory: Path
) -> list[str]:
    return [
        line for item in items for line in message_lines(item, files.get(item.id, ()), directory)
    ]


def conversation_json(found: Conversation, caller: str) -> dict[str, object]:
    return {
        "ref": ref_of(found.id, caller),
        "id": found.id,
        "kind": found.kind,
        "name": found.name,
        "subject": found.subject,
        "project": found.project,
    }


def inbox_json(entry: InboxEntry, caller: str) -> dict[str, object]:
    return {
        **conversation_json(entry.conversation, caller),
        "unread": entry.unread,
        "mentions": entry.mentions,
        "sender": entry.sender,
    }


def inbox_line(entry: InboxEntry, caller: str, width: int) -> str:
    mentions = entry.mentions
    tail = f", {mentions} mention{'s' if mentions > 1 else ''}" if mentions else ""
    return f"{ref_of(entry.conversation.id, caller):<{width}}  {entry.unread} unread{tail}"


def mail_line(entry: InboxEntry, width: int) -> str:
    subject = one_line(entry.conversation.subject or "")
    return (
        f"{entry.conversation.id:<{width}}  {entry.unread} unread  from {entry.sender}: {subject}"
    )


def inbox_lines(entries: Sequence[InboxEntry], caller: str) -> list[str]:
    chats = [entry for entry in entries if entry.conversation.kind != "mail"]
    mail = [entry for entry in entries if entry.conversation.kind == "mail"]
    if not entries:
        return ["no unread messages"]
    chat_width = max((len(ref_of(entry.conversation.id, caller)) for entry in chats), default=0)
    mail_width = max((len(entry.conversation.id) for entry in mail), default=0)
    chat_lines = [inbox_line(entry, caller, chat_width) for entry in chats]
    mail_lines = ["mail:", *(f"  {mail_line(entry, mail_width)}" for entry in mail)] if mail else []
    return [*chat_lines, *([""] if chat_lines and mail_lines else []), *mail_lines]


def receipt_json(receipt: Receipt) -> dict[str, object]:
    return {
        "recipient": receipt.recipient,
        "ping": receipt.ping,
        "ping_state": receipt.ping_state,
        "bellhop_id": receipt.bellhop_id,
        "inline": receipt.inline,
        "read_at": receipt.read_at,
    }


def receipt_lines(items: Sequence[Receipt]) -> list[str]:
    rows = [("recipient", "ping", "state", "read")] + [
        (item.recipient, item.ping, item.ping_state or "-", item.read_at or "-") for item in items
    ]
    widths = [max(len(row[index]) for row in rows) for index in range(3)]
    return [
        "  ".join(
            [*(cell.ljust(width) for cell, width in zip(row[:3], widths, strict=True)), row[3]]
        )
        for row in rows
    ]


def last_json(item: Sequenced) -> dict[str, object]:
    return {
        "seq": item.seq,
        "id": item.message.id,
        "sender": item.message.sender,
        "created_at": item.message.created_at,
        "preview": shortened(item.message.body, PREVIEW_CHARS),
    }


def summary_json(summary: ConversationSummary) -> dict[str, object]:
    found = summary.conversation
    return {
        "id": found.id,
        "kind": found.kind,
        "name": found.name,
        "subject": found.subject,
        "project": found.project,
        "created_by": found.created_by,
        "created_at": found.created_at,
        "members": list(summary.members),
        "messages": summary.messages,
        "first_seq": summary.first_seq,
        "last": None if summary.last is None else last_json(summary.last),
    }


def admin_message_json(
    item: Sequenced, files: Sequence[Attachment], directory: Path
) -> dict[str, object]:
    message = item.message
    return {
        "seq": item.seq,
        **message_json(message, files, directory),
        "body": message.body[:ADMIN_BODY_CHARS],
        "body_truncated": len(message.body) > ADMIN_BODY_CHARS,
    }


def admin_messages_json(
    items: Sequence[Sequenced], files: Mapping[str, Sequence[Attachment]], directory: Path
) -> list[dict[str, object]]:
    return [admin_message_json(item, files.get(item.message.id, ()), directory) for item in items]


def message_count(summary: ConversationSummary) -> str:
    return f"{summary.messages} message{'' if summary.messages == 1 else 's'}"


def summary_line(summary: ConversationSummary, widths: tuple[int, int]) -> str:
    head = f"{summary.conversation.id:<{widths[0]}}  {message_count(summary):<{widths[1]}}"
    last = summary.last
    if last is None:
        return head.rstrip()
    preview = shortened(last.message.body, PREVIEW_CHARS)
    return f"{head}  {last.message.created_at} {last.message.sender}: {preview}"


def summary_lines(summaries: Sequence[ConversationSummary]) -> list[str]:
    widths = (
        max((len(summary.conversation.id) for summary in summaries), default=0),
        max((len(message_count(summary)) for summary in summaries), default=0),
    )
    return [summary_line(summary, widths) for summary in summaries] or ["no conversations"]


def admin_message_lines(item: Sequenced, files: Sequence[Attachment], directory: Path) -> list[str]:
    first, *rest = message_lines(item.message, files, directory)
    return [f"#{item.seq}  {first}", *rest]


def admin_messages_lines(
    items: Sequence[Sequenced], files: Mapping[str, Sequence[Attachment]], directory: Path
) -> list[str]:
    return [
        line
        for item in items
        for line in admin_message_lines(item, files.get(item.message.id, ()), directory)
    ]


def watch_snapshot_line(store: Path, found: Snapshot) -> str:
    count = len(found.conversations)
    noun = "conversation" if count == 1 else "conversations"
    return f"watching {store}: {count} {noun}, cursor {found.cursor}"


def watch_message_line(item: Sequenced) -> str:
    message = item.message
    first = visible(message.body).split("\n")[0]
    return f"#{item.seq}  {message.conversation_id}  {message.sender}: {first}"
