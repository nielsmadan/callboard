import pytest

from helpers import Callboard, chat_scenario, load_golden, seed

pytestmark = pytest.mark.usefixtures("ringing")


def test_inbox_json_matches_the_golden(cb: Callboard) -> None:
    chat_scenario(cb)
    result = cb("--as", "nanna", "inbox", "--json")
    assert (result.code, result.err) == (0, "")
    assert result.json() == load_golden("inbox.json")


def test_mentions_come_first_then_the_most_recent(cb: Callboard) -> None:
    seed(("enki", "enki"), ("nanna", "sess-nanna"), ("niels", None), ("utu", "utu"))
    steps = [
        ("--as", "enki", "group", "create", "ops", "--members", "nanna"),
        ("--as", "enki", "group", "create", "lab", "--members", "nanna"),
        ("--as", "enki", "group", "send", "ops", "@nanna older mention"),
        ("--as", "enki", "group", "send", "lab", "no mention"),
        ("--as", "niels", "dm", "nanna", "newest"),
        ("--as", "utu", "dm", "nanna", "one"),
        ("--as", "utu", "dm", "nanna", "two"),
        ("--as", "niels", "dm", "nanna", "newest again"),
    ]
    assert [cb(*step).code for step in steps] == [0] * len(steps)
    assert cb("--as", "nanna", "inbox") == (
        0,
        "group:ops  1 unread, 1 mention\n@niels     2 unread\n@utu       2 unread\ngroup:lab  1 unread\n",
        "",
    )


def test_reading_empties_the_inbox(cb: Callboard) -> None:
    chat_scenario(cb)
    assert cb("--as", "nanna", "read", "group:ops").code == 0
    assert cb("--as", "nanna", "read", "@enki").code == 0
    assert cb("--as", "nanna", "inbox") == (0, "no unread messages\n", "")
    assert cb("--as", "nanna", "inbox", "--json").json()["conversations"] == []


def test_the_sender_has_nothing_unread_from_themselves(cb: Callboard) -> None:
    chat_scenario(cb)
    assert cb("--as", "enki", "inbox", "--json").json()["conversations"] == [
        {
            "ref": "group:ops",
            "id": "group:ops",
            "kind": "group",
            "name": "ops",
            "subject": None,
            "project": "bellhop",
            "unread": 1,
            "mentions": 0,
            "sender": "niels",
        }
    ]


def test_a_removed_member_no_longer_sees_the_group_until_re_added(cb: Callboard) -> None:
    chat_scenario(cb)
    assert cb("--as", "enki", "group", "remove", "ops", "nanna").code == 0
    assert [
        entry["ref"] for entry in cb("--as", "nanna", "inbox", "--json").json()["conversations"]
    ] == ["@enki"]
    assert cb("--as", "enki", "group", "add", "ops", "nanna").code == 0
    assert cb("--as", "nanna", "inbox", "--json").json() == load_golden("inbox.json")
