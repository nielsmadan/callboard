import argparse

from callboard.cli.context import as_caller, body_of
from callboard.conversations import add_member, create_group, remove_member
from callboard.errors import CallboardError
from callboard.identity import validate_handle
from callboard.messages import send_direct, send_group
from callboard.models import Message, Runtime
from callboard.refs import ref_of


def _draft(
    conversation_id: str, sender: str, body: str, args: argparse.Namespace, runtime: Runtime
) -> Message:
    return Message(
        f"cb_{runtime.token()}", conversation_id, sender, body, args.reply_to, runtime.clock()
    )


def dm(args: argparse.Namespace, runtime: Runtime) -> int:
    recipient = validate_handle(args.to.removeprefix("@"))
    body = body_of(args.text, runtime)
    with as_caller(args, runtime) as (conn, caller):
        if recipient == caller.handle:
            raise CallboardError("cannot send a direct message to yourself", code="usage")
        stored = send_direct(
            conn,
            _draft("", caller.handle, body, args, runtime),
            recipient,
            rings=not args.no_ping,
            now=args.now,
        )
    print(f"sent {stored.id} to @{recipient}")
    return 0


def _group_send(args: argparse.Namespace, runtime: Runtime) -> int:
    name = validate_handle(args.name, "group")
    body = body_of(args.text, runtime)
    with as_caller(args, runtime) as (conn, caller):
        stored, tagged = send_group(
            conn, _draft(f"group:{name}", caller.handle, body, args, runtime), now=args.now
        )
    mentions = f" (mentions {', '.join(f'@{handle}' for handle in tagged)})" if tagged else ""
    print(f"sent {stored.id} to {ref_of(stored.conversation_id, caller.handle)}{mentions}")
    return 0


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
