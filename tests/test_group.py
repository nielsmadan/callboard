from pathlib import Path

import pytest

from callboard.mentions import mentioned
from helpers import Callboard, rows, seed

pytestmark = pytest.mark.usefixtures("ringing")


@pytest.fixture(autouse=True)
def people() -> None:
    seed(("enki", "enki"), ("nanna", "sess-nanna"), ("utu", "utu"), ("niels", None))


@pytest.fixture
def ops(cb: Callboard) -> None:
    assert cb("--as", "enki", "group", "create", "ops", "--members", "nanna,niels").code == 0


def _receipts() -> list[tuple[str, str, str | None]]:
    return rows("SELECT recipient, ping, ping_state FROM receipts ORDER BY recipient")


def test_create_adds_the_creator_as_a_member(cb: Callboard) -> None:
    result = cb(
        "--as",
        "enki",
        "group",
        "create",
        "ops",
        "--members",
        "nanna, niels,nanna",
        "--project",
        "bellhop",
    )
    assert result == (0, "created group:ops (members: enki, nanna, niels)\n", "")
    assert rows("SELECT id, kind, name, project, created_by FROM conversations") == [
        ("group:ops", "group", "ops", "bellhop", "enki")
    ]
    assert rows("SELECT handle FROM members ORDER BY handle") == [
        ("enki",),
        ("nanna",),
        ("niels",),
    ]


def test_repeated_members_flags_add_up(cb: Callboard) -> None:
    result = cb("--as", "enki", "group", "create", "ops", "--members", "nanna", "--members", "utu")
    assert result == (0, "created group:ops (members: enki, nanna, utu)\n", "")


def test_create_twice_fails(cb: Callboard, ops: None) -> None:
    result = cb("--as", "nanna", "group", "create", "ops", "--members", "utu")
    assert result == (1, "", "callboard: group:ops already exists\n")


def test_create_with_an_unknown_member_creates_nothing(cb: Callboard) -> None:
    result = cb("--as", "enki", "group", "create", "ops", "--members", "nanna,ghost")
    assert result == (3, "", "callboard: no participant 'ghost'\n")
    assert rows("SELECT count(*) FROM conversations") == [(0,)]


def test_an_invalid_group_name_is_a_usage_error(cb: Callboard) -> None:
    assert cb("--as", "enki", "group", "create", "Ops", "--members", "nanna").code == 2


def test_add_and_remove_members(cb: Callboard, ops: None) -> None:
    assert cb("--as", "nanna", "group", "add", "ops", "utu") == (0, "added utu to group:ops\n", "")
    assert cb("--as", "nanna", "group", "add", "ops", "utu") == (
        0,
        "utu is already in group:ops\n",
        "",
    )
    assert cb("--as", "utu", "group", "remove", "ops", "niels") == (
        0,
        "removed niels from group:ops\n",
        "",
    )
    assert rows("SELECT handle FROM members ORDER BY handle") == [("enki",), ("nanna",), ("utu",)]
    assert cb("--as", "utu", "group", "remove", "ops", "niels") == (
        3,
        "",
        "callboard: 'niels' is not a member of group:ops\n",
    )


def test_a_non_member_cannot_change_send_to_or_read_a_group(cb: Callboard, ops: None) -> None:
    denied = "callboard: 'utu' is not a member of group:ops\n"
    assert cb("--as", "utu", "group", "add", "ops", "utu") == (3, "", denied)
    assert cb("--as", "utu", "group", "send", "ops", "hi") == (3, "", denied)
    assert cb("--as", "utu", "read", "group:ops") == (3, "", denied)
    assert cb("--as", "utu", "history", "group:ops") == (3, "", denied)
    assert rows("SELECT count(*) FROM messages") == [(0,)]


def test_sending_to_a_missing_group_is_not_found(cb: Callboard) -> None:
    assert cb("--as", "enki", "group", "send", "nope", "hi") == (
        3,
        "",
        "callboard: no conversation group:nope\n",
    )


def test_only_mentioned_members_ring(cb: Callboard, ops: None) -> None:
    result = cb("--as", "enki", "group", "send", "ops", "@nanna look; cc @utu and enki@x.com")
    assert result == (0, "sent cb_000000000001 to group:ops (mentions @nanna)\n", "")
    assert rows("SELECT message_id, handle FROM mentions") == [("cb_000000000001", "nanna")]
    assert _receipts() == [("nanna", "idle", "pending"), ("niels", "none", None)]


def test_now_rings_mentions_as_an_interrupt(cb: Callboard, ops: None) -> None:
    assert cb("--as", "enki", "group", "send", "ops", "@nanna @niels now", "--now").code == 0
    assert rows("SELECT handle FROM mentions ORDER BY handle") == [("nanna",), ("niels",)]
    assert _receipts() == [("nanna", "now", "pending"), ("niels", "none", None)]


def test_group_text_comes_from_stdin_and_reply_to_stays_in_the_group(
    cb: Callboard, ops: None
) -> None:
    assert cb("--as", "enki", "group", "send", "ops", stdin="plan\n").code == 0
    reply = cb("--as", "nanna", "group", "send", "ops", "ok", "--reply-to", "cb_000000000001")
    assert reply.code == 0
    assert rows("SELECT body, parent_id FROM messages ORDER BY seq") == [
        ("plan", None),
        ("ok", "cb_000000000001"),
    ]
    assert cb("--as", "enki", "dm", "nanna", "x", "--reply-to", "cb_000000000001").code == 2


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("@nanna hi", ("nanna",)),
        ("hi @nanna, and @utu.", ("nanna", "utu")),
        ("(@nanna)", ("nanna",)),
        ("@ghost and @enki", ()),
        ("mail nanna@example.com or a.@nanna", ()),
        ("@nanna @nanna", ("nanna",)),
        ("@Nanna", ()),
        ("@nanna- thanks", ("nanna",)),
        ("@nanna_, ok", ("nanna",)),
        ("@nannaX", ()),
        ("@nAnna", ()),
        ("@nannaé", ()),
        ("@nanna-é", ()),
        ("@nanna-X", ()),
        ("@nanna\u2019s turn", ("nanna",)),
        ("@nanna@utu", ()),
        ("@re-view-", ("re-view-",)),
        ("@re-view- and @re-view", ("re-view-", "re-view")),
    ],
)
def test_mention_parsing(body: str, expected: tuple[str, ...]) -> None:
    assert mentioned(body, {"enki", "nanna", "utu", "re-view-", "re-view"}, "enki") == expected


def test_a_group_whose_last_member_leaves_is_gone_and_its_name_is_free(
    cb: Callboard, tmp_path: Path
) -> None:
    note = tmp_path / "note.txt"
    note.write_text("kept elsewhere\n")
    assert cb("--as", "enki", "group", "create", "solo", "--members", "nanna").code == 0
    assert cb("--as", "enki", "group", "send", "solo", "@nanna hi", "--attach", str(note)).code == 0
    assert cb("--as", "enki", "group", "remove", "solo", "nanna").code == 0
    assert cb("--as", "enki", "group", "remove", "solo", "enki") == (
        0,
        "removed enki from group:solo\ngroup:solo had no members left and is gone; its name is free\n",
        "",
    )
    assert rows("SELECT count(*) FROM messages WHERE conversation_id = 'group:solo'") == [(0,)]
    assert rows("SELECT count(*) FROM attachments") == [(0,)]
    assert cb("--as", "utu", "group", "create", "solo", "--members", "niels") == (
        0,
        "created group:solo (members: niels, utu)\n",
        "",
    )


def test_group_changes_print_json(cb: Callboard) -> None:
    ok = {"schema_version": 1, "status": "ok", "warnings": []}
    group = {"conversation": "group:ops", "handle": "utu"}
    created = cb("--as", "enki", "group", "create", "ops", "--members", "nanna", "--json").json()
    assert created == {
        **ok,
        "conversation": "group:ops",
        "name": "ops",
        "project": None,
        "members": ["enki", "nanna"],
    }
    added = cb("--as", "enki", "group", "add", "ops", "utu", "--json").json()
    assert added == {**ok, **group, "added": True}
    again = cb("--as", "enki", "group", "add", "ops", "utu", "--json").json()
    assert again == {**ok, **group, "added": False}
    removed = cb("--as", "enki", "group", "remove", "ops", "utu", "--json").json()
    assert removed == {**ok, **group, "group_deleted": False}
