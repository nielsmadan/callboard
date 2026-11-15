import argparse
from collections.abc import Callable, Mapping, Sequence
from importlib.metadata import version

from callboard.cli.parsing import json_requested, parse
from callboard.cli.presentation import report_error
from callboard.errors import CallboardError

type Clock = Callable[[], str]
type Command = Callable[[argparse.Namespace, Mapping[str, str], Clock], int]

COMMANDS: Mapping[str, Command] = {}


def run(argv: Sequence[str], env: Mapping[str, str], clock: Clock) -> int:
    try:
        args = parse(argv)
        if args.version:
            print(f"callboard {version('callboard')}")
            return 0
        if args.command is None:
            raise CallboardError("missing command; see callboard --help", code="usage")
        return COMMANDS[args.command](args, env, clock)
    except CallboardError as error:
        report_error(error, json_mode=json_requested(argv))
        return error.exit_code
