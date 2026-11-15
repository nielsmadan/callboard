import json
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from callboard.bellhop_client import (
    Reply,
    error_code,
    parse_agents,
    parse_message,
    parse_sessions,
    parse_status,
    parse_whoami,
    require_ok,
    warnings_of,
)
from callboard.errors import CallboardError

CONTRACT = Path(__file__).resolve().parent
FIXTURES = sorted(path.name for path in CONTRACT.glob("*.json"))
UNUSED = {"bind.json", "bind-conflict.json", "doctor-failed.json", "inbox.json"}
SEND_ERRORS = {
    "send-hls-unavailable.json": ("hls_unavailable", 5),
    "send-no-route.json": ("no_route", 4),
    "send-target-ambiguous.json": ("target_ambiguous", 3),
    "send-target-not-found.json": ("target_not_found", 3),
    "send-usage.json": ("usage", 2),
}


def _load(name: str) -> dict[str, object]:
    payload = json.loads((CONTRACT / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert payload["schema_version"] == 1
    return payload


def test_every_fixture_is_parsed_or_named_unused() -> None:
    prefixes = ("whoami", "send-", "status", "sessions", "agents")
    assert [name for name in FIXTURES if not name.startswith(prefixes)] == sorted(UNUSED)


@pytest.mark.parametrize(
    "name",
    [name for name in FIXTURES if name.startswith("send-") and name not in SEND_ERRORS],
)
def test_every_stored_send_carries_a_message(name: str) -> None:
    payload = _load(name)
    message = parse_message(payload["message"])
    assert message is not None
    assert message.id == "bh_000000000001"
    if payload["status"] == "error":
        assert error_code(payload) in {"push_rejected", "interrupted", "internal_error"}


@pytest.mark.parametrize(("name", "expected"), sorted(SEND_ERRORS.items()))
def test_every_refused_send_carries_its_code_and_no_message(
    name: str, expected: tuple[str, int]
) -> None:
    payload = _load(name)
    assert (error_code(payload), payload["exit_code"], "message" in payload) == (*expected, False)


def test_the_unconfirmed_send_passes_its_warning() -> None:
    assert warnings_of(_load("send-unconfirmed.json")) == [
        "cannot confirm: no transcript to read for this session"
    ]


def test_whoami_results_parse_or_map_to_their_error() -> None:
    session = parse_whoami(require_ok(Reply(0, _load("whoami.json")), "whoami"))
    assert (session.agent, session.harness, session.title) == ("enki", "claude", "alpha")
    unnamed = parse_whoami(require_ok(Reply(0, _load("whoami-no-agent.json")), "whoami"))
    assert (unnamed.agent, unnamed.harness) == (None, "codex")
    with pytest.raises(CallboardError) as caught:
        require_ok(Reply(3, _load("whoami-caller-unknown.json")), "whoami")
    assert caught.value.code == "not_in_session"


def test_status_results_parse() -> None:
    real = _load("status.json")
    assert {key: value.state for key, value in parse_status(real).items()} == {
        "bh_000000000002": "sent",
        "bh_000000000003": "pending",
    }
    assert warnings_of(real) == ["unknown message id bh_000000000001"]
    assert parse_status(_load("status-confirmed.json"))["bh_000000000001"].state == "confirmed"
    assert parse_status(_load("status-pending.json"))["bh_000000000001"].state == "pending"


def test_sessions_and_agents_parse() -> None:
    assert parse_sessions(_load("sessions.json")) == {
        "2e2042a9-937c-4e03-ba25-74b5ba14a58f",
        "enki",
        "2e20ffff-0000-4000-8000-000000000002",
        "7f00aa11-0000-4000-8000-000000000003",
        "7f00bb22-0000-4000-8000-000000000004",
    }
    assert parse_agents(_load("agents.json")) == {"enki", "nanna", "scribe"}


def test_degraded_and_held_sends_are_told_apart_by_urgency() -> None:
    degraded = parse_message(_load("send-degraded.json")["message"])
    held = parse_message(_load("send-held.json")["message"])
    assert degraded is not None
    assert held is not None
    assert (degraded.urgency, degraded.degraded_from, degraded.state) == ("now", "now", "sent")
    assert (held.urgency, held.degraded_from, held.state) == ("hold", "idle", "pending")


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
