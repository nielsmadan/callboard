import pytest

from callboard.text import visible
from helpers import Callboard, FakeBellhop, chat_scenario, load_golden, rows

pytestmark = pytest.mark.usefixtures("ringing")


@pytest.fixture(autouse=True)
def scenario(cb: Callboard, ringing: FakeBellhop) -> None:
    chat_scenario(cb)


def _unread(recipient: str) -> list[str]:
    found = rows(
        "SELECT message_id FROM receipts WHERE recipient = ? AND read_at IS NULL ORDER BY rowid",
        recipient,
    )
    return [row[0] for row in found]


def test_read_json_matches_the_golden(cb: Callboard) -> None:
    result = cb("--as", "nanna", "read", "group:ops", "--json")
    assert (result.code, result.err) == (0, "")
    assert result.json() == load_golden("read.json")


def test_read_prints_unread_in_order_and_marks_only_the_callers_receipts(cb: Callboard) -> None:
    assert _unread("niels") == ["cb_000000000002"]
    result = cb("--as", "nanna", "read", "group:ops")
    assert result == (
        0,
        (
            "cb_000000000002  2026-11-14T09:00:00Z  enki: @nanna please review\n"
            "cb_000000000003  2026-11-14T09:00:00Z  niels (reply to cb_000000000002): on it\n"
        ),
        "",
    )
    assert _unread("nanna") == ["cb_000000000001"]
    assert _unread("niels") == ["cb_000000000002"]
    assert cb("--as", "nanna", "read", "group:ops") == (
        0,
        "no unread messages in group:ops\n",
        "",
    )


def test_peek_prints_without_marking(cb: Callboard) -> None:
    peeked = cb("--as", "nanna", "read", "@enki", "--peek", "--json")
    assert peeked.json()["peek"] is True
    assert [item["id"] for item in peeked.json()["messages"]] == ["cb_000000000001"]
    assert _unread("nanna") == ["cb_000000000001", "cb_000000000002", "cb_000000000003"]
    text = cb("--as", "nanna", "read", "@enki")
    assert text.out == "cb_000000000001  2026-11-14T09:00:00Z  enki: first line\n  second line\n"
    assert _unread("nanna") == ["cb_000000000002", "cb_000000000003"]


def test_read_one_message_marks_only_that_message(cb: Callboard) -> None:
    result = cb("--as", "nanna", "read", "cb_000000000003", "--json")
    assert (result.json()["ref"], [item["id"] for item in result.json()["messages"]]) == (
        "group:ops",
        ["cb_000000000003"],
    )
    assert _unread("nanna") == ["cb_000000000001", "cb_000000000002"]


def test_reading_others_conversations_or_unknown_messages_is_refused(cb: Callboard) -> None:
    assert cb("--as", "niels", "read", "@enki") == (
        3,
        "",
        "callboard: no conversation @enki\n",
    )
    assert cb("--as", "niels", "read", "cb_000000000001") == (
        3,
        "",
        "callboard: 'niels' is not a member of dm:enki:nanna\n",
    )
    assert cb("--as", "niels", "read", "cb_0000000000ff") == (
        3,
        "",
        "callboard: no message cb_0000000000ff\n",
    )
    assert cb("--as", "niels", "read", "ops").code == 2


def test_receipts_json_matches_the_golden(cb: Callboard) -> None:
    assert cb("--as", "nanna", "read", "group:ops").code == 0
    result = cb("--as", "enki", "receipts", "cb_000000000002", "--json")
    assert (result.code, result.err) == (0, "")
    assert result.json() == load_golden("receipts.json")


def test_receipts_text_lists_ping_and_read_state(cb: Callboard) -> None:
    assert cb("--as", "enki", "receipts", "cb_000000000002") == (
        0,
        (
            "recipient  ping  state    read\n"
            "nanna      idle  pending  -\n"
            "niels      none  -        -\n"
        ),
        "",
    )


def test_receipts_need_membership(cb: Callboard) -> None:
    assert cb("--as", "niels", "receipts", "cb_000000000001", "--json").json()["error"] == {
        "code": "not_a_member",
        "message": "'niels' is not a member of dm:enki:nanna",
    }


def test_bodies_show_control_and_direction_characters_escaped_but_keep_lines_and_tabs(
    cb: Callboard,
) -> None:
    body = f"ok\rcb_000000000001  forged\n\x1b]0;title\x07\tsee {chr(0x202E)}fdp.sh"
    assert cb("--as", "enki", "dm", "nanna", body).code == 0
    printed = cb("--as", "nanna", "history", "@enki").out.splitlines()
    assert printed[-2:] == [
        "cb_000000000004  2026-11-14T09:00:00Z  enki: ok\\rcb_000000000001  forged",
        "  \\x1b]0;title\\x07\tsee \\u202efdp.sh",
    ]
    history = cb("--as", "nanna", "history", "@enki", "--json").json()
    assert history["messages"][-1]["body"] == body


@pytest.mark.parametrize(
    ("code", "escape"),
    [
        (0x2028, "\\u2028"),
        (0x2029, "\\u2029"),
        (0x2066, "\\u2066"),
        (0x2067, "\\u2067"),
        (0x2068, "\\u2068"),
        (0x2069, "\\u2069"),
        (0x80, "\\x80"),
        (0x85, "\\x85"),
        (0x9F, "\\x9f"),
    ],
)
def test_line_separators_isolates_and_c1_controls_are_shown_escaped(code: int, escape: str) -> None:
    assert visible(f"a{chr(code)}b\tc\nd") == f"a{escape}b\tc\nd"
