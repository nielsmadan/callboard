import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Any, TypedDict

import pytest

from callboard.messages import send_direct
from callboard.models import BellhopMessage
from callboard.paths import store_path
from callboard.ping import Ring, Rung, record, send_worst
from callboard.store import open_store
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
    assert _receipt("cb_000000000001", "nanna") == ("bh_000000000001", "pending", None, 1)


def test_an_inline_ping_shows_control_characters_escaped_and_stores_the_body_as_sent(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    body = "red \x1b[31mtext\x07\tnext\nline\x00end"
    assert cb("--as", "enki", "dm", "nanna", body).code == 0
    assert bellhop.entries()[0]["stdin"] == (
        "callboard cb_000000000001 dm from enki: red \\x1b[31mtext\\x07\tnext\nline\\x00end"
    )
    assert rows("SELECT body FROM messages") == [(body,)]


def test_now_rings_as_an_interrupt(cb: Callboard, bellhop: FakeBellhop) -> None:
    assert cb("--as", "enki", "dm", "nanna", "stop", "--now").code == 0
    assert bellhop.entries() == [
        {
            "argv": _send_argv(SESSION, "now", "enki", "cb_000000000001:nanna"),
            "stdin": "callboard cb_000000000001 dm from enki: stop",
        }
    ]


def test_group_now_interrupts_the_mentioned_member(cb: Callboard, bellhop: FakeBellhop) -> None:
    assert cb("--as", "enki", "group", "create", "ops", "--members", "nanna,utu").code == 0
    assert cb("--as", "enki", "group", "send", "ops", "@nanna now please", "--now").code == 0
    assert bellhop.entries() == [
        {
            "argv": _send_argv(SESSION, "now", "enki", "cb_000000000001:nanna"),
            "stdin": "callboard cb_000000000001 group ops from enki: @nanna now please",
        }
    ]


def test_a_mail_reply_rings_with_the_thread_subject(cb: Callboard, bellhop: FakeBellhop) -> None:
    sent = cb("--as", "enki", "mail", "send", "--to", "nanna", "--subject", "Plan", "draft")
    assert sent.code == 0
    before = len(bellhop.entries())
    assert cb("--as", "nanna", "mail", "reply", "cb_000000000001", "ok").code == 0
    assert bellhop.entries()[before:] == [
        {
            "argv": _send_argv("enki", "hold", "nanna", "cb_000000000003:enki", wake=False),
            "stdin": 'callboard cb_000000000003 mail "Plan" from nanna (2 chars);'
            " read: callboard read cb_000000000003",
        }
    ]


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
        "bh_000000000001",
        "confirmed",
        "2026-11-14T09:00:00Z",
        1,
    )
    assert cb("--as", "nanna", "inbox").out == "no unread messages\n"


def test_a_confirmed_doorbell_is_not_read(cb: Callboard, bellhop: FakeBellhop) -> None:
    bellhop.replay("send", "send-confirmed.json")
    assert cb("--as", "enki", "dm", "nanna", "x" * 600).code == 0
    assert _receipt("cb_000000000001", "nanna") == ("bh_000000000001", "confirmed", None, 0)


def test_a_later_refresh_upgrades_with_one_status_call(cb: Callboard, bellhop: FakeBellhop) -> None:
    assert cb("--as", "enki", "dm", "nanna", "one").code == 0
    assert cb("--as", "enki", "dm", "nanna", "two").code == 0
    assert _receipt("cb_000000000002", "nanna") == ("bh_000000000001", "pending", None, 1)
    bellhop.replay("status", "status-confirmed.json")
    inbox = cb("--as", "nanna", "inbox", "--json")
    assert inbox.json()["conversations"] == []
    assert inbox.json()["warnings"] == []
    status_calls = [call for call in bellhop.calls() if call[0] == "status"]
    assert status_calls == [["status", "bh_000000000001", "--json"]]
    assert _receipt("cb_000000000001", "nanna") == (
        "bh_000000000001",
        "confirmed",
        "2026-11-14T09:00:00Z",
        1,
    )


def test_receipts_refresh_their_message(cb: Callboard, bellhop: FakeBellhop) -> None:
    assert cb("--as", "enki", "dm", "nanna", "one").code == 0
    bellhop.replay("status", "status-confirmed.json")
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
                        "exit_code": 2,
                        "error": {"code": "usage", "message": "body longer than 8000 characters"},
                    }
                ),
                "exit_code": 2,
            },
            "pending",
            (
                "bellhop send: body longer than 8000 characters; callboard and bellhop may not"
                " match; callboard doctor --reping rings it again once they do"
            ),
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
        (
            {"sleep": 3},
            "pending",
            (
                "bellhop send timed out after 0.5s; the outcome is unknown;"
                " callboard doctor --reping settles it"
            ),
        ),
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
    bellhop.replay("send", "send-push-rejected.json")
    result = cb("--as", "enki", "dm", "nanna", "hello")
    assert result.err == (
        "callboard: ping nanna for cb_000000000001: bellhop send:"
        " the receiver rejected bh_000000000001: fake rejected\n"
    )
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", "failed")


def test_a_now_that_went_out_as_idle_is_delivered_not_held(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    bellhop.replay("send", "send-degraded.json")
    result = cb("--as", "enki", "dm", "nanna", "hello", "--now", "--json")
    assert (result.code, result.err, result.json()["warnings"]) == (0, "", [])
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", "sent")


def test_a_ping_bellhop_held_is_kept_and_reported(cb: Callboard, bellhop: FakeBellhop) -> None:
    bellhop.replay("send", "send-held.json")
    result = cb("--as", "enki", "dm", "nanna", "hello")
    assert result.err == (
        "callboard: ping nanna for cb_000000000001: held by bellhop; no usable route for idle\n"
    )
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", "pending")


def test_a_mail_hold_is_not_reported_as_held(cb: Callboard, bellhop: FakeBellhop) -> None:
    bellhop.replay("send", "send-held.json")
    result = cb("--as", "enki", "mail", "send", "--to", "nanna", "--subject", "s", "x")
    assert (result.code, result.err) == (0, "")


def test_a_confirm_bellhop_could_not_do_is_passed_on_not_failed(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    bellhop.replay("send", "send-unconfirmed.json")
    result = cb("--as", "enki", "dm", "nanna", "hello", "--json")
    assert (result.code, result.json()["warnings"]) == (
        0,
        [
            (
                "ping nanna for cb_000000000001: bellhop send:"
                " cannot confirm: no transcript to read for this session"
            )
        ],
    )
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", "sent")


def test_any_other_bellhop_send_warning_is_passed_on(cb: Callboard, bellhop: FakeBellhop) -> None:
    bellhop.replay("send", "send-not-running.json")
    result = cb("--as", "enki", "dm", "nanna", "later", "--json")
    assert (result.code, result.json()["warnings"]) == (
        0,
        [
            (
                "ping nanna for cb_000000000001: bellhop send:"
                " 'nanna' is not running; the message waits (use --wake to start it)"
            )
        ],
    )
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", "pending")


def test_unknown_ids_from_a_refresh_are_passed_on(cb: Callboard, bellhop: FakeBellhop) -> None:
    assert cb("--as", "enki", "dm", "nanna", "one").code == 0
    bellhop.replay("status", "status.json")
    inbox = cb("--as", "nanna", "inbox", "--json")
    assert inbox.json()["warnings"] == [
        "refreshing receipts: bellhop status: unknown message id bh_000000000001"
    ]
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", "pending")


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
    assert _receipt("cb_000000000002", "utu")[:2] == ("bh_000000000001", "sent")
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
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", "pending")


def _confirm_of(bellhop: FakeBellhop) -> float:
    send = next(call for call in bellhop.calls() if call[0] == "send")
    return float(send[send.index("--confirm") + 1])


def test_a_send_that_starts_late_still_gets_its_whole_budget(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    bellhop.replay("whoami", "whoami.json")
    bellhop.behave(sleep=1.2)
    started = time.monotonic()
    result = cb("dm", "nanna", "hello", "--json", deadline=2.0)
    elapsed = time.monotonic() - started
    assert (result.code, result.json()["warnings"]) == (0, [])
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", "pending")
    assert _confirm_of(bellhop) == 0
    assert elapsed < 3.2


def test_confirm_waits_only_for_the_time_left_after_bellhops_budget(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    bellhop.replay("whoami", "whoami.json")
    bellhop.behave(sleep=1.2)
    result = cb("dm", "nanna", "hello", "--json", deadline=12.0)
    assert (result.code, result.json()["warnings"]) == (0, [])
    assert 0 < _confirm_of(bellhop) <= 12.0 - 10.0 - 1.2


def test_rings_queued_behind_the_parallel_cap_share_the_deadline(
    cb: Callboard, bellhop: FakeBellhop, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("callboard.ping.MAX_PARALLEL", 1)
    assert cb("--as", "enki", "group", "create", "ops", "--members", "nanna,utu,niels").code == 0
    seed(("anu", "anu"))
    assert cb("--as", "enki", "group", "add", "ops", "anu").code == 0
    bellhop.behave(sleep=1.1)
    started = time.monotonic()
    result = cb("--as", "enki", "group", "send", "ops", "@nanna @utu @anu", "--json", deadline=2.0)
    elapsed = time.monotonic() - started
    assert result.code == 0
    assert len(result.json()["warnings"]) == 1
    assert elapsed < 3.2


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
    bellhop.replay("whoami", "whoami.json")
    bellhop.replay("sessions", "sessions.json")
    bellhop.replay("agents", "agents.json")
    assert cb("join", "enki") == (0, "joined as enki (route enki)\n", "")
    assert cb("dm", "nanna", "hello") == (0, "sent cb_000000000001 to @nanna\n", "")
    checks = cb("doctor", "--json").json()["checks"]
    assert checks[2] == {"name": "bellhop", "status": "ok", "detail": str(FAKES / "bellhop")}
    assert checks[3] == {
        "name": "routes",
        "status": "warn",
        "detail": "2 of 3 routes no longer resolve",
    }


def test_output_that_is_not_utf8_is_malformed_not_a_crash(
    cb: Callboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_BELLHOP_RAW_HEX", b'{"id": "bh_\xff"}'.hex())
    result = cb("--as", "enki", "dm", "nanna", "hello", "--json")
    assert result.code == 0
    assert result.json()["warnings"] == [
        "ping nanna for cb_000000000001: bellhop send printed output that is not UTF-8"
    ]
    assert _receipt("cb_000000000001", "nanna")[:2] == (None, "pending")


def test_any_failure_after_storing_still_reports_the_message(
    cb: Callboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object) -> object:
        raise ValueError("unexpected")

    monkeypatch.setattr("callboard.cli.chat.receipts_of", broken)
    payload = cb("--as", "enki", "dm", "nanna", "hello", "--json").json()
    assert (payload["exit_code"], payload["error"]["code"], payload["message"]["id"]) == (
        1,
        "internal_error",
        "cb_000000000001",
    )


def test_a_long_or_multiline_subject_is_one_short_line_in_the_ping(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    subject = 'Plan "v2"\nline two ' + "x" * 9000
    assert cb("--as", "enki", "mail", "send", "--to", "nanna", "--subject", subject, "hi").code == 0
    label = 'Plan \\"v2\\"\\nline two ' + "x" * 59 + "…"
    assert bellhop.entries()[0]["stdin"] == (
        f'callboard cb_000000000001 mail "{label}" from enki (2 chars);'
        " read: callboard read cb_000000000001"
    )


def test_storing_the_message_does_not_spend_the_bellhop_deadline(
    cb: Callboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = send_direct

    def slow(*args: Any, **kwargs: Any) -> Any:
        time.sleep(1.2)
        return real(*args, **kwargs)

    monkeypatch.setattr("callboard.cli.chat.send_direct", slow)
    result = cb("--as", "enki", "dm", "nanna", "hello", "--json", deadline=1.0)
    assert (result.code, result.json()["warnings"]) == (0, [])
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", "pending")


def test_a_timeout_kills_the_whole_bellhop_process_group(cb: Callboard, tmp_path: Path) -> None:
    pidfile = tmp_path / "grandchild.pid"
    wrapper = tmp_path / "wrapper"
    wrapper.write_text(f"#!/bin/sh\n/bin/sleep 30 >/dev/null 2>&1 &\necho $! > {pidfile}\nwait\n")
    wrapper.chmod(0o755)
    config = Path(os.environ["XDG_CONFIG_HOME"]) / "callboard" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f'ping_command = ["{wrapper}"]\n')
    started = time.monotonic()
    result = cb("--as", "enki", "dm", "nanna", "hello", deadline=3)
    assert (result.code, time.monotonic() - started < 10) == (0, True)
    grandchild = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _alive(grandchild):
        time.sleep(0.05)
    assert not _alive(grandchild)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_reping_counts_only_rings_bellhop_answered(
    cb: Callboard, bellhop: FakeBellhop, monkeypatch: pytest.MonkeyPatch
) -> None:
    bellhop.behave(raw="garbage")
    assert cb("--as", "enki", "dm", "nanna", "missed").code == 0
    result = cb("doctor", "--reping", "--json")
    assert result.json()["repinged"] == 0
    assert result.json()["warnings"] == [
        "ping nanna for cb_000000000001: bellhop send printed no schema_version 1 JSON (exit 0)"
    ]
    assert _receipt("cb_000000000001", "nanna")[:2] == (None, "pending")


def test_a_late_answer_never_moves_a_receipt_backwards(cb: Callboard, bellhop: FakeBellhop) -> None:
    bellhop.replay("send", "send-confirmed.json")
    assert cb("--as", "enki", "dm", "nanna", "hello").code == 0
    ring = Ring("cb_000000000001", "nanna", SESSION, "idle", "enki", "text")
    late = Rung(ring, BellhopMessage("bh_000000000001", "sending", "idle", None), False, ())
    with closing(open_store(store_path(os.environ))) as conn:
        record(conn, [late], "2026-11-14T09:05:00Z")
    assert _receipt("cb_000000000001", "nanna") == (
        "bh_000000000001",
        "confirmed",
        "2026-11-14T09:00:00Z",
        1,
    )


@pytest.mark.parametrize(
    ("fixture", "state"), [("send-confirmed.json", "confirmed"), ("send-read.json", "read")]
)
def test_a_late_refusal_never_turns_a_delivered_receipt_failed(
    cb: Callboard, bellhop: FakeBellhop, fixture: str, state: str
) -> None:
    bellhop.replay("send", fixture)
    assert cb("--as", "enki", "dm", "nanna", "hello").code == 0
    ring = Ring("cb_000000000001", "nanna", SESSION, "idle", "enki", "text")
    with closing(open_store(store_path(os.environ))) as conn:
        record(conn, [Rung(ring, None, True, ())], "2026-11-14T09:05:00Z")
    assert _receipt("cb_000000000001", "nanna")[:3] == (
        "bh_000000000001",
        state,
        "2026-11-14T09:00:00Z",
    )


def test_a_stale_refresh_never_moves_a_sent_receipt_back_to_pending(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    bellhop.replay("send", "send-sent.json")
    assert cb("--as", "enki", "dm", "nanna", "hello").code == 0
    bellhop.replay("status", "status-pending.json")
    assert cb("--as", "enki", "receipts", "cb_000000000001", "--json").code == 0
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", "sent")


def test_ctrl_c_while_ringing_stops_promptly(bellhop: FakeBellhop) -> None:
    bellhop.behave(sleep=15)
    process = subprocess.Popen(
        [sys.executable, "-m", "callboard", "--as", "enki", "dm", "nanna", "hi"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    waited = time.monotonic() + 10
    while time.monotonic() < waited and not any(
        entry["argv"][0] == "send" for entry in bellhop.entries()
    ):
        time.sleep(0.05)
    time.sleep(0.3)
    interrupted = time.monotonic()
    process.send_signal(signal.SIGINT)
    process.communicate(timeout=20)
    assert (process.returncode, time.monotonic() - interrupted < 3) == (130, True)


def test_a_kill_refused_for_an_exited_child_still_reports_the_timeout(
    cb: Callboard, bellhop: FakeBellhop, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(_pid: int, _signal: int) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr("callboard.bellhop_client.os.killpg", refused)
    bellhop.behave(sleep=1)
    result = cb("--as", "enki", "dm", "nanna", "hello", "--json", deadline=0.3)
    assert result.json()["warnings"] == [
        (
            "ping nanna for cb_000000000001: bellhop send timed out after 0.3s;"
            " the outcome is unknown; callboard doctor --reping settles it"
        )
    ]


def test_a_descendant_holding_the_pipe_cannot_stretch_the_deadline(
    cb: Callboard, tmp_path: Path
) -> None:
    pidfile = tmp_path / "escaped.pid"
    spawn = (
        "import subprocess, sys; "
        "p = subprocess.Popen(['/bin/sleep', '30'], start_new_session=True); "
        "open(sys.argv[1], 'w').write(str(p.pid))"
    )
    wrapper = tmp_path / "wrapper"
    wrapper.write_text(
        f'#!/bin/sh\n"{sys.executable}" -c "{spawn}" {pidfile}\nexec /bin/sleep 30\n'
    )
    wrapper.chmod(0o755)
    config = Path(os.environ["XDG_CONFIG_HOME"]) / "callboard" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f'ping_command = ["{wrapper}"]\n')
    started = time.monotonic()
    try:
        result = cb("--as", "enki", "dm", "nanna", "hello", deadline=0.5)
        elapsed = time.monotonic() - started
    finally:
        if pidfile.exists():
            os.kill(int(pidfile.read_text()), signal.SIGKILL)
    assert (result.code, elapsed < 5) == (0, True)


def test_ctrl_c_after_storing_still_reports_the_message(
    cb: Callboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(*_args: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr("callboard.cli.chat.receipts_of", interrupted)
    result = cb("--as", "enki", "dm", "nanna", "hello", "--json")
    payload = result.json()
    assert (result.code, payload["error"], payload["message"]["id"]) == (
        130,
        {"code": "interrupted", "message": "stored cb_000000000001, then interrupted"},
        "cb_000000000001",
    )


@pytest.mark.parametrize(
    ("fixture", "state"),
    [
        ("send-no-route.json", "failed"),
        ("send-target-not-found.json", "failed"),
        ("send-target-ambiguous.json", "failed"),
        ("send-usage.json", "pending"),
        ("send-hls-unavailable.json", "pending"),
    ],
)
def test_bellhops_refusals_fail_and_its_outages_stay_pending(
    cb: Callboard, bellhop: FakeBellhop, fixture: str, state: str
) -> None:
    bellhop.replay("send", fixture)
    result = cb("--as", "enki", "dm", "nanna", "hello")
    assert result.code == 0
    assert _receipt("cb_000000000001", "nanna")[:2] == (None, state)


def test_a_bellhop_config_error_stays_pending_for_reping(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    envelope = {
        "schema_version": 1,
        "status": "error",
        "exit_code": 2,
        "error": {"code": "invalid_config", "message": "config.toml: unknown key 'agentz'"},
    }
    bellhop.behave(raw=json.dumps(envelope), exit_code=2)
    assert cb("--as", "enki", "dm", "nanna", "hello").code == 0
    assert _receipt("cb_000000000001", "nanna")[:2] == (None, "pending")


def test_an_ok_send_whose_message_failed_warns(cb: Callboard, bellhop: FakeBellhop) -> None:
    bellhop.replay("send", "send-expired.json")
    result = cb("--as", "enki", "dm", "nanna", "hello", "--json")
    assert result.json()["warnings"] == ["ping nanna for cb_000000000001: bellhop send: expired"]
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", "failed")


def test_a_routine_unconfirmed_send_stays_quiet(cb: Callboard, bellhop: FakeBellhop) -> None:
    bellhop.replay("send", "send-not-confirmed.json")
    result = cb("--as", "enki", "dm", "nanna", "hello", "--json")
    assert (result.err, result.json()["warnings"]) == ("", [])
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", "sent")


@pytest.mark.parametrize(
    ("fixture", "state", "warning"),
    [
        ("send-interrupted.json", "sending", "interrupted"),
        (
            "send-internal-error.json",
            "sent",
            "internal error: OSError: [Errno 5] Input/output error",
        ),
    ],
)
def test_an_error_after_bellhop_stored_the_ping_records_its_message(
    cb: Callboard, bellhop: FakeBellhop, fixture: str, state: str, warning: str
) -> None:
    bellhop.replay("send", fixture)
    result = cb("--as", "enki", "dm", "nanna", "hello", "--json")
    assert result.json()["warnings"] == [f"ping nanna for cb_000000000001: bellhop send: {warning}"]
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", state)
    assert cb("doctor", "--reping", "--json").json().get("repinged") == 0


def test_a_ping_that_wakes_its_recipient_is_pending_and_unread(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    bellhop.replay("send", "send-wake.json")
    result = cb("--as", "enki", "dm", "nanna", "hello", "--json")
    assert (result.code, result.err, result.json()["warnings"]) == (0, "", [])
    assert _receipt("cb_000000000001", "nanna")[:3] == ("bh_000000000001", "pending", None)


def test_that_confirm_does_not_wait_for_a_wake_stays_quiet(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    bellhop.replay("send", "send-wake-confirm.json")
    result = cb("--as", "enki", "dm", "nanna", "hello", "--json")
    assert (result.code, result.err, result.json()["warnings"]) == (0, "", [])
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", "pending")


def test_a_woken_inline_ping_is_unread_while_sent_and_read_once_confirmed(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    bellhop.replay("send", "send-wake-confirm.json")
    assert cb("--as", "enki", "dm", "nanna", "hello").code == 0
    bellhop.replay("status", "status-woken.json")
    assert cb("--as", "nanna", "inbox", "--json").json()["conversations"][0]["unread"] == 1
    assert _receipt("cb_000000000001", "nanna") == ("bh_000000000001", "sent", None, 1)
    bellhop.replay("status", "status-confirmed.json")
    receipts = cb("--as", "enki", "receipts", "cb_000000000001", "--json").json()["receipts"]
    assert (receipts[0]["ping_state"], receipts[0]["read_at"]) == (
        "confirmed",
        "2026-11-14T09:00:00Z",
    )
    assert cb("--as", "nanna", "inbox", "--json").json()["conversations"] == []


def test_a_wake_that_cannot_start_keeps_the_ping_pending_and_passes_the_warning_on(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    bellhop.replay("send", "send-wake-cannot-launch.json")
    result = cb("--as", "enki", "dm", "nanna", "hello", "--json")
    assert (result.code, result.json()["warnings"]) == (
        0,
        [
            (
                "ping nanna for cb_000000000001: bellhop send: cannot launch 'enki':"
                " its cwd /no/such/dir is not a directory; the message waits"
            )
        ],
    )
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", "pending")


def test_a_wake_after_a_failed_start_records_the_ping_failed_with_its_detail(
    cb: Callboard, bellhop: FakeBellhop
) -> None:
    bellhop.replay("send", "send-wake-failed.json")
    result = cb("--as", "enki", "dm", "nanna", "hello", "--json")
    assert (result.code, result.json()["warnings"]) == (
        0,
        [
            (
                "ping nanna for cb_000000000001: bellhop send: cannot wake 'enki': start failed:"
                " stopped at the trust-folder screen; attach with: tmux -S <tmux-socket> attach"
                " -t =enki; run `bellhop launch enki` to retry"
            )
        ],
    )
    assert _receipt("cb_000000000001", "nanna")[:2] == ("bh_000000000001", "failed")
    assert cb("doctor", "--reping", "--json").json().get("repinged") == 0


@pytest.mark.parametrize(
    ("level", "confirm", "worst"),
    [("idle", 0.0, 20.0), ("now", 5.0, 20.0), ("hold", 5.0, 15.0), ("hold", 0.0, 10.0)],
)
def test_a_ring_that_may_start_its_agent_is_given_bellhops_tmux_time(
    level: str, confirm: float, worst: float
) -> None:
    ring = Ring("cb_000000000001", "nanna", SESSION, level, "enki", "text")
    assert send_worst(ring, confirm) == worst


def test_bellhop_text_in_a_warning_is_escaped_and_cut(cb: Callboard, bellhop: FakeBellhop) -> None:
    message = "x\x1b[2J" + "y" * 1000
    envelope = {
        "schema_version": 1,
        "status": "error",
        "exit_code": 1,
        "error": {"code": "store_error", "message": message},
    }
    bellhop.behave(raw=json.dumps(envelope), exit_code=1)
    warning = cb("--as", "enki", "dm", "nanna", "hello", "--json").json()["warnings"][0]
    shown = "x\\x1b[2J" + "y" * 1000
    assert warning == f"ping nanna for cb_000000000001: bellhop send: {shown[:299]}…"


@pytest.mark.parametrize(
    ("message", "warnings", "raw"),
    [
        (
            {"id": "bh_1", "state": "failed", "detail": "z\x07" + "q" * 1000},
            [],
            "z\x07" + "q" * 1000,
        ),
        ({"id": "bh_1", "state": "sent"}, ["w\x1b" + "r" * 1000], "w\x1b" + "r" * 1000),
    ],
)
def test_a_detail_or_warning_from_bellhop_is_escaped_and_cut(
    cb: Callboard,
    bellhop: FakeBellhop,
    message: dict[str, object],
    warnings: list[str],
    raw: str,
) -> None:
    envelope = {"schema_version": 1, "status": "ok", "warnings": warnings, "message": message}
    bellhop.behave(raw=json.dumps(envelope))
    shown = raw.replace("\x07", "\\x07").replace("\x1b", "\\x1b")
    result = cb("--as", "enki", "dm", "nanna", "hello", "--json")
    assert result.json()["warnings"] == [
        f"ping nanna for cb_000000000001: bellhop send: {shown[:299]}…"
    ]
