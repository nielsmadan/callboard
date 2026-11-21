import argparse
from collections.abc import Callable, Sequence
from typing import Any, NoReturn

from callboard.errors import CallboardError


class _Parser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **{**kwargs, "allow_abbrev": False})

    def error(self, message: str) -> NoReturn:
        raise CallboardError(message, code="usage")


AS_HELP = "act as this handle"
DASH_HINT = "; a TEXT that starts with '-' goes after --, as in: callboard dm nanna -- -x"


def _as_flag() -> "_Parser":
    parent = _Parser(add_help=False)
    parent.add_argument(
        "--as", dest="as_handle", metavar="HANDLE", default=argparse.SUPPRESS, help=AS_HELP
    )
    return parent


def _rejected_as() -> "_Parser":
    parent = _Parser(add_help=False)
    parent.add_argument(
        "--as",
        dest="as_handle",
        metavar="HANDLE",
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    return parent


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="callboard", description="Chat, mail and pings between coding agents.")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument("--as", dest="as_handle", metavar="HANDLE", help=AS_HELP)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", parser_class=_Parser)
    join = commands.add_parser("join", help="join callboard as a handle from this session")
    join.add_argument("handle")
    join.add_argument("--human", action="store_true", help="join as a human, with no route")
    join.add_argument("--json", action="store_true", help="print one JSON object")
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
    log = commands.add_parser("log", help="show what callboard did lately, from its trace file")
    log.add_argument(
        "words",
        nargs="*",
        metavar="TEXT",
        help="show only events that contain every TEXT, such as a message id or a handle",
    )
    log.add_argument(
        "-n", "--lines", type=_positive, default=40, metavar="N", help="how many events"
    )
    log.add_argument(
        "--errors", action="store_true", help="show only what failed or rang with a warning"
    )
    log.add_argument("--json", action="store_true", help="print one JSON object")
    _add_chat(commands)
    _add_reading(commands)
    _add_admin(commands)
    return parser


MAX_LIMIT = 1_000_000
MAX_ADMIN_LIMIT = 500
MAX_SEQ = 2**63 - 1
MIN_INTERVAL = 0.05
MAX_INTERVAL = 10.0


def _within(high: int) -> Callable[[str], int]:
    def check(text: str) -> int:
        value = int(text) if text.isascii() and text.isdigit() else 0
        if not 1 <= value <= high:
            raise argparse.ArgumentTypeError(f"must be an integer from 1 to {high}, got '{text}'")
        return value

    return check


def _interval(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        value = 0.0
    if not MIN_INTERVAL <= value <= MAX_INTERVAL:
        raise argparse.ArgumentTypeError(
            f"must be a number of seconds from {MIN_INTERVAL} to {MAX_INTERVAL:g}, got '{text}'"
        )
    return value


_positive = _within(MAX_LIMIT)


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
    create.add_argument("--json", action="store_true", help="print one JSON object")
    for action, verb in (("add", "add a member"), ("remove", "remove a member")):
        change = actions.add_parser(action, parents=[_as_flag()], help=verb)
        change.add_argument("name")
        change.add_argument("handle")
        change.add_argument("--json", action="store_true", help="print one JSON object")
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
    get.add_argument("--json", action="store_true", help="print one JSON object")


def _add_admin(commands: "argparse._SubParsersAction[_Parser]") -> None:
    admin = commands.add_parser(
        "admin",
        parents=[_rejected_as()],
        description="Read every conversation in the store. Nothing is marked read.",
    )
    actions = admin.add_subparsers(dest="action", metavar="ACTION", parser_class=_Parser)
    actions.required = True
    conversations = actions.add_parser(
        "conversations",
        parents=[_rejected_as()],
        help="list every conversation with its latest message",
    )
    conversations.add_argument("--json", action="store_true", help="print one JSON object")
    history = actions.add_parser(
        "history", parents=[_rejected_as()], help="print a page of any conversation's messages"
    )
    history.add_argument("conversation_id", metavar="CONVERSATION_ID")
    history.add_argument(
        "--before", type=_within(MAX_SEQ), metavar="SEQ", help="only messages before this seq"
    )
    history.add_argument(
        "--limit",
        type=_within(MAX_ADMIN_LIMIT),
        default=50,
        metavar="N",
        help=f"how many messages, at most {MAX_ADMIN_LIMIT}",
    )
    history.add_argument("--json", action="store_true", help="print one JSON object")
    watch = actions.add_parser(
        "watch", parents=[_rejected_as()], help="stream new messages as they arrive"
    )
    watch.add_argument(
        "--interval",
        type=_interval,
        default=0.25,
        metavar="SECONDS",
        help=f"how often to look for changes, {MIN_INTERVAL} to {MAX_INTERVAL:g} seconds",
    )
    watch.add_argument("--json", action="store_true", help="print one JSON object per line")


def _utf8(argument: str) -> bool:
    try:
        argument.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


TEXT_COMMANDS = (("dm",), ("group", "send"), ("mail", "send"), ("mail", "reply"))


def _words(argv: Sequence[str]) -> list[str]:
    words: list[str] = []
    skip = False
    for argument in argv:
        if skip:
            skip = False
        elif argument == "--as":
            skip = True
        elif not argument.startswith("-"):
            words.append(argument)
    return words


def _dash_text(argv: Sequence[str], message: str) -> bool:
    unknown = message.removeprefix("unrecognized arguments: ")
    single = unknown != message and unknown.startswith("-") and not unknown.startswith("--")
    words = _words(argv)
    return single and any(tuple(words[: len(command)]) == command for command in TEXT_COMMANDS)


def parse(argv: Sequence[str]) -> argparse.Namespace:
    if not all(_utf8(argument) for argument in argv):
        raise CallboardError("an argument is not valid UTF-8 text", code="usage")
    try:
        return build_parser().parse_args(argv)
    except CallboardError as error:
        if error.code != "usage" or not _dash_text(argv, str(error)):
            raise
        raise CallboardError(f"{error}{DASH_HINT}", code="usage") from error


def json_requested(argv: Sequence[str]) -> bool:
    return "--json" in argv
