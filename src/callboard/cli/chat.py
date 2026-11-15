import argparse
from collections.abc import Sequence
from dataclasses import replace

from callboard.cli.context import as_caller, attach, body_of
from callboard.cli.presentation import emit
from callboard.cli.rendering import receipt_json
from callboard.conversations import add_member, create_group, remove_member
from callboard.errors import CallboardError
from callboard.identity import validate_handle
from callboard.jsonout import ok_payload
from callboard.mail import addressees, reply_mail, send_mail
from callboard.messages import send_direct, send_group
from callboard.models import Attachment, Message, Receipt, Runtime
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


def _report(
    args: argparse.Namespace,
    stored: Message,
    files: Sequence[Attachment],
    receipts: Sequence[Receipt],
    line: str,
) -> int:
    emit(ok_payload({"message": _sent_json(stored, files, receipts)}), [line], json_mode=args.json)
    return 0


def dm(args: argparse.Namespace, runtime: Runtime) -> int:
    recipient = validate_handle(args.to.removeprefix("@"))
    body = body_of(args.text, runtime, attached=bool(args.attach))
    with as_caller(args, runtime) as (conn, caller):
        if recipient == caller.handle:
            raise CallboardError("cannot send a direct message to yourself", code="usage")
        draft = _draft("", caller.handle, body, args.reply_to, runtime)
        files = attach(args.attach, runtime)
        stored = send_direct(conn, draft, recipient, files, rings=not args.no_ping, now=args.now)
        receipts = receipts_of(conn, stored.id)
    return _report(args, stored, files, receipts, f"sent {stored.id} to @{recipient}")


def _group_send(args: argparse.Namespace, runtime: Runtime) -> int:
    name = validate_handle(args.name, "group")
    body = body_of(args.text, runtime, attached=bool(args.attach))
    with as_caller(args, runtime) as (conn, caller):
        draft = _draft(f"group:{name}", caller.handle, body, args.reply_to, runtime)
        files = attach(args.attach, runtime)
        stored, tagged = send_group(conn, draft, files, now=args.now)
        receipts = receipts_of(conn, stored.id)
    mentions = f" (mentions {', '.join(f'@{handle}' for handle in tagged)})" if tagged else ""
    line = f"sent {stored.id} to {ref_of(stored.conversation_id, caller.handle)}{mentions}"
    return _report(args, stored, files, receipts, line)


def _group_create(args: argparse.Namespace, runtime: Runtime) -> int:
    name = validate_handle(args.name, "group")
    handles = [validate_handle(handle, "--members") for handle in args.members]
    with as_caller(args, runtime) as (conn, caller):
        created = create_group(conn, name, caller.handle, handles, args.project, runtime.clock())
    everyone = sorted({caller.handle, *handles})
    print(f"created {created.id} (members: {', '.join(everyone)})")
    return 0


def _group_add(args: argparse.Namespace, runtime: Runtime) -> int:
    name = validate_handle(args.name, "group")
    handle = validate_handle(args.handle)
    with as_caller(args, runtime) as (conn, caller):
        added = add_member(conn, name, caller.handle, handle, runtime.clock())
    print(f"added {handle} to group:{name}" if added else f"{handle} is already in group:{name}")
    return 0


def _group_remove(args: argparse.Namespace, runtime: Runtime) -> int:
    name = validate_handle(args.name, "group")
    handle = validate_handle(args.handle)
    with as_caller(args, runtime) as (conn, caller):
        remove_member(conn, name, caller.handle, handle)
    print(f"removed {handle} from group:{name}")
    return 0


GROUP_ACTIONS = {
    "add": _group_add,
    "create": _group_create,
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
    with as_caller(args, runtime) as (conn, caller):
        draft = _draft("", caller.handle, body, None, runtime)
        draft = replace(draft, conversation_id=f"mail:{runtime.token()}")
        roles = addressees(caller.handle, to, cc)
        files = attach(args.attach, runtime)
        stored = send_mail(conn, draft, subject, roles, files, urgent=args.urgent)
        receipts = receipts_of(conn, stored.id)
    return _report(args, stored, files, receipts, f"sent {stored.id} to {stored.conversation_id}")


def _mail_reply(args: argparse.Namespace, runtime: Runtime) -> int:
    body = body_of(args.text, runtime, attached=bool(args.attach))
    with as_caller(args, runtime) as (conn, caller):
        draft = _draft("", caller.handle, body, args.message_id, runtime)
        files = attach(args.attach, runtime)
        stored = reply_mail(conn, draft, files, urgent=args.urgent)
        receipts = receipts_of(conn, stored.id)
    return _report(args, stored, files, receipts, f"sent {stored.id} to {stored.conversation_id}")


MAIL_ACTIONS = {"reply": _mail_reply, "send": _mail_send}


def mail(args: argparse.Namespace, runtime: Runtime) -> int:
    return MAIL_ACTIONS[args.action](args, runtime)
