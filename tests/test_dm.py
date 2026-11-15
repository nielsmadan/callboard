import os
import subprocess
import sys

import pytest

from callboard.cli.dispatch import run
from callboard.models import Runtime
from helpers import Callboard, rows, seed


@pytest.fixture(autouse=True)
def people() -> None:
    seed(("enki", "enki"), ("nanna", "sess-nanna"), ("niels", None))


def _receipts() -> list[tuple[str, str, str, str | None]]:
    return rows("SELECT message_id, recipient, ping, ping_state FROM receipts ORDER BY rowid")


def test_dm_stores_the_message_and_a_pending_idle_receipt(cb: Callboard) -> None:
    result = cb("--as", "enki", "dm", "nanna", "hello")
    assert result == (0, "sent cb_000000000001 to @nanna\n", "")
    assert rows("SELECT id, kind, created_by FROM conversations") == [
        ("dm:enki:nanna", "dm", "enki")
    ]
    assert rows("SELECT handle, role FROM members ORDER BY handle") == [
        ("enki", "member"),
        ("nanna", "member"),
    ]
    assert rows("SELECT id, conversation_id, sender, body, parent_id FROM messages") == [
        ("cb_000000000001", "dm:enki:nanna", "enki", "hello", None)
    ]
    assert _receipts() == [("cb_000000000001", "nanna", "idle", "pending")]


def test_dm_creates_the_conversation_once_in_either_direction(cb: Callboard) -> None:
    assert cb("--as", "enki", "dm", "nanna", "one").code == 0
    assert cb("--as", "nanna", "dm", "@enki", "two").code == 0
    assert rows("SELECT id FROM conversations") == [("dm:enki:nanna",)]
    assert rows("SELECT conversation_id, sender FROM messages ORDER BY seq") == [
        ("dm:enki:nanna", "enki"),
        ("dm:enki:nanna", "nanna"),
    ]


@pytest.mark.parametrize(
    ("flags", "recipient", "receipt"),
    [
        (["--now"], "nanna", ("nanna", "now", "pending")),
        (["--no-ping"], "nanna", ("nanna", "none", None)),
        ([], "niels", ("niels", "none", None)),
    ],
)
def test_ping_level_follows_flags_and_route(
    cb: Callboard, flags: list[str], recipient: str, receipt: tuple[str, str, str | None]
) -> None:
    assert cb("--as", "enki", "dm", recipient, "hi", *flags).code == 0
    assert [row[1:] for row in _receipts()] == [receipt]


def test_now_and_no_ping_together_are_a_usage_error(cb: Callboard) -> None:
    assert cb("--as", "enki", "dm", "nanna", "hi", "--now", "--no-ping").code == 2


def test_text_comes_from_stdin_when_omitted(cb: Callboard) -> None:
    assert cb("--as", "enki", "dm", "nanna", stdin="first\nsecond\n").code == 0
    assert rows("SELECT body FROM messages") == [("first\nsecond",)]


@pytest.mark.parametrize("stdin", ["", "  \n\n"])
def test_an_empty_body_is_a_usage_error_and_stores_nothing(cb: Callboard, stdin: str) -> None:
    result = cb("--as", "enki", "dm", "nanna", stdin=stdin)
    assert result == (2, "", "callboard: empty message; pass TEXT or pipe it on stdin\n")
    assert rows("SELECT count(*) FROM messages") == [(0,)]


def test_stdin_that_is_not_utf8_is_a_usage_error(cb: Callboard) -> None:
    def undecodable() -> str:
        return b"\xff\xfe".decode("utf-8")

    runtime = Runtime(os.environ, lambda: "t", lambda: "000000000001", undecodable)
    assert run(["--as", "enki", "dm", "nanna"], runtime) == 2
    assert rows("SELECT count(*) FROM messages") == [(0,)]


def test_dm_to_yourself_is_a_usage_error(cb: Callboard) -> None:
    result = cb("--as", "enki", "dm", "enki", "hi")
    assert result == (2, "", "callboard: cannot send a direct message to yourself\n")


def test_dm_to_an_unknown_handle_stores_nothing(cb: Callboard) -> None:
    result = cb("--as", "enki", "dm", "ghost", "hi")
    assert result == (3, "", "callboard: no participant 'ghost'\n")
    assert rows("SELECT count(*) FROM conversations") == [(0,)]


def test_reply_to_stores_the_parent(cb: Callboard) -> None:
    assert cb("--as", "enki", "dm", "nanna", "question").code == 0
    assert cb("--as", "nanna", "dm", "enki", "answer", "--reply-to", "cb_000000000001").code == 0
    assert rows("SELECT id, parent_id FROM messages ORDER BY seq") == [
        ("cb_000000000001", None),
        ("cb_000000000002", "cb_000000000001"),
    ]


def test_reply_to_a_message_in_another_conversation_is_refused(cb: Callboard) -> None:
    assert cb("--as", "enki", "dm", "niels", "elsewhere").code == 0
    result = cb("--as", "enki", "dm", "nanna", "hi", "--reply-to", "cb_000000000001")
    assert result == (
        2,
        "",
        "callboard: --reply-to: cb_000000000001 is in another conversation (dm:enki:niels)\n",
    )
    assert rows("SELECT count(*) FROM messages") == [(1,)]


def test_reply_to_an_unknown_message_is_not_found(cb: Callboard) -> None:
    result = cb("--as", "enki", "dm", "nanna", "hi", "--reply-to", "cb_0000000000ff")
    assert result == (3, "", "callboard: --reply-to: no message cb_0000000000ff\n")


def test_two_concurrent_first_sends_create_one_conversation() -> None:
    def send(sender: str, recipient: str) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [sys.executable, "-m", "callboard", "--as", sender, "dm", recipient, "hi"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=dict(os.environ),
        )

    processes = [send(*pair) for _ in range(4) for pair in (("enki", "nanna"), ("nanna", "enki"))]
    results = [(process.wait(timeout=60), process.communicate()[1]) for process in processes]
    assert results == [(0, "")] * 8
    assert rows("SELECT id FROM conversations") == [("dm:enki:nanna",)]
    assert rows("SELECT count(*) FROM members") == [(2,)]
    assert rows("SELECT count(*) FROM messages") == [(8,)]


def test_as_works_after_the_command_too(cb: Callboard) -> None:
    assert cb("dm", "nanna", "hi", "--as", "enki") == (0, "sent cb_000000000001 to @nanna\n", "")
    assert cb("group", "create", "ops", "--members", "nanna", "--as", "niels").code == 0
    assert cb("group", "send", "ops", "@nanna", "--as", "niels").code == 0
    assert rows("SELECT sender FROM messages ORDER BY seq") == [("enki",), ("niels",)]
    assert cb("inbox", "--json", "--as", "nanna").json()["conversations"][0]["ref"] == "group:ops"
