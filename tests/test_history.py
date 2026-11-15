import pytest

from helpers import Callboard, chat_scenario, load_golden, rows


@pytest.fixture(autouse=True)
def scenario(cb: Callboard) -> None:
    chat_scenario(cb)


def test_history_json_matches_the_golden(cb: Callboard) -> None:
    result = cb("--as", "nanna", "history", "group:ops", "--json")
    assert (result.code, result.err) == (0, "")
    assert result.json() == load_golden("history.json")


def test_limit_keeps_the_latest_messages_in_order(cb: Callboard) -> None:
    for text in ("three", "four", "five"):
        assert cb("--as", "enki", "group", "send", "ops", text).code == 0
    result = cb("--as", "nanna", "history", "group:ops", "--limit", "3", "--json")
    assert [item["body"] for item in result.json()["messages"]] == ["three", "four", "five"]
    everything = cb("--as", "nanna", "history", "group:ops", "--json")
    assert len(everything.json()["messages"]) == 5


def test_history_by_message_id_shows_its_conversation_and_marks_nothing(cb: Callboard) -> None:
    result = cb("--as", "nanna", "history", "cb_000000000001")
    assert result == (
        0,
        "cb_000000000001  2026-11-14T09:00:00Z  enki: first line\n  second line\n",
        "",
    )
    assert rows("SELECT count(*) FROM receipts WHERE read_at IS NOT NULL") == [(0,)]


def test_history_of_an_empty_group_says_so(cb: Callboard) -> None:
    assert cb("--as", "enki", "group", "create", "quiet", "--members", "nanna").code == 0
    assert cb("--as", "nanna", "history", "group:quiet") == (0, "no messages in group:quiet\n", "")


@pytest.mark.parametrize("limit", ["0", "-1", "x"])
def test_a_non_positive_limit_is_a_usage_error(cb: Callboard, limit: str) -> None:
    assert cb("--as", "nanna", "history", "group:ops", "--limit", limit).code == 2
