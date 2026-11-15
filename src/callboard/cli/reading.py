import argparse
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Literal

from callboard.attachments import attachment as attachment_of
from callboard.attachments import attachments_of
from callboard.bellhop_client import Caller
from callboard.cli.context import as_caller, bellhop, settings
from callboard.cli.presentation import diagnostic, emit
from callboard.cli.rendering import (
    attachment_json,
    inbox_json,
    inbox_lines,
    message_json,
    messages_json,
    messages_lines,
    receipt_json,
    receipt_lines,
)
from callboard.conversations import require_member
from callboard.errors import CallboardError
from callboard.jsonout import ok_payload
from callboard.messages import history as history_of
from callboard.messages import read_conversation, read_message, require_message
from callboard.models import Attachment, Runtime
from callboard.paths import attachments_dir
from callboard.ping import refresh
from callboard.receipts import inbox as inbox_of
from callboard.receipts import receipts as receipts_of
from callboard.refs import ConversationRef, parse_ref, ref_of


def _refresh(
    conn: sqlite3.Connection,
    scope: Literal["recipient", "message"],
    value: str,
    bell: Caller,
    now: str,
) -> list[str]:
    warnings = refresh(conn, scope, value, bell, now)
    for warning in warnings:
        diagnostic(warning)
    return warnings


def inbox(args: argparse.Namespace, runtime: Runtime) -> int:
    bell = bellhop(runtime, settings(runtime))
    with as_caller(args, runtime, bell) as (conn, caller):
        warnings = _refresh(conn, "recipient", caller.handle, bell, runtime.clock())
        entries = inbox_of(conn, caller.handle)
    me = caller.handle
    payload = ok_payload({"conversations": [inbox_json(entry, me) for entry in entries]}, warnings)
    emit(payload, inbox_lines(entries, me), json_mode=args.json)
    return 0


def read(args: argparse.Namespace, runtime: Runtime) -> int:
    bell = bellhop(runtime, settings(runtime))
    with as_caller(args, runtime, bell) as (conn, caller):
        ref = parse_ref(args.ref, caller.handle)
        now = runtime.clock()
        if isinstance(ref, ConversationRef):
            conversation_id = ref.conversation_id
            items = read_conversation(conn, conversation_id, caller.handle, now, peek=args.peek)
        else:
            found = read_message(conn, ref.message_id, caller.handle, now, peek=args.peek)
            conversation_id, items = found.conversation_id, [found]
        files = attachments_of(conn, [item.id for item in items])
    label = ref_of(conversation_id, caller.handle)
    directory = attachments_dir(runtime.env)
    payload = ok_payload(
        {"ref": label, "peek": args.peek, "messages": messages_json(items, files, directory)}
    )
    lines = messages_lines(items, files, directory) or [f"no unread messages in {label}"]
    emit(payload, lines, json_mode=args.json)
    return 0


def history(args: argparse.Namespace, runtime: Runtime) -> int:
    bell = bellhop(runtime, settings(runtime))
    with as_caller(args, runtime, bell) as (conn, caller):
        ref = parse_ref(args.ref, caller.handle)
        if isinstance(ref, ConversationRef):
            conversation_id = require_member(conn, ref.conversation_id, caller.handle).id
        else:
            conversation_id = require_message(conn, ref.message_id, caller.handle).conversation_id
        items = history_of(conn, conversation_id, args.limit)
        files = attachments_of(conn, [item.id for item in items])
    label = ref_of(conversation_id, caller.handle)
    directory = attachments_dir(runtime.env)
    payload = ok_payload({"ref": label, "messages": messages_json(items, files, directory)})
    lines = messages_lines(items, files, directory) or [f"no messages in {label}"]
    emit(payload, lines, json_mode=args.json)
    return 0


def receipts(args: argparse.Namespace, runtime: Runtime) -> int:
    bell = bellhop(runtime, settings(runtime))
    with as_caller(args, runtime, bell) as (conn, caller):
        found = require_message(conn, args.message_id, caller.handle)
        warnings = _refresh(conn, "message", found.id, bell, runtime.clock())
        items = receipts_of(conn, found.id)
        files = attachments_of(conn, [found.id])[found.id]
    directory = attachments_dir(runtime.env)
    payload = ok_payload(
        {
            "message": message_json(found, files, directory),
            "receipts": [receipt_json(item) for item in items],
        },
        warnings,
    )
    emit(payload, receipt_lines(items), json_mode=args.json)
    return 0


def _got(args: argparse.Namespace, item: Attachment, runtime: Runtime, line: str) -> None:
    payload = ok_payload(
        {
            "attachment": attachment_json(item, attachments_dir(runtime.env)),
            "out": None if args.out is None else os.path.abspath(args.out),
        }
    )
    emit(payload, [line], json_mode=args.json)


def _private(path: str, flags: int) -> int:
    return os.open(path, flags, 0o600)


def attachment(args: argparse.Namespace, runtime: Runtime) -> int:
    bell = bellhop(runtime, settings(runtime))
    with as_caller(args, runtime, bell) as (conn, caller):
        found = attachment_of(conn, args.attachment_id)
        if found is None:
            raise CallboardError(f"no attachment {args.attachment_id}", code="attachment_not_found")
        item, message_id = found
        require_message(conn, message_id, caller.handle)
    stored = attachments_dir(runtime.env) / item.sha256
    if not stored.is_file():
        raise CallboardError(
            f"attachment {item.id} is missing its file {stored}", code="attachment_missing"
        )
    if args.out is None:
        _got(args, item, runtime, str(stored))
        return 0
    if os.path.isdir(args.out):
        raise CallboardError(f"--out: {args.out} is a directory; name a file", code="usage")
    created = False
    try:
        with stored.open("rb") as source, open(args.out, "xb", opener=_private) as target:
            created = True
            shutil.copyfileobj(source, target)
    except FileExistsError as error:
        raise CallboardError(f"--out: {args.out} already exists", code="usage") from error
    except OSError as error:
        if created:
            Path(args.out).unlink(missing_ok=True)
        raise CallboardError(
            f"--out: cannot write {args.out}: {error.strerror}", code="usage"
        ) from error
    _got(args, item, runtime, args.out)
    return 0
