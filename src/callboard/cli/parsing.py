import argparse
from collections.abc import Sequence
from typing import NoReturn

from callboard.errors import CallboardError


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CallboardError(message, code="usage")


AS_HELP = "act as this handle"


def _as_flag() -> "_Parser":
    parent = _Parser(add_help=False)
    parent.add_argument(
        "--as", dest="as_handle", metavar="HANDLE", default=argparse.SUPPRESS, help=AS_HELP
    )
    return parent


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="callboard", description="Chat, mail and pings between coding agents.")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument("--as", dest="as_handle", metavar="HANDLE", help=AS_HELP)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", parser_class=_Parser)
    join = commands.add_parser(
        "join", parents=[_as_flag()], help="join callboard as a handle from this session"
    )
    join.add_argument("handle")
    join.add_argument("--human", action="store_true", help="join as a human, with no route")
    who = commands.add_parser("who", parents=[_as_flag()], help="list participants")
    who.add_argument("--json", action="store_true", help="print one JSON object")
    doctor = commands.add_parser(
        "doctor", parents=[_as_flag()], help="check the store, data directory and bellhop"
    )
    doctor.add_argument("--json", action="store_true", help="print one JSON object")
    doctor.add_argument(
        "--reping", action="store_true", help="ring receipts that bellhop never accepted"
    )
    doctor.add_argument(
        "--prune", action="store_true", help="remove unreferenced attachments; truncate the WAL"
    )
    _add_chat(commands)
    _add_reading(commands)
    return parser


MAX_LIMIT = 1_000_000


def _positive(text: str) -> int:
    value = int(text) if text.isascii() and text.isdigit() else 0
    if not 1 <= value <= MAX_LIMIT:
        raise argparse.ArgumentTypeError(f"must be an integer from 1 to {MAX_LIMIT}, got '{text}'")
    return value


def _handles(text: str) -> list[str]:
    return [handle.strip() for handle in text.split(",") if handle.strip()]


def _add_chat(commands: "argparse._SubParsersAction[_Parser]") -> None:
    dm = commands.add_parser("dm", parents=[_as_flag()], help="send a direct message")
    dm.add_argument("to", metavar="HANDLE")
    dm.add_argument("text", nargs="?", metavar="TEXT", help="message text; stdin when omitted")
    ringing = dm.add_mutually_exclusive_group()
    ringing.add_argument("--now", action="store_true", help="ring as an interrupt")
    ringing.add_argument("--no-ping", action="store_true", help="store without ringing")
    dm.add_argument("--reply-to", metavar="MESSAGE", help="reply to a message in this chat")
    dm.add_argument(
        "--attach", action="append", default=[], metavar="PATH", help="attach a file; repeatable"
    )
    dm.add_argument("--json", action="store_true", help="print one JSON object")
    group = commands.add_parser(
        "group", parents=[_as_flag()], help="create, change and post to groups"
    )
    actions = group.add_subparsers(dest="action", metavar="ACTION", parser_class=_Parser)
    actions.required = True
    create = actions.add_parser("create", parents=[_as_flag()], help="create a group")
    create.add_argument("name")
    create.add_argument("--members", type=_handles, action="extend", required=True, metavar="A,B,C")
    create.add_argument("--project", metavar="P")
    for action, verb in (("add", "add a member"), ("remove", "remove a member")):
        change = actions.add_parser(action, parents=[_as_flag()], help=verb)
        change.add_argument("name")
        change.add_argument("handle")
    send = actions.add_parser(
        "send", parents=[_as_flag()], help="post to a group; @handle rings a member"
    )
    send.add_argument("name")
    send.add_argument("text", nargs="?", metavar="TEXT", help="message text; stdin when omitted")
    send.add_argument("--now", action="store_true", help="ring mentioned members as an interrupt")
    send.add_argument("--reply-to", metavar="MESSAGE", help="reply to a message in this group")
    send.add_argument(
        "--attach", action="append", default=[], metavar="PATH", help="attach a file; repeatable"
    )
    send.add_argument("--json", action="store_true", help="print one JSON object")
    _add_mail(commands)


def _add_mail(commands: "argparse._SubParsersAction[_Parser]") -> None:
    mail = commands.add_parser("mail", parents=[_as_flag()], help="send and reply to mail")
    actions = mail.add_subparsers(dest="action", metavar="ACTION", parser_class=_Parser)
    actions.required = True
    send = actions.add_parser("send", parents=[_as_flag()], help="start a mail thread")
    send.add_argument("--to", type=_handles, action="extend", required=True, metavar="A,B")
    send.add_argument("--cc", type=_handles, action="extend", default=[], metavar="C,D")
    send.add_argument("--subject", required=True, metavar="S")
    send.add_argument("text", nargs="?", metavar="TEXT", help="message text; stdin when omitted")
    send.add_argument("--urgent", action="store_true", help="ring recipients instead of holding")
    send.add_argument(
        "--attach", action="append", default=[], metavar="PATH", help="attach a file; repeatable"
    )
    send.add_argument("--json", action="store_true", help="print one JSON object")
    reply = actions.add_parser("reply", parents=[_as_flag()], help="reply to all in a thread")
    reply.add_argument("message_id", metavar="MESSAGE")
    reply.add_argument("text", nargs="?", metavar="TEXT", help="message text; stdin when omitted")
    reply.add_argument("--urgent", action="store_true", help="ring recipients instead of holding")
    reply.add_argument(
        "--attach", action="append", default=[], metavar="PATH", help="attach a file; repeatable"
    )
    reply.add_argument("--json", action="store_true", help="print one JSON object")


def _add_reading(commands: "argparse._SubParsersAction[_Parser]") -> None:
    inbox = commands.add_parser(
        "inbox", parents=[_as_flag()], help="unread counts per conversation"
    )
    inbox.add_argument("--json", action="store_true", help="print one JSON object")
    read = commands.add_parser(
        "read", parents=[_as_flag()], help="print unread messages and mark them read"
    )
    read.add_argument("ref", help="@handle, group:<name>, mail:<id> or a message id")
    read.add_argument("--peek", action="store_true", help="do not mark anything read")
    read.add_argument("--json", action="store_true", help="print one JSON object")
    history = commands.add_parser(
        "history", parents=[_as_flag()], help="print the latest messages of a conversation"
    )
    history.add_argument("ref", help="@handle, group:<name>, mail:<id> or a message id")
    history.add_argument("--limit", type=_positive, default=20, metavar="N")
    history.add_argument("--json", action="store_true", help="print one JSON object")
    receipts = commands.add_parser(
        "receipts", parents=[_as_flag()], help="ping and read state per recipient"
    )
    receipts.add_argument("message_id", metavar="MESSAGE")
    receipts.add_argument("--json", action="store_true", help="print one JSON object")
    attachment = commands.add_parser("attachment", parents=[_as_flag()], help="fetch attachments")
    files = attachment.add_subparsers(dest="action", metavar="ACTION", parser_class=_Parser)
    files.required = True
    get = files.add_parser("get", parents=[_as_flag()], help="print the stored path or copy it")
    get.add_argument("attachment_id", metavar="ATTACHMENT")
    get.add_argument("--out", metavar="PATH", help="copy the file here instead")


def parse(argv: Sequence[str]) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def json_requested(argv: Sequence[str]) -> bool:
    return "--json" in argv
