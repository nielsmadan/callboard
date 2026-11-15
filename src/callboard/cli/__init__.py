import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from callboard.cli.dispatch import run
from callboard.cli.presentation import silence_stdout
from callboard.codes import FAILURE_EXIT, INTERRUPTED_EXIT


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        exit_code = run(list(sys.argv[1:] if argv is None else argv), os.environ, utc_now)
        sys.stdout.flush()
    except BrokenPipeError:
        silence_stdout()
        return FAILURE_EXIT
    except KeyboardInterrupt:
        return INTERRUPTED_EXIT
    return exit_code
