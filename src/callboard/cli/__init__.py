import os
import secrets
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from callboard.cli.dispatch import run
from callboard.cli.parsing import json_requested
from callboard.cli.presentation import report_error, silence_stdout
from callboard.codes import FAILURE_EXIT
from callboard.errors import CallboardError
from callboard.models import Runtime


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def random_token() -> str:
    return secrets.token_hex(6)


def read_stdin() -> str:
    if sys.stdin is None or sys.stdin.isatty():
        return ""
    return sys.stdin.read()


def main(argv: Sequence[str] | None = None) -> int:
    runtime = Runtime(os.environ, utc_now, random_token, read_stdin)
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        exit_code = run(arguments, runtime)
        sys.stdout.flush()
    except BrokenPipeError:
        silence_stdout()
        return FAILURE_EXIT
    except KeyboardInterrupt:
        interrupted = CallboardError("interrupted", code="interrupted")
        report_error(interrupted, json_mode=json_requested(arguments))
        return interrupted.exit_code
    except Exception as error:
        unexpected = CallboardError(
            f"internal error: {type(error).__name__}: {error}", code="internal_error"
        )
        report_error(unexpected, json_mode=json_requested(arguments))
        return unexpected.exit_code
    return exit_code
