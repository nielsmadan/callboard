import argparse
from collections.abc import Sequence
from typing import NoReturn

from callboard.errors import CallboardError


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CallboardError(message, code="usage")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="callboard", description="Chat, mail and pings between coding agents.")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument("--as", dest="as_handle", metavar="HANDLE", help="act as this handle")
    parser.add_subparsers(dest="command", metavar="COMMAND", parser_class=_Parser)
    return parser


def parse(argv: Sequence[str]) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def json_requested(argv: Sequence[str]) -> bool:
    return "--json" in argv
