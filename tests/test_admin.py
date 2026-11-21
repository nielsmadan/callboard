import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from callboard.cli import main
from callboard.paths import store_path
from callboard.store import MIGRATIONS, open_readonly
from helpers import Callboard, FakeBellhop, chat_scenario, load_golden, rows, seed


@pytest.fixture
def scenario(cb: Callboard, ringing: FakeBellhop) -> None:
    chat_scenario(cb)


def store() -> str:
    return str(store_path(os.environ))


def golden(name: str) -> object:
    expected = load_golden(name)
    assert isinstance(expected, dict)
    return {**expected, "store": store()}


def summaries(cb: Callboard) -> list[dict[str, Any]]:
    result = cb("admin", "conversations", "--json")
    assert (result.code, result.err) == (0, "")
    conversations: list[dict[str, Any]] = result.json()["conversations"]
    return conversations


def page(cb: Callboard, *argv: str) -> dict[str, Any]:
    result = cb("admin", "history", *argv, "--json")
    assert (result.code, result.err) == (0, "")
    return result.json()


@pytest.mark.usefixtures("scenario")
def test_conversations_json_matches_the_golden(cb: Callboard) -> None:
    assert cb("admin", "conversations", "--json").json() == golden("admin-conversations.json")


@pytest.mark.usefixtures("scenario")
def test_conversations_are_ordered_by_latest_message_with_empty_ones_last(cb: Callboard) -> None:
    assert cb("--as", "enki", "group", "create", "quiet", "--members", "nanna").code == 0
    assert cb("--as", "nanna", "dm", "enki", "back on it").code == 0
    assert [item["id"] for item in summaries(cb)] == ["dm:enki:nanna", "group:ops", "group:quiet"]


@pytest.mark.usefixtures("scenario")
def test_conversations_follow_membership_and_new_messages(cb: Callboard) -> None:
    seed(("utu", None))
    assert cb("--as", "enki", "group", "add", "ops", "utu").code == 0
    assert cb("--as", "utu", "group", "send", "ops", "hello all").code == 0
    ops = next(item for item in summaries(cb) if item["id"] == "group:ops")
    assert (ops["members"], ops["messages"], ops["first_seq"]) == (
        ["enki", "nanna", "niels", "utu"],
        3,
        2,
    )
    assert ops["last"] == {
        "seq": 4,
        "id": "cb_000000000004",
        "sender": "utu",
        "created_at": "2026-11-14T09:00:00Z",
        "preview": "hello all",
    }


def test_a_missing_store_lists_nothing_and_creates_nothing(cb: Callboard) -> None:
    result = cb("admin", "conversations", "--json")
    assert (result.code, result.err) == (0, "")
    assert result.json() == {
        "schema_version": 1,
        "status": "ok",
        "warnings": [],
        "store": store(),
        "cursor": 0,
        "conversations": [],
    }
    assert cb("admin", "conversations") == (0, "no conversations\n", "")
    assert Path(store()).exists() is False


def test_an_empty_store_file_counts_as_missing(cb: Callboard) -> None:
    Path(store()).parent.mkdir(parents=True)
    Path(store()).touch()
    assert summaries(cb) == []
    assert Path(store()).read_bytes() == b""


@pytest.mark.usefixtures("scenario")
def test_reading_leaves_the_store_file_untouched(cb: Callboard) -> None:
    path = Path(store())
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    assert cb("admin", "conversations", "--json").code == 0
    assert cb("admin", "history", "group:ops", "--json").code == 0
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.usefixtures("scenario")
@pytest.mark.parametrize("command", [("conversations",), ("history", "group:ops"), ("watch",)])
def test_a_newer_store_schema_is_refused(cb: Callboard, command: tuple[str, ...]) -> None:
    newer = str(len(MIGRATIONS) + 1)
    with closing(sqlite3.connect(store())) as conn, conn:
        conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (newer,))
    result = cb("admin", *command, "--json")
    assert result.code == 1
    assert result.json()["error"] == {
        "code": "schema_too_new",
        "message": f"store schema version {newer} is newer than this callboard supports"
        f" ({len(MIGRATIONS)}); upgrade callboard",
    }


def test_an_unreadable_store_is_unavailable(cb: Callboard) -> None:
    Path(store()).parent.mkdir(parents=True)
    Path(store()).write_bytes(b"not a database, just some bytes that are long enough" * 20)
    result = cb("admin", "conversations", "--json")
    assert result.code == 1
    assert result.json()["error"]["code"] == "store_unavailable"
    assert result.json()["error"]["message"].startswith(f"cannot read store {store()}: ")


@pytest.mark.usefixtures("scenario")
def test_the_cursor_keeps_the_highest_seq_after_a_group_is_dropped(cb: Callboard) -> None:
    steps = [
        ("--as", "enki", "group", "create", "brief", "--members", "nanna"),
        ("--as", "enki", "group", "send", "brief", "soon gone"),
        ("--as", "enki", "group", "remove", "brief", "nanna"),
        ("--as", "enki", "group", "remove", "brief", "enki"),
    ]
    assert [cb(*step).code for step in steps] == [0] * len(steps)
    result = cb("admin", "conversations", "--json").json()
    assert result["cursor"] == 4
    assert [item["id"] for item in result["conversations"]] == ["group:ops", "dm:enki:nanna"]


@pytest.mark.usefixtures("scenario")
def test_conversations_text_lists_one_line_each(cb: Callboard) -> None:
    assert cb("--as", "enki", "group", "create", "quiet", "--members", "nanna").code == 0
    lines = (
        "group:ops      2 messages  2026-11-14T09:00:00Z niels: on it\n"
        "dm:enki:nanna  1 message   2026-11-14T09:00:00Z enki: first line\\nsecond line\n"
        "group:quiet    0 messages\n"
    )
    assert cb("admin", "conversations") == (0, lines, "")


@pytest.mark.usefixtures("scenario")
def test_history_json_matches_the_golden(cb: Callboard) -> None:
    assert page(cb, "group:ops") == golden("admin-history.json")


@pytest.mark.usefixtures("scenario")
def test_history_pages_back_with_limit_and_before(cb: Callboard) -> None:
    for text in ("three", "four"):
        assert cb("--as", "enki", "group", "send", "ops", text).code == 0
    latest = page(cb, "group:ops", "--limit", "2")
    assert [(item["seq"], item["body"]) for item in latest["messages"]] == [
        (4, "three"),
        (5, "four"),
    ]
    assert latest["more"] is True
    older = page(cb, "group:ops", "--limit", "2", "--before", "4")
    assert [(item["seq"], item["body"]) for item in older["messages"]] == [
        (2, "@nanna please review"),
        (3, "on it"),
    ]
    assert older["more"] is False


@pytest.mark.usefixtures("scenario")
def test_history_text_points_at_older_messages(cb: Callboard) -> None:
    lines = (
        "#3  cb_000000000003  2026-11-14T09:00:00Z  niels (reply to cb_000000000002): on it\n"
        "older messages: callboard admin history group:ops --before 3\n"
    )
    assert cb("admin", "history", "group:ops", "--limit", "1") == (0, lines, "")
    assert cb("admin", "history", "dm:enki:nanna") == (
        0,
        "#1  cb_000000000001  2026-11-14T09:00:00Z  enki: first line\n  second line\n",
        "",
    )


@pytest.mark.usefixtures("scenario")
def test_history_of_an_empty_group_has_no_messages(cb: Callboard) -> None:
    assert cb("--as", "enki", "group", "create", "quiet", "--members", "nanna").code == 0
    assert cb("admin", "history", "group:quiet") == (0, "no messages in group:quiet\n", "")
    assert (page(cb, "group:quiet")["messages"], page(cb, "group:quiet")["more"]) == ([], False)


@pytest.mark.usefixtures("scenario")
def test_history_before_the_first_message_says_so(cb: Callboard) -> None:
    assert cb("admin", "history", "dm:enki:nanna", "--before", "1") == (
        0,
        "no messages in dm:enki:nanna before 1\n",
        "",
    )


@pytest.mark.usefixtures("scenario")
def test_a_non_numeric_schema_version_is_an_error_without_a_leak(cb: Callboard) -> None:
    with closing(sqlite3.connect(store())) as conn, conn:
        conn.execute("UPDATE meta SET value = 'two' WHERE key = 'schema_version'")
    with pytest.raises(ValueError, match="invalid literal"):
        open_readonly(Path(store()))


@pytest.mark.usefixtures("scenario")
def test_history_of_an_unknown_conversation_is_not_found(cb: Callboard) -> None:
    result = cb("admin", "history", "group:nope", "--json")
    assert result.code == 3
    assert result.json()["error"] == {
        "code": "conversation_not_found",
        "message": "no conversation group:nope",
    }


def test_history_without_a_store_is_not_found(cb: Callboard) -> None:
    assert cb("admin", "history", "group:ops") == (
        3,
        "",
        "callboard: no conversation group:ops\n",
    )
    assert Path(store()).exists() is False


@pytest.mark.usefixtures("scenario")
def test_history_marks_nothing_read(cb: Callboard) -> None:
    assert len(page(cb, "group:ops")["messages"]) == 2
    assert rows("SELECT read_at FROM receipts WHERE message_id = 'cb_000000000002'") == [
        (None,),
        (None,),
    ]


@pytest.mark.usefixtures("scenario")
def test_history_cuts_long_bodies(cb: Callboard) -> None:
    assert cb("--as", "enki", "dm", "nanna", "--no-ping", stdin="x" * 70_000).code == 0
    messages = page(cb, "dm:enki:nanna")["messages"]
    assert [(len(item["body"]), item["body_truncated"]) for item in messages] == [
        (len("first line\nsecond line"), False),
        (65_536, True),
    ]


@pytest.mark.usefixtures("scenario")
def test_history_lists_attachments(cb: Callboard, tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("hello\n", encoding="utf-8")
    assert cb("--as", "enki", "dm", "nanna", "see file", "--attach", str(notes)).code == 0
    last = page(cb, "dm:enki:nanna", "--limit", "1")["messages"]
    assert [(item["filename"], item["size"]) for item in last[0]["attachments"]] == [
        ("notes.txt", 6)
    ]


@pytest.mark.parametrize("limit", ["0", "501", "x"])
def test_history_limit_is_bounded(cb: Callboard, limit: str) -> None:
    result = cb("admin", "history", "group:ops", "--limit", limit, "--json")
    assert result.code == 2
    assert result.json()["error"]["message"] == (
        f"argument --limit: must be an integer from 1 to 500, got '{limit}'"
    )


@pytest.mark.parametrize(
    "argv",
    [
        ("--as", "enki", "admin", "conversations"),
        ("admin", "--as", "enki", "conversations"),
        ("admin", "conversations", "--as", "enki"),
        ("--as", "enki", "admin", "history", "group:ops"),
        ("admin", "history", "group:ops", "--as", "enki"),
        ("admin", "watch", "--as", "enki"),
    ],
)
def test_admin_commands_take_no_as(cb: Callboard, argv: tuple[str, ...]) -> None:
    assert cb(*argv) == (2, "", "callboard: admin commands take no --as\n")


def help_text(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    with pytest.raises(SystemExit) as stopped:
        main(list(argv))
    assert stopped.value.code == 0
    return capsys.readouterr().out


def test_admin_is_hidden_from_the_command_list(capsys: pytest.CaptureFixture[str]) -> None:
    listed = [
        line.split()[0] for line in help_text(capsys, "--help").splitlines() if line[:4] == " " * 4
    ]
    assert "history" in listed
    assert "admin" not in listed


def test_admin_help_lists_its_actions(capsys: pytest.CaptureFixture[str]) -> None:
    listed = [
        line.split()[0]
        for line in help_text(capsys, "admin", "--help").splitlines()
        if line[:4] == " " * 4
    ]
    assert listed == ["conversations", "history", "watch"]
