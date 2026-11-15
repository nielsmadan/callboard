import argparse

from callboard.cli.context import as_caller
from callboard.cli.presentation import emit
from callboard.cli.rendering import (
    inbox_json,
    inbox_line,
    message_json,
    messages_lines,
    receipt_json,
    receipt_lines,
)
from callboard.conversations import require_member
from callboard.jsonout import ok_payload
from callboard.messages import history as history_of
from callboard.messages import read_conversation, read_message, require_message
from callboard.models import Runtime
from callboard.receipts import inbox as inbox_of
from callboard.receipts import receipts as receipts_of
from callboard.refs import ConversationRef, parse_ref, ref_of


def inbox(args: argparse.Namespace, runtime: Runtime) -> int:
    with as_caller(args, runtime) as (conn, caller):
        entries = inbox_of(conn, caller.handle)
    me = caller.handle
    width = max((len(ref_of(entry.conversation.id, me)) for entry in entries), default=0)
    lines = [inbox_line(entry, me, width) for entry in entries] or ["no unread messages"]
    payload = ok_payload({"conversations": [inbox_json(entry, me) for entry in entries]})
    emit(payload, lines, json_mode=args.json)
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
    label = ref_of(conversation_id, caller.handle)
    payload = ok_payload(
        {"ref": label, "peek": args.peek, "messages": [message_json(item) for item in items]}
    )
    lines = messages_lines(items) or [f"no unread messages in {label}"]
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
    label = ref_of(conversation_id, caller.handle)
    payload = ok_payload({"ref": label, "messages": [message_json(item) for item in items]})
    emit(payload, messages_lines(items) or [f"no messages in {label}"], json_mode=args.json)
    return 0


def receipts(args: argparse.Namespace, runtime: Runtime) -> int:
    with as_caller(args, runtime) as (conn, caller):
        found = require_message(conn, args.message_id, caller.handle)
        items = receipts_of(conn, found.id)
    payload = ok_payload(
        {"message": message_json(found), "receipts": [receipt_json(item) for item in items]}
    )
    emit(payload, receipt_lines(items), json_mode=args.json)
    return 0
