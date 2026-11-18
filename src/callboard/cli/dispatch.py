import argparse
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version

from callboard.cli.chat import dm, group, mail
from callboard.cli.commands import join, who
from callboard.cli.doctor import doctor
from callboard.cli.log import log
from callboard.cli.parsing import json_requested, parse
from callboard.cli.presentation import report_error
from callboard.cli.reading import attachment, history, inbox, read, receipts
from callboard.errors import CallboardError
from callboard.models import Runtime
from callboard.trace import working_directory

type Command = Callable[[argparse.Namespace, Runtime], int]

COMMANDS: Mapping[str, Command] = {
    "attachment": attachment,
    "dm": dm,
    "doctor": doctor,
    "group": group,
    "history": history,
    "inbox": inbox,
    "join": join,
    "log": log,
    "mail": mail,
    "read": read,
    "receipts": receipts,
    "who": who,
}


UNTRACED = frozenset({"log"})


def installed_version() -> str:
    try:
        return version("callboard")
    except PackageNotFoundError:
        return "0+unknown"


def _run(argv: Sequence[str], runtime: Runtime) -> tuple[str | None, int | CallboardError]:
    command: str | None = None
    try:
        args = parse(argv)
        command = args.command
        if args.version:
            print(f"callboard {installed_version()}")
            return command, 0
        if command is None:
            raise CallboardError("missing command; see callboard --help", code="usage")
        return command, COMMANDS[command](args, runtime)
    except sqlite3.Error as error:
        return command, CallboardError(f"store error: {error}", code="store_unavailable")
    except CallboardError as error:
        return command, error


def command_fields(
    argv: Sequence[str], env: Mapping[str, str], outcome: int | CallboardError, seconds: float
) -> dict[str, object]:
    failure = outcome if isinstance(outcome, CallboardError) else None
    return {
        "argv": list(argv),
        "cwd": working_directory(),
        "as": env.get("CALLBOARD_AS") or None,
        "exit": failure.exit_code if failure else outcome,
        "code": failure.code if failure else None,
        "error": str(failure) if failure else None,
        "ms": round(seconds * 1000),
    }


def run(argv: Sequence[str], runtime: Runtime) -> int:
    started = time.monotonic()
    command, outcome = _run(argv, runtime)
    if argv and command not in UNTRACED:
        fields = command_fields(argv, runtime.env, outcome, time.monotonic() - started)
        runtime.trace("command", **fields)
    if isinstance(outcome, CallboardError):
        report_error(outcome, json_mode=json_requested(argv))
        return outcome.exit_code
    return outcome
