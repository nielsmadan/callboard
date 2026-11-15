import json
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from callboard.bellhop_client import (
    Reply,
    parse_agents,
    parse_message,
    parse_sessions,
    parse_status,
    parse_whoami,
    require_ok,
)
from callboard.errors import CallboardError

CONTRACT = Path(__file__).resolve().parent
FIXTURES = sorted(path.name for path in CONTRACT.glob("*.json"))


def _load(name: str) -> dict[str, object]:
    payload = json.loads((CONTRACT / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert payload["schema_version"] == 1
    return payload


def test_every_fixture_has_a_parser() -> None:
    prefixes = ("whoami-", "send-", "status", "sessions", "agents")
    assert [name for name in FIXTURES if not name.startswith(prefixes)] == []


@pytest.mark.parametrize("name", [name for name in FIXTURES if name.startswith("send-")])
def test_every_send_result_carries_a_message(name: str) -> None:
    payload = _load(name)
    message = parse_message(payload["message"])
    assert message is not None
    assert message.id == "bh_7f3a9c2e41d0"
    assert (payload["status"] == "ok") == (message.state != "failed")


def test_whoami_results_parse_or_map_to_their_error() -> None:
    session = parse_whoami(require_ok(Reply(0, _load("whoami-agent.json")), "whoami"))
    assert (session.agent, session.harness) == ("enki", "claude")
    unnamed = parse_whoami(require_ok(Reply(0, _load("whoami-session.json")), "whoami"))
    assert unnamed.agent is None
    with pytest.raises(CallboardError) as caught:
        require_ok(Reply(3, _load("whoami-not-found.json")), "whoami")
    assert caught.value.code == "not_in_session"


def test_status_results_parse() -> None:
    assert {key: value.state for key, value in parse_status(_load("status.json")).items()} == {
        "bh_7f3a9c2e41d0": "confirmed"
    }
    assert _load("status.json")["warnings"] == ["unknown message id bh_000000000000"]
    assert parse_status(_load("status-pending.json"))["bh_7f3a9c2e41d0"].state == "pending"


def test_sessions_and_agents_parse() -> None:
    assert parse_sessions(_load("sessions.json")) == {
        "2e2042a9-937c-4e03-ba25-74b5ba14a58f",
        "enki",
        "7c1d0b5e-4a2f-4c8e-9d3b-1f6a2e8c0d47",
    }
    assert parse_agents(_load("agents.json")) == {"enki", "utu", "ninsun"}


def test_a_degraded_send_names_what_it_was_degraded_from() -> None:
    message = parse_message(_load("send-degraded.json")["message"])
    assert message is not None
    assert (message.state, message.degraded_from) == ("pending", "idle")


@pytest.mark.parametrize(
    "value",
    [None, [], {"id": "bh_1"}, {"id": 1, "state": "sent"}, {"id": "bh_1", "state": "lost"}],
)
def test_malformed_messages_are_rejected(value: object) -> None:
    assert parse_message(value) is None


@pytest.mark.parametrize(
    ("parser", "payload"),
    [(parse_status, {}), (parse_sessions, {"sessions": {}}), (parse_agents, {"agents": None})],
)
def test_missing_lists_are_a_bellhop_failure(
    parser: Callable[[Mapping[str, object]], object], payload: dict[str, object]
) -> None:
    with pytest.raises(CallboardError) as caught:
        parser(payload)
    assert caught.value.code == "bellhop_failed"
