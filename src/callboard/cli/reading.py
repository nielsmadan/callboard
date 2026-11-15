import argparse
import os
import shutil

from callboard.attachments import attachment as attachment_of
from callboard.attachments import attachments_of
from callboard.cli.context import as_caller
from callboard.cli.presentation import emit
from callboard.cli.rendering import (
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
from callboard.models import Runtime
from callboard.paths import attachments_dir
from callboard.receipts import inbox as inbox_of
from callboard.receipts import receipts as receipts_of
from callboard.refs import ConversationRef, parse_ref, ref_of


def inbox(args: argparse.Namespace, runtime: Runtime) -> int:
    with as_caller(args, runtime) as (conn, caller):
        entries = inbox_of(conn, caller.handle)
    me = caller.handle
    payload = ok_payload({"conversations": [inbox_json(entry, me) for entry in entries]})
    emit(payload, inbox_lines(entries, me), json_mode=args.json)
    return 0


def read(args: argparse.Namespace, runtime: Runtime) -> int:
    with as_caller(args, runtime) as (conn, caller):
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
    with as_caller(args, runtime) as (conn, caller):
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
    with as_caller(args, runtime) as (conn, caller):
        found = require_message(conn, args.message_id, caller.handle)
        items = receipts_of(conn, found.id)
        files = attachments_of(conn, [found.id])[found.id]
    directory = attachments_dir(runtime.env)
    payload = ok_payload(
        {
            "message": message_json(found, files, directory),
            "receipts": [receipt_json(item) for item in items],
        }
    )
    emit(payload, receipt_lines(items), json_mode=args.json)
    return 0


def attachment(args: argparse.Namespace, runtime: Runtime) -> int:
    with as_caller(args, runtime) as (conn, caller):
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
        print(stored)
        return 0
    if os.path.isdir(args.out):
        raise CallboardError(f"--out: {args.out} is a directory; name a file", code="usage")
    try:
        with stored.open("rb") as source, open(args.out, "xb") as target:
            shutil.copyfileobj(source, target)
    except FileExistsError as error:
        raise CallboardError(f"--out: {args.out} already exists", code="usage") from error
    except OSError as error:
        raise CallboardError(
            f"--out: cannot write {args.out}: {error.strerror}", code="usage"
        ) from error
    print(args.out)
    return 0
