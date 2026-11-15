import json
import os
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import TypedDict

import pytest

from callboard.paths import store_path
from helpers import FAKES, Callboard, FakeBellhop, rows, seed

SESSION = "sess-nanna"


class Behaviour(TypedDict, total=False):
    sleep: float
    exit_code: int
    raw: str


@pytest.fixture(autouse=True)
def people(bellhop: FakeBellhop) -> None:
    seed(("enki", "enki"), ("nanna", SESSION), ("utu", "utu"), ("niels", None))
    bellhop.replay("send", "send-pending.json")


def _send_argv(route: str, level: str, sender: str, key: str, *, wake: bool = True) -> list[str]:
    return [
        "send",
        route,
        "--urgency",
        level,
        *(["--wake"] if wake else []),
        "--or-hold",
        "--from",
        sender,
        "--key",
        key,
        "--confirm",
        "5",
        "--json",
    ]


def _receipt(message_id: str, recipient: str) -> tuple[str | None, str | None, str | None, int]:
    found = rows(
        "SELECT bellhop_id, ping_state, read_at, inline FROM receipts"
        " WHERE message_id = ? AND recipient = ?",
        message_id,
        recipient,
    )
    return found[0]


def test_a_direct_message_rings_at_idle_with_wake_and_the_full_text(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    assert cb("--as", "enki", "dm", "nanna", "hello there") == (
        0,
        "sent cb_000000000001 to @nanna\n",
        "",
    )
    assert bellhop.entries() == [
        {
            "argv": _send_argv(SESSION, "idle", "enki", "cb_000000000001:nanna"),
            "stdin": "callboard cb_000000000001 dm from enki: hello there",
        }
    ]
    assert _receipt("cb_000000000001", "nanna") == ("bh_7f3a9c2e41d0", "pending", None, 1)


def test_now_rings_as_an_interrupt(cb: Callboard, bellhop: FakeBellhop) -> None:
    assert cb("--as", "enki", "dm", "nanna", "stop", "--now").code == 0
    assert bellhop.calls() == [_send_argv(SESSION, "now", "enki", "cb_000000000001:nanna")]


def test_no_ping_and_routeless_recipients_are_never_rung(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    assert cb("--as", "enki", "dm", "nanna", "quiet", "--no-ping").code == 0
    assert cb("--as", "enki", "dm", "niels", "human").code == 0
    assert bellhop.calls() == []


def test_a_group_rings_only_mentions_with_the_group_label(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    assert cb("--as", "enki", "group", "create", "ops", "--members", "nanna,utu,niels").code == 0
    assert cb("--as", "enki", "group", "send", "ops", "@utu please look").code == 0
    assert bellhop.entries() == [
        {
            "argv": _send_argv("utu", "idle", "enki", "cb_000000000001:utu"),
            "stdin": "callboard cb_000000000001 group ops from enki: @utu please look",
        }
    ]


def test_mail_is_a_held_doorbell_without_wake(cb: Callboard, bellhop: FakeBellhop) -> None:
    sent = cb(
        "--as", "enki", "mail", "send", "--to", "nanna", "--subject", "Release plan", "ship it"
    )
    assert sent.code == 0
    assert bellhop.entries() == [
        {
            "argv": _send_argv(SESSION, "hold", "enki", "cb_000000000001:nanna", wake=False),
            "stdin": 'callboard cb_000000000001 mail "Release plan" from enki (7 chars);'
            " read: callboard read cb_000000000001",
        }
    ]
    assert _receipt("cb_000000000001", "nanna")[3] == 0


def test_short_urgent_mail_is_inline(cb: Callboard, bellhop: FakeBellhop) -> None:
    sent = cb(
        "--as", "enki", "mail", "send", "--to", "nanna", "--subject", "Now", "ship", "--urgent"
    )
    assert sent.code == 0
    assert bellhop.entries() == [
        {
            "argv": _send_argv(SESSION, "idle", "enki", "cb_000000000001:nanna"),
            "stdin": 'callboard cb_000000000001 mail "Now" from enki: ship',
        }
    ]


@pytest.mark.parametrize(
    ("length", "inline"),
    [(500, True), (501, False)],
)
def test_the_inline_threshold_is_500_characters(
    cb: Callboard, bellhop: FakeBellhop, length: int, inline: bool
) -> None:
    body = "é" * length
    assert cb("--as", "enki", "dm", "nanna", body).code == 0
    text = bellhop.entries()[0]["stdin"]
    if inline:
        assert text == f"callboard cb_000000000001 dm from enki: {body}"
    else:
        assert text == (
            "callboard cb_000000000001 dm from enki (501 chars);"
            " read: callboard read cb_000000000001"
        )


def test_an_attachment_forces_a_doorbell(
    cb: Callboard, bellhop: FakeBellhop, tmp_path: Path
) -> None:
    files = []
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text(name)
        files += ["--attach", str(tmp_path / name)]
    assert cb("--as", "enki", "dm", "nanna", "see", *files).code == 0
    assert bellhop.entries()[0]["stdin"] == (
        "callboard cb_000000000001 dm from enki (3 chars, 2 attachments);"
        " read: callboard read cb_000000000001"
    )
    assert _receipt("cb_000000000001", "nanna")[3] == 0


def test_a_long_body_counts_with_thousands_separators(cb: Callboard, bellhop: FakeBellhop) -> None:
    assert cb("--as", "enki", "dm", "nanna", "x" * 1840).code == 0
    assert "(1,840 chars)" in bellhop.entries()[0]["stdin"]


def _five_mentions(cb: Callboard) -> None:
    seed(*((f"m{index}", f"route-{index}") for index in range(5)))
    members = ",".join(f"m{index}" for index in range(5))
    assert cb("--as", "enki", "group", "create", "ops", "--members", members).code == 0


def test_mentions_ring_concurrently(cb: Callboard, bellhop: FakeBellhop) -> None:
    _five_mentions(cb)
    bellhop.behave(sleep=0.6)
    started = time.monotonic()
    result = cb("--as", "enki", "group", "send", "ops", "@m0 @m1 @m2 @m3 @m4 go", deadline=10)
    elapsed = time.monotonic() - started
    assert (result.code, result.err) == (0, "")
    assert elapsed < 2.4
    assert sorted(call[1] for call in bellhop.calls()) == [f"route-{index}" for index in range(5)]


def test_a_slow_bellhop_cannot_hold_the_command_past_the_deadline(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    _five_mentions(cb)
    bellhop.behave(sleep=5)
    started = time.monotonic()
    result = cb(
        "--as", "enki", "group", "send", "ops", "@m0 @m1 @m2 @m3 @m4 go", "--json", deadline=0.5
    )
    elapsed = time.monotonic() - started
    assert result.code == 0
    assert elapsed < 3
    warnings = result.json()["warnings"]
    assert len(warnings) == 5
    assert all("bellhop send timed out after" in warning for warning in warnings)
    assert rows("SELECT DISTINCT ping_state, bellhop_id FROM receipts WHERE ping != 'none'") == [
        ("pending", None)
    ]


def test_a_confirmed_inline_ping_counts_as_read(cb: Callboard, bellhop: FakeBellhop) -> None:
    bellhop.replay("send", "send-confirmed.json")
    assert cb("--as", "enki", "dm", "nanna", "short").code == 0
    assert _receipt("cb_000000000001", "nanna") == (
        "bh_7f3a9c2e41d0",
        "confirmed",
        "2026-11-14T09:00:00Z",
        1,
    )
    assert cb("--as", "nanna", "inbox").out == "no unread messages\n"


def test_a_confirmed_doorbell_is_not_read(cb: Callboard, bellhop: FakeBellhop) -> None:
    bellhop.replay("send", "send-confirmed.json")
    assert cb("--as", "enki", "dm", "nanna", "x" * 600).code == 0
    assert _receipt("cb_000000000001", "nanna") == ("bh_7f3a9c2e41d0", "confirmed", None, 0)


def test_a_later_refresh_upgrades_with_one_status_call(cb: Callboard, bellhop: FakeBellhop) -> None:
    assert cb("--as", "enki", "dm", "nanna", "one").code == 0
    assert cb("--as", "enki", "dm", "nanna", "two").code == 0
    assert _receipt("cb_000000000002", "nanna") == ("bh_7f3a9c2e41d0", "pending", None, 1)
    bellhop.replay("status", "status.json")
    inbox = cb("--as", "nanna", "inbox", "--json")
    assert inbox.json()["conversations"] == []
    assert inbox.json()["warnings"] == [
        "refreshing receipts: bellhop status: unknown message id bh_000000000000"
    ]
    status_calls = [call for call in bellhop.calls() if call[0] == "status"]
    assert status_calls == [["status", "bh_7f3a9c2e41d0", "--json"]]
    assert _receipt("cb_000000000001", "nanna") == (
        "bh_7f3a9c2e41d0",
        "confirmed",
        "2026-11-14T09:00:00Z",
        1,
    )


def test_receipts_refresh_their_message(cb: Callboard, bellhop: FakeBellhop) -> None:
    assert cb("--as", "enki", "dm", "nanna", "one").code == 0
    bellhop.replay("status", "status.json")
    receipts = cb("--as", "enki", "receipts", "cb_000000000001", "--json").json()["receipts"]
    assert (receipts[0]["ping_state"], receipts[0]["read_at"]) == (
        "confirmed",
        "2026-11-14T09:00:00Z",
    )


def test_held_or_old_or_unrung_receipts_are_not_refreshed(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    assert cb("--as", "enki", "mail", "send", "--to", "nanna", "--subject", "s", "held").code == 0
    assert cb("--as", "enki", "dm", "nanna", "old").code == 0
    with closing(sqlite3.connect(store_path(os.environ))) as conn:
        conn.execute(
            "UPDATE messages SET created_at = '2026-11-14T08:40:00Z' WHERE id = 'cb_000000000003'"
        )
        conn.commit()
    assert cb("--as", "enki", "dm", "nanna", "unrung", "--no-ping").code == 0
    bellhop.replay("status", "status.json")
    assert cb("--as", "nanna", "inbox").code == 0
    assert [call for call in bellhop.calls() if call[0] == "status"] == []


@pytest.mark.parametrize(
    ("behaviour", "state", "warning"),
    [
        (
            {
                "raw": json.dumps(
                    {
                        "schema_version": 1,
                        "status": "error",
                        "exit_code": 4,
                        "error": {"code": "no_route", "message": "no usable route"},
                    }
                ),
                "exit_code": 4,
            },
            "failed",
            "bellhop send: no usable route",
        ),
        (
            {
                "raw": json.dumps(
                    {
                        "schema_version": 1,
                        "status": "error",
                        "exit_code": 3,
                        "error": {"code": "target_not_found", "message": "no target sess-nanna"},
                    }
                ),
                "exit_code": 3,
            },
            "failed",
            "bellhop send: no target sess-nanna",
        ),
        (
            {
                "raw": json.dumps(
                    {
                        "schema_version": 1,
                        "status": "error",
                        "exit_code": 5,
                        "error": {"code": "hls_unavailable", "message": "hls timed out"},
                    }
                ),
                "exit_code": 5,
            },
            "pending",
            "bellhop send: hls timed out",
        ),
        (
            {"raw": "not json at all"},
            "pending",
            "bellhop send printed no schema_version 1 JSON (exit 0)",
        ),
        (
            {"raw": '{"schema_version": 1, "status": "ok", "message": {"id": 7}}'},
            "pending",
            "bellhop send returned no message",
        ),
        ({"sleep": 3}, "pending", "bellhop send timed out after 0.5s"),
    ],
)
def test_a_failing_bellhop_never_loses_the_message(
    cb: Callboard, bellhop: FakeBellhop, behaviour: Behaviour, state: str, warning: str
) -> None:
    bellhop.behave(**behaviour)
    result = cb("--as", "enki", "dm", "nanna", "hello", "--json", deadline=0.5)
    assert result.code == 0
    expected = f"ping nanna for cb_000000000001: {warning}"
    assert result.json()["warnings"] == [expected]
    assert result.err == f"callboard: {expected}\n"
    assert rows("SELECT count(*) FROM messages") == [(1,)]
    assert _receipt("cb_000000000001", "nanna")[:2] == (None, state)


def test_a_missing_bellhop_leaves_the_receipt_pending(
    cb: Callboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", os.defpath)
    result = cb("--as", "enki", "dm", "nanna", "hello")
    assert result == (
        0,
        "sent cb_000000000001 to @nanna\n",
        "callboard: ping nanna for cb_000000000001: bellhop not found on PATH\n",
    )
    assert _receipt("cb_000000000001", "nanna")[:2] == (None, "pending")


def test_a_rejected_push_records_the_bellhop_message_as_failed(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    bellhop.replay("send", "send-failed.json")
    result = cb("--as", "enki", "dm", "nanna", "hello")
    assert result.err == (
        "callboard: ping nanna for cb_000000000001: bellhop send:"
        " relay rejected the message: session closing\n"
    )
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_7f3a9c2e41d0", "failed")


def test_a_degraded_ping_is_kept_and_reported(cb: Callboard, bellhop: FakeBellhop) -> None:
    bellhop.replay("send", "send-degraded.json")
    result = cb("--as", "enki", "dm", "nanna", "hello")
    assert result.err == (
        "callboard: ping nanna for cb_000000000001: held by bellhop; no usable route for idle\n"
    )
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_7f3a9c2e41d0", "pending")


def test_reping_rings_only_receipts_bellhop_never_accepted(
    cb: Callboard, bellhop: FakeBellhop, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert cb("--as", "enki", "dm", "nanna", "rung").code == 0
    bellhop.behave(raw="garbage")
    assert cb("--as", "enki", "dm", "utu", "missed").code == 0
    monkeypatch.delenv("FAKE_BELLHOP_RAW")
    bellhop.replay("send", "send-replayed.json")
    bellhop.replay("sessions", "sessions.json")
    bellhop.replay("agents", "agents.json")
    before = len(bellhop.calls())
    result = cb("doctor", "--reping", "--json")
    assert result.code == 0
    assert result.json()["repinged"] == 1
    sends = [call for call in bellhop.calls()[before:] if call[0] == "send"]
    assert sends == [_send_argv("utu", "idle", "enki", "cb_000000000002:utu")]
    assert _receipt("cb_000000000002", "utu")[:2] == ("bh_7f3a9c2e41d0", "sent")
    assert cb("doctor", "--reping", "--json").json()["repinged"] == 0


def test_an_unwritable_store_exits_1_and_never_calls_bellhop(
    cb: Callboard, bellhop: FakeBellhop, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_home = tmp_path / "readonly"
    data_home.mkdir(mode=0o500)
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    assert cb("--as", "enki", "dm", "nanna", "hello").code == 1
    assert bellhop.calls() == []


def test_ping_command_from_config_replaces_bellhop(
    cb: Callboard, bellhop: FakeBellhop, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrapper = tmp_path / "wrapper"
    wrapper.write_text(
        f'#!/bin/sh\necho "$@" > {tmp_path / "wrapped"}\nshift 2\nexec bellhop "$@"\n'
    )
    wrapper.chmod(0o755)
    config = Path(os.environ["XDG_CONFIG_HOME"]) / "callboard" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f'ping_command = ["{wrapper}", "--profile", "x"]\n')
    assert cb("--as", "enki", "dm", "nanna", "hello").err == ""
    assert (tmp_path / "wrapped").read_text().split()[:3] == ["--profile", "x", "send"]


@pytest.mark.parametrize("value", ["[]", '"bellhop"', "[1]", '[""]'])
def test_an_invalid_ping_command_is_a_config_error_before_storing(
    cb: Callboard, value: str
) -> None:
    config = Path(os.environ["XDG_CONFIG_HOME"]) / "callboard" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f"ping_command = {value}\n")
    result = cb("--as", "enki", "dm", "nanna", "hello")
    assert result.code == 2
    assert "ping_command must be a non-empty list of strings" in result.err
    assert rows("SELECT count(*) FROM messages") == [(0,)]


@pytest.mark.parametrize(
    ("raw", "warning"),
    [
        (
            "garbage",
            "refreshing receipts: bellhop status printed no schema_version 1 JSON (exit 0)",
        ),
        (
            json.dumps(
                {"schema_version": 1, "status": "error", "error": {"message": "store locked"}}
            ),
            "refreshing receipts: bellhop status: store locked",
        ),
    ],
)
def test_a_failed_refresh_is_a_warning(
    cb: Callboard, bellhop: FakeBellhop, raw: str, warning: str
) -> None:
    assert cb("--as", "enki", "dm", "nanna", "one").code == 0
    bellhop.behave(raw=raw)
    result = cb("--as", "nanna", "inbox", "--json")
    assert result.code == 0
    assert result.json()["warnings"] == [warning]
    assert result.json()["conversations"][0]["unread"] == 1
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_7f3a9c2e41d0", "pending")


def test_one_deadline_covers_identity_and_ringing(cb: Callboard, bellhop: FakeBellhop) -> None:
    bellhop.replay("whoami", "whoami-agent.json")
    bellhop.behave(sleep=0.7)
    started = time.monotonic()
    result = cb("dm", "nanna", "hello", "--json", deadline=1.0)
    elapsed = time.monotonic() - started
    assert result.code == 0
    assert result.json()["warnings"][0].startswith("ping nanna for cb_000000000001: bellhop send")
    assert elapsed < 1.4


def test_rings_queued_behind_the_parallel_cap_share_the_deadline(
    cb: Callboard, bellhop: FakeBellhop, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("callboard.ping.MAX_PARALLEL", 1)
    assert cb("--as", "enki", "group", "create", "ops", "--members", "nanna,utu,niels").code == 0
    seed(("anu", "anu"))
    assert cb("--as", "enki", "group", "add", "ops", "anu").code == 0
    bellhop.behave(sleep=0.4)
    started = time.monotonic()
    result = cb("--as", "enki", "group", "send", "ops", "@nanna @utu @anu", "--json", deadline=1.0)
    elapsed = time.monotonic() - started
    assert result.code == 0
    assert len(result.json()["warnings"]) == 1
    assert elapsed < 1.4


def test_one_status_call_carries_every_refreshable_id(cb: Callboard, bellhop: FakeBellhop) -> None:
    bellhop.keyed_ids()
    assert cb("--as", "enki", "dm", "nanna", "one").code == 0
    assert cb("--as", "utu", "dm", "nanna", "two").code == 0
    ids = sorted(row[0] for row in rows("SELECT bellhop_id FROM receipts"))
    assert len(set(ids)) == 2
    bellhop.replay("status", "status-pending.json")
    assert cb("--as", "nanna", "inbox").code == 0
    assert [call for call in bellhop.calls() if call[0] == "status"] == [["status", *ids, "--json"]]


def test_ping_command_reaches_identity_join_and_doctor(
    cb: Callboard, bellhop: FakeBellhop, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Path(os.environ["XDG_CONFIG_HOME"]) / "callboard" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f'ping_command = ["{FAKES / "bellhop"}"]\n')
    monkeypatch.setenv("PATH", os.pathsep.join([str(Path(sys.executable).parent), os.defpath]))
    bellhop.replay("whoami", "whoami-agent.json")
    bellhop.replay("sessions", "sessions.json")
    bellhop.replay("agents", "agents.json")
    assert cb("join", "enki") == (0, "joined as enki (route enki)\n", "")
    assert cb("dm", "nanna", "hello") == (0, "sent cb_000000000001 to @nanna\n", "")
    checks = cb("doctor", "--json").json()["checks"]
    assert checks[2] == {"name": "bellhop", "status": "ok", "detail": str(FAKES / "bellhop")}
    assert checks[3] == {
        "name": "routes",
        "status": "warn",
        "detail": "1 of 3 routes no longer resolve",
    }
