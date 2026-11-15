import os
import sys
from collections.abc import Mapping, Sequence

from callboard.errors import CallboardError
from callboard.jsonout import error_payload, render


def emit(payload: Mapping[str, object], lines: Sequence[str], *, json_mode: bool) -> None:
    if json_mode:
        print(render(payload))
    else:
        for line in lines:
            print(line)


def diagnostic(text: str) -> None:
    print(f"callboard: {text}", file=sys.stderr)


def report_error(error: CallboardError, *, json_mode: bool) -> None:
    if json_mode:
        print(render(error_payload(error)))
    else:
        diagnostic(str(error))


def silence_stdout() -> None:
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, sys.stdout.fileno())
    os.close(devnull)
