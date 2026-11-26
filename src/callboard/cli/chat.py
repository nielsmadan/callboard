import argparse
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import replace

from callboard.bellhop_client import Caller, resumed
from callboard.cli.context import as_caller, attach, bellhop, body_of, ring, settings
from callboard.cli.presentation import diagnostic, emit
from callboard.cli.rendering import receipt_json
from callboard.conversations import (
    add_member,
    create_group,
    join_group,
    remove_member,
    require_member,
    require_participants,
)
from callboard.errors import CallboardError
from callboard.identity import validate_handle
from callboard.jsonout import ok_payload
from callboard.mail import addressees, reply_mail, require_mail_thread, send_mail
from callboard.messages import send_direct, send_group
from callboard.models import Attachment, Message, NewGroup, Receipt, Runtime
from callboard.receipts import receipts as receipts_of
from callboard.refs import ref_of


def _draft(
    conversation_id: str, sender: str, body: str, parent_id: str | None, runtime: Runtime
) -> Message:
    return Message(
        f"cb_{runtime.token()}", conversation_id, sender, body, parent_id, runtime.clock()
    )


def _sent_json(
    stored: Message, files: Sequence[Attachment], receipts: Sequence[Receipt]
) -> dict[str, object]:
    return {
        "id": stored.id,
        "conversation": stored.conversation_id,
        "sender": stored.sender,
        "created_at": stored.created_at,
        "parent_id": stored.parent_id,
        "attachments": [
            {
                "id": file.id,
                "filename": file.filename,
                "media_type": file.media_type,
                "size": file.size,
            }
            for file in files
        ],
        "receipts": [receipt_json(receipt) for receipt in receipts],
    }


def _after_commit(
    conn: sqlite3.Connection,
    stored: Message,
    files: Sequence[Attachment],
    bell: Caller,
    runtime: Runtime,
) -> tuple[list[str], list[Receipt]]:
    try:
        warnings = ring(conn, stored.id, bell, runtime.clock())
        receipts = receipts_of(conn, stored.id)
        runtime.trace(
            "sent",
            message=stored.id,
            conversation=stored.conversation_id,
            sender=stored.sender,
            receipts=[receipt_json(receipt) for receipt in receipts],
            warnings=warnings or None,
        )
        return warnings, receipts
    except (sqlite3.Error, OSError) as error:
        raise CallboardError(
            f"stored {stored.id}, then failed: {error}",
            code="store_unavailable",
            extra={"message": _sent_json(stored, files, [])},
        ) from error
    except Exception as error:
        raise CallboardError(
            f"stored {stored.id}, then failed: {type(error).__name__}: {error}",
            code="internal_error",
            extra={"message": _sent_json(stored, files, [])},
        ) from error
    except KeyboardInterrupt as error:
        raise CallboardError(
            f"stored {stored.id}, then interrupted",
            code="interrupted",
            extra={"message": _sent_json(stored, files, [])},
        ) from error


def _report(
    args: argparse.Namespace,
    stored: Message,
    files: Sequence[Attachment],
    receipts: Sequence[Receipt],
    warnings: Sequence[str],
    line: str,
) -> int:
    for warning in warnings:
        diagnostic(warning)
    payload = ok_payload({"message": _sent_json(stored, files, receipts)}, warnings)
    emit(payload, [line], json_mode=args.json)
    return 0


def dm(args: argparse.Namespace, runtime: Runtime) -> int:
    recipient = validate_handle(args.to.removeprefix("@"))
    body = body_of(args.text, runtime, attached=bool(args.attach))
    config = settings(runtime)
    bell = bellhop(runtime, config)
    with as_caller(args, runtime, bell) as (conn, caller):
        paused = time.monotonic()
        if recipient == caller.handle:
            raise CallboardError("cannot send a direct message to yourself", code="usage")
        require_participants(conn, [recipient])
        draft = _draft("", caller.handle, body, args.reply_to, runtime)
        files = attach(args.attach, runtime, config)
        stored = send_direct(conn, draft, recipient, files, rings=not args.no_ping, now=args.now)
        warnings, receipts = _after_commit(conn, stored, files, resumed(bell, paused), runtime)
    line = f"sent {stored.id} to @{recipient}"
    return _report(args, stored, files, receipts, warnings, line)


def _group_send(args: argparse.Namespace, runtime: Runtime) -> int:
    name = validate_handle(args.name, "group")
    body = body_of(args.text, runtime, attached=bool(args.attach))
    config = settings(runtime)
    bell = bellhop(runtime, config)
    with as_caller(args, runtime, bell) as (conn, caller):
        paused = time.monotonic()
        require_member(conn, f"group:{name}", caller.handle)
        draft = _draft(f"group:{name}", caller.handle, body, args.reply_to, runtime)
        files = attach(args.attach, runtime, config)
        stored, tagged = send_group(conn, draft, files, now=args.now)
        warnings, receipts = _after_commit(conn, stored, files, resumed(bell, paused), runtime)
    mentions = f" (mentions {', '.join(f'@{handle}' for handle in tagged)})" if tagged else ""
    line = f"sent {stored.id} to {ref_of(stored.conversation_id, caller.handle)}{mentions}"
    return _report(args, stored, files, receipts, warnings, line)


def _group_create(args: argparse.Namespace, runtime: Runtime) -> int:
    name = validate_handle(args.name, "group")
    handles = [validate_handle(handle, "--members") for handle in args.members]
    if not handles and not args.open:
        raise CallboardError("group create needs --members or --open", code="usage")
    with as_caller(args, runtime, bellhop(runtime, settings(runtime))) as (conn, caller):
        wanted = NewGroup(name, args.project, args.open)
        created = create_group(conn, wanted, caller.handle, handles, runtime.clock())
    everyone = sorted({caller.handle, *handles})
    payload = ok_payload(
        {
            "conversation": created.id,
            "name": created.name,
            "project": created.project,
            "open": args.open,
            "members": everyone,
        }
    )
    kind = "open; " if args.open else ""
    line = f"created {created.id} ({kind}members: {', '.join(everyone)})"
    emit(payload, [line], json_mode=args.json)
    return 0


def _group_join(args: argparse.Namespace, runtime: Runtime) -> int:
    name = validate_handle(args.name, "group")
    with as_caller(args, runtime, bellhop(runtime, settings(runtime))) as (conn, caller):
        joined = join_group(conn, name, caller.handle, runtime.clock())
    line = f"joined group:{name}" if joined else f"{caller.handle} is already in group:{name}"
    payload = ok_payload(
        {"conversation": f"group:{name}", "handle": caller.handle, "joined": joined}
    )
    emit(payload, [line], json_mode=args.json)
    return 0


def _group_add(args: argparse.Namespace, runtime: Runtime) -> int:
    name = validate_handle(args.name, "group")
    handle = validate_handle(args.handle)
    with as_caller(args, runtime, bellhop(runtime, settings(runtime))) as (conn, caller):
        added = add_member(conn, name, caller.handle, handle, runtime.clock())
    line = f"added {handle} to group:{name}" if added else f"{handle} is already in group:{name}"
    payload = ok_payload({"conversation": f"group:{name}", "handle": handle, "added": added})
    emit(payload, [line], json_mode=args.json)
    return 0


def _group_remove(args: argparse.Namespace, runtime: Runtime) -> int:
    name = validate_handle(args.name, "group")
    handle = validate_handle(args.handle)
    with as_caller(args, runtime, bellhop(runtime, settings(runtime))) as (conn, caller):
        emptied = remove_member(conn, name, caller.handle, handle)
    gone = [f"group:{name} had no members left and is gone; its name is free"] if emptied else []
    payload = ok_payload(
        {"conversation": f"group:{name}", "handle": handle, "group_deleted": emptied}
    )
    emit(payload, [f"removed {handle} from group:{name}", *gone], json_mode=args.json)
    return 0


GROUP_ACTIONS = {
    "add": _group_add,
    "create": _group_create,
    "join": _group_join,
    "remove": _group_remove,
    "send": _group_send,
}


def group(args: argparse.Namespace, runtime: Runtime) -> int:
    return GROUP_ACTIONS[args.action](args, runtime)


def _mail_send(args: argparse.Namespace, runtime: Runtime) -> int:
    subject = args.subject.strip()
    if not subject:
        raise CallboardError("--subject must not be empty", code="usage")
    to = [validate_handle(handle, "--to") for handle in args.to]
    cc = [validate_handle(handle, "--cc") for handle in args.cc]
    body = body_of(args.text, runtime, attached=bool(args.attach))
    config = settings(runtime)
    bell = bellhop(runtime, config)
    with as_caller(args, runtime, bell) as (conn, caller):
        paused = time.monotonic()
        draft = _draft("", caller.handle, body, None, runtime)
        draft = replace(draft, conversation_id=f"mail:{runtime.token()}")
        roles = addressees(caller.handle, to, cc)
        require_participants(conn, sorted(roles))
        files = attach(args.attach, runtime, config)
        stored = send_mail(conn, draft, subject, roles, files, urgent=args.urgent)
        warnings, receipts = _after_commit(conn, stored, files, resumed(bell, paused), runtime)
    line = f"sent {stored.id} to {stored.conversation_id}"
    return _report(args, stored, files, receipts, warnings, line)


def _mail_reply(args: argparse.Namespace, runtime: Runtime) -> int:
    body = body_of(args.text, runtime, attached=bool(args.attach))
    config = settings(runtime)
    bell = bellhop(runtime, config)
    with as_caller(args, runtime, bell) as (conn, caller):
        paused = time.monotonic()
        require_mail_thread(conn, args.message_id, caller.handle)
        draft = _draft("", caller.handle, body, args.message_id, runtime)
        files = attach(args.attach, runtime, config)
        stored = reply_mail(conn, draft, files, urgent=args.urgent)
        warnings, receipts = _after_commit(conn, stored, files, resumed(bell, paused), runtime)
    line = f"sent {stored.id} to {stored.conversation_id}"
    return _report(args, stored, files, receipts, warnings, line)


MAIL_ACTIONS = {"reply": _mail_reply, "send": _mail_send}


def mail(args: argparse.Namespace, runtime: Runtime) -> int:
    return MAIL_ACTIONS[args.action](args, runtime)
