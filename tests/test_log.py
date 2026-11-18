import itertools
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from callboard.cli.dispatch import run
from callboard.models import Runtime
from callboard.trace import read_events, rotate, trace_path, tracer
from helpers import CLOCK, Callboard, FakeBellhop, Result, seed


def env(tmp_path: Path, **extra: str) -> dict[str, str]:
    return {"XDG_DATA_HOME": str(tmp_path / "data"), **extra}


def test_an_event_is_one_private_json_line_without_empty_fields(tmp_path: Path) -> None:
    tracer(env(tmp_path))("command", argv=["who"], code=None, text="x" * 400)

    path = trace_path(env(tmp_path))
    [event] = [json.loads(line) for line in path.read_text().splitlines()]
    assert (event["event"], event["argv"]) == ("command", ["who"])
    assert event["text"] == "x" * 300 + "… (400 characters)"
    assert "code" not in event
    assert path.stat().st_mode & 0o777 == 0o600


def test_tracing_can_be_switched_off(tmp_path: Path) -> None:
    tracer(env(tmp_path, CALLBOARD_TRACE="off"))("command")

    assert not trace_path(env(tmp_path)).exists()


def test_a_planted_link_is_not_written_through(tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.write_text("mine")
    path = trace_path(env(tmp_path))
    path.parent.mkdir(parents=True)
    path.symlink_to(victim)

    tracer(env(tmp_path))("command")

    assert victim.read_text() == "mine"


def test_reading_keeps_the_last_events_that_hold_every_word(tmp_path: Path) -> None:
    emit = tracer(env(tmp_path))
    emit("sent", message="cb_1", sender="enki")
    emit("sent", message="cb_2", sender="enki")
    emit("sent", message="cb_3", sender="nanna")

    found = read_events(env(tmp_path), count=1, words=["sent", "enki"])

    assert [event["message"] for event in found] == ["cb_2"]


def test_failures_are_failed_commands_and_rings_with_warnings(tmp_path: Path) -> None:
    emit = tracer(env(tmp_path))
    emit("command", argv=["who"], exit=0)
    emit("command", argv=["dm"], exit=3, code="unknown_handle", error="no handle nobody")
    emit("sent", message="cb_1", receipts=[])
    emit("sent", message="cb_2", warnings=["nanna was not rung: no_route"])

    found = read_events(env(tmp_path), count=10, failures=True)

    assert [event.get("code") or event.get("message") for event in found] == [
        "unknown_handle",
        "cb_2",
    ]


@pytest.fixture
def traced(capsys: pytest.CaptureFixture[str]) -> Callboard:
    counter = itertools.count(1)

    def call(*argv: str, stdin: str = "", deadline: float = 20.0) -> Result:
        runtime = Runtime(
            os.environ,
            lambda: CLOCK,
            lambda: f"{next(counter):012x}",
            lambda: stdin,
            deadline,
            tracer(os.environ),
        )
        code = run(list(argv), runtime)
        out, err = capsys.readouterr()
        return Result(code, out, err)

    return call


def events(traced: Callboard, *words: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = traced("log", "-n", "100", "--json", *words).json()["events"]
    return found


def test_a_command_leaves_its_arguments_and_its_result(traced: Callboard) -> None:
    seed(("enki", "enki"))

    traced("--as", "enki", "who", "--json")
    traced("--as", "enki", "dm", "nobody", "hello")

    ok, refused = events(traced, "command")
    assert (ok["argv"], ok["exit"]) == (["--as", "enki", "who", "--json"], 0)
    assert (refused["exit"], refused["code"]) == (3, "unknown_handle")
    assert "nobody" in refused["error"]


def test_errors_keeps_only_what_went_wrong(traced: Callboard) -> None:
    seed(("enki", "enki"))
    traced("--as", "enki", "who", "--json")
    traced("--as", "enki", "dm", "nobody", "hello")

    found = traced("log", "--errors", "--json").json()["events"]

    assert [(event["event"], event["code"]) for event in found] == [("command", "unknown_handle")]


def test_a_sent_message_leaves_its_receipts(traced: Callboard, ringing: FakeBellhop) -> None:
    seed(("enki", "enki"), ("nanna", "sess-nanna"))

    sent = traced("--as", "enki", "dm", "nanna", "hello", "--json").json()["message"]

    [event] = events(traced, '"event": "sent"')
    assert (event["message"], event["sender"]) == (sent["id"], "enki")
    assert event["receipts"] == sent["receipts"]


def test_the_log_command_is_not_itself_recorded(traced: Callboard) -> None:
    traced("who")
    events(traced)

    assert [event["argv"] for event in events(traced, "command")] == [["who"]]


def test_the_text_form_is_one_line_per_event(traced: Callboard) -> None:
    traced("who")

    [line] = traced("log").out.splitlines()

    clock, pid, event, *fields = line.split(" ")
    assert (len(clock), pid[0] + pid[-1], event) == (12, "[]", "command")
    assert 'argv=["who"]' in fields


def test_an_empty_trace_says_where_it_looked(traced: Callboard) -> None:
    assert traced("log").out.startswith("no matching events in ")


def test_log_is_not_recorded_behind_a_handle_either(traced: Callboard) -> None:
    seed(("enki", "enki"))
    traced("--as", "enki", "who")

    traced("--as", "enki", "log")

    assert [event["argv"] for event in events(traced, "command")] == [["--as", "enki", "who"]]


def test_a_file_that_cannot_be_set_aside_is_emptied_instead_of_growing(tmp_path: Path) -> None:
    emit = tracer(env(tmp_path))
    emit("first")
    path = trace_path(env(tmp_path))
    path.with_name("trace.jsonl.1").mkdir()

    rotate(path, limit=10)
    emit("second")

    assert [json.loads(line)["event"] for line in path.read_text().splitlines()] == ["second"]


def test_reading_takes_the_end_of_a_long_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    emit = tracer(env(tmp_path))
    for number in range(50):
        emit("sent", number=number)
    monkeypatch.setattr("callboard.trace.READ_LIMIT", 300)

    found = read_events(env(tmp_path), count=2)

    assert [event["number"] for event in found] == [48, 49]


def test_a_removed_working_directory_does_not_fail_a_command(tmp_path: Path) -> None:
    gone = tmp_path / "gone"
    gone.mkdir()
    script = 'rmdir "$PWD" && exec "$0" -m callboard --version'

    done = subprocess.run(
        ["/bin/sh", "-c", script, sys.executable],
        cwd=gone,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert (done.returncode, done.stderr) == (0, "")
    [event] = read_events(os.environ, count=5)
    assert (event["argv"], event.get("cwd")) == (["--version"], None)
