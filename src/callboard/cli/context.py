import argparse
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager

from callboard.errors import CallboardError
from callboard.identity import resolve_caller
from callboard.models import Participant, Runtime
from callboard.paths import store_path
from callboard.store import open_store


@contextmanager
def as_caller(
    args: argparse.Namespace, runtime: Runtime
) -> Iterator[tuple[sqlite3.Connection, Participant]]:
    with closing(open_store(store_path(runtime.env))) as conn:
        yield conn, resolve_caller(conn, args.as_handle, runtime.env)


def body_of(text: str | None, runtime: Runtime) -> str:
    try:
        raw = runtime.stdin() if text is None else text
    except UnicodeDecodeError as error:
        raise CallboardError("stdin is not valid UTF-8 text", code="usage") from error
    body = raw.rstrip("\n")
    if not body.strip():
        raise CallboardError("empty message; pass TEXT or pipe it on stdin", code="usage")
    return body
