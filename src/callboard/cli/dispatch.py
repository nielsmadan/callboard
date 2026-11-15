import argparse
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from importlib.metadata import version

from callboard.cli.chat import dm, group, mail
from callboard.cli.commands import join, who
from callboard.cli.doctor import doctor
from callboard.cli.parsing import json_requested, parse
from callboard.cli.presentation import report_error
from callboard.cli.reading import history, inbox, read, receipts
from callboard.errors import CallboardError
from callboard.models import Runtime

type Command = Callable[[argparse.Namespace, Runtime], int]

COMMANDS: Mapping[str, Command] = {
    "dm": dm,
    "doctor": doctor,
    "group": group,
    "history": history,
    "inbox": inbox,
    "join": join,
    "mail": mail,
    "read": read,
    "receipts": receipts,
    "who": who,
}


def run(argv: Sequence[str], runtime: Runtime) -> int:
    try:
        args = parse(argv)
        if args.version:
            print(f"callboard {version('callboard')}")
            return 0
        if args.command is None:
            raise CallboardError("missing command; see callboard --help", code="usage")
        return COMMANDS[args.command](args, runtime)
    except sqlite3.Error as error:
        failure = CallboardError(f"store error: {error}", code="store_unavailable")
        report_error(failure, json_mode=json_requested(argv))
        return failure.exit_code
    except CallboardError as error:
        report_error(error, json_mode=json_requested(argv))
        return error.exit_code
