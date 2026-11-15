import argparse
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager

from callboard.attachments import copy_attachments
from callboard.bellhop_client import Caller, caller_for
from callboard.config import Config, load_config
from callboard.errors import CallboardError
from callboard.identity import resolve_caller
from callboard.models import Attachment, Participant, Runtime
from callboard.paths import attachments_dir, config_path, store_path
from callboard.ping import ring_messages
from callboard.store import open_store


@contextmanager
def as_caller(
    args: argparse.Namespace, runtime: Runtime, bell: Caller
) -> Iterator[tuple[sqlite3.Connection, Participant]]:
    with closing(open_store(store_path(runtime.env))) as conn:
        yield conn, resolve_caller(conn, args.as_handle, bell)


def body_of(text: str | None, runtime: Runtime, *, attached: bool = False) -> str:
    try:
        raw = runtime.stdin() if text is None else text
    except UnicodeDecodeError as error:
        raise CallboardError("stdin is not valid UTF-8 text", code="usage") from error
    body = raw.rstrip("\n")
    if not body.strip() and not attached:
        raise CallboardError("empty message; pass TEXT or pipe it on stdin", code="usage")
    return body


def settings(runtime: Runtime) -> Config:
    return load_config(config_path(runtime.env))


def attach(sources: list[str], runtime: Runtime, config: Config) -> list[Attachment]:
    if not sources:
        return []
    return copy_attachments(
        sources, attachments_dir(runtime.env), config.max_attachment_bytes, runtime.token
    )


def bellhop(runtime: Runtime, config: Config) -> Caller:
    return caller_for(config.ping_command, runtime.env, runtime.deadline)


def ring(conn: sqlite3.Connection, message_id: str, bell: Caller, now: str) -> list[str]:
    _, warnings = ring_messages(conn, [message_id], bell, now)
    return warnings
