from collections.abc import Mapping, Sequence
from pathlib import Path

from callboard.models import Attachment, Conversation, InboxEntry, Message, Receipt
from callboard.refs import ref_of


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
        f"  attachment {item.id}  {item.filename}  {item.media_type}  {item.size} bytes"
        f"  {directory / item.sha256}"
    )


def message_lines(item: Message, files: Sequence[Attachment], directory: Path) -> list[str]:
    reply = f" (reply to {item.parent_id})" if item.parent_id else ""
    first, *rest = item.body.split("\n")
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
    subject = entry.conversation.subject or ""
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
