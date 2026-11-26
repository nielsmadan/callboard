import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from callboard.cli.dispatch import run
from callboard.paths import store_path
from callboard.store import open_store
from helpers import FakeBellhop, runtime, seed

ENKI_SESSION = "2e2042a9-937c-4e03-ba25-74b5ba14a58f"
UNNAMED_SESSION = "2e20ffff-0000-4000-8000-000000000002"


def _callboard(*argv: str) -> int:
    return run(list(argv), runtime())


def _rows() -> list[tuple[str, str, str | None, str]]:
    with closing(sqlite3.connect(store_path(os.environ))) as conn:
        return conn.execute(
            "SELECT handle, kind, route, created_at FROM participants ORDER BY handle"
        ).fetchall()


def test_join_routes_to_the_agent_name(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    bellhop.replay("whoami", "whoami.json")
    assert _callboard("join", "enki") == 0
    assert capsys.readouterr() == ("joined as enki (route enki)\n", "")
    assert _rows() == [("enki", "agent", "enki", "2026-11-14T09:00:00Z")]


def test_join_without_an_agent_name_routes_to_the_session_id(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    bellhop.replay("whoami", "whoami-no-agent.json")
    assert _callboard("join", "reviewer") == 0
    assert capsys.readouterr().out == f"joined as reviewer (route {UNNAMED_SESSION})\n"
    assert _rows() == [("reviewer", "agent", UNNAMED_SESSION, "2026-11-14T09:00:00Z")]


def test_join_again_from_another_session_rebinds_and_says_so(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    bellhop.replay("whoami", "whoami.json")
    assert _callboard("join", "enki") == 0
    bellhop.replay("whoami", "whoami-no-agent.json")
    capsys.readouterr()
    assert _callboard("join", "enki") == 0
    assert capsys.readouterr() == (
        f"joined as enki (route {UNNAMED_SESSION})\n",
        f"callboard: rebound 'enki' from route enki to route {UNNAMED_SESSION}\n",
    )
    assert _rows() == [("enki", "agent", UNNAMED_SESSION, "2026-11-14T09:00:00Z")]


def test_join_again_from_the_same_session_is_quiet(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    bellhop.replay("whoami", "whoami.json")
    assert _callboard("join", "enki") == 0
    assert _callboard("join", "enki") == 0
    assert capsys.readouterr() == ("joined as enki (route enki)\n" * 2, "")


def test_join_human_needs_no_session_and_has_no_route(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _callboard("join", "niels", "--human") == 0
    assert capsys.readouterr() == ("joined as niels (human, no route)\n", "")
    assert _rows() == [("niels", "human", None, "2026-11-14T09:00:00Z")]


def test_join_with_an_invalid_handle_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _callboard("join", "Enki") == 2
    assert capsys.readouterr().err.startswith("callboard: handle 'Enki' is not a valid handle; ")
    assert not store_path(os.environ).exists()


def test_join_outside_a_session_fails_and_stores_nothing(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    bellhop.replay("whoami", "whoami-caller-unknown.json")
    assert _callboard("join", "enki") == 3
    assert capsys.readouterr().err == (
        "callboard: bellhop whoami: CODEX_THREAD_ID=not-live is not a live session hooklinesinker lists;"
        " if you are a person at a terminal, run: callboard join <handle> --human\n"
    )
    assert not store_path(os.environ).exists()


def test_join_with_an_unwritable_data_dir_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_home = tmp_path / "readonly-data"
    data_home.mkdir(mode=0o500)
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    assert _callboard("join", "niels", "--human") == 1
    assert capsys.readouterr().err.startswith(
        f"callboard: cannot open store {data_home / 'callboard' / 'callboard.sqlite'}: "
    )


def test_concurrent_joins_of_one_new_handle_leave_one_row() -> None:
    command = [sys.executable, "-m", "callboard", "join", "niels", "--human"]
    processes = [
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(8)
    ]
    results = [(process.wait(timeout=60), *process.communicate()) for process in processes]
    assert results == [(0, "joined as niels (human, no route)\n", "")] * 8
    assert [row[:3] for row in _rows()] == [("niels", "human", None)]


GOLDEN = Path(__file__).resolve().parent / "golden"


def test_who_json_matches_the_golden(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    bellhop.replay("whoami", "whoami.json")
    assert _callboard("join", "enki") == 0
    assert _callboard("join", "niels", "--human") == 0
    capsys.readouterr()
    assert _callboard("who", "--json") == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == json.loads((GOLDEN / "who.json").read_text())
    assert captured.out.count("\n") == 1


def test_who_marks_the_caller_in_text(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    bellhop.replay("whoami", "whoami.json")
    assert _callboard("join", "enki") == 0
    assert _callboard("join", "niels", "--human") == 0
    capsys.readouterr()
    assert _callboard("--as", "niels", "who") == 0
    assert capsys.readouterr().out == (
        "   handle  kind   route\n   enki    agent  enki\n*  niels   human  -\n"
        "* is you through --as\n"
    )


def test_who_names_callboard_as_when_it_chose_the_caller(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    bellhop.replay("whoami", "whoami.json")
    assert _callboard("join", "enki") == 0
    assert _callboard("join", "niels", "--human") == 0
    monkeypatch.setenv("CALLBOARD_AS", "niels")
    capsys.readouterr()
    assert _callboard("who") == 0
    assert capsys.readouterr().out.splitlines()[-2:] == [
        "*  niels   human  -",
        "* is you through $CALLBOARD_AS; unset it if this is not you",
    ]
    assert _callboard("who", "--json") == 0
    assert json.loads(capsys.readouterr().out)["you_from"] == "CALLBOARD_AS"


def test_who_outside_a_session_shows_no_caller(capsys: pytest.CaptureFixture[str]) -> None:
    assert _callboard("join", "niels", "--human") == 0
    capsys.readouterr()
    assert _callboard("who", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert (payload["you"], [p["handle"] for p in payload["participants"]]) == (None, ["niels"])


def test_who_with_no_participants_says_how_to_join(capsys: pytest.CaptureFixture[str]) -> None:
    assert _callboard("who") == 0
    assert capsys.readouterr().out == "no participants yet; run: callboard join <handle>\n"


def test_who_warns_when_the_session_is_joined_twice(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    with closing(open_store(store_path(os.environ))) as conn:
        conn.executemany(
            "INSERT INTO participants (handle, kind, route, created_at) VALUES (?, 'agent', 'enki', 't')",
            [("one",), ("two",)],
        )
    bellhop.replay("whoami", "whoami.json")
    assert _callboard("who", "--json") == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    warning = "this session is joined as one, two; pass --as HANDLE"
    assert (payload["you"], payload["warnings"]) == (None, [warning])
    assert captured.err == f"callboard: {warning}\n"


def test_who_warns_when_hls_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _callboard("join", "niels", "--human") == 0
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "bellhop"
    script.write_text(
        "#!/bin/sh\n"
        'echo \'{"schema_version":1,"status":"error","exit_code":5,'
        '"error":{"code":"hls_unavailable","message":"hls timed out"}}\'\n'
        "exit 5\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    capsys.readouterr()
    assert _callboard("who", "--json") == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert (payload["you"], payload["warnings"]) == (None, ["bellhop whoami: hls timed out"])
    assert captured.err == "callboard: bellhop whoami: hls timed out\n"


def test_joining_a_second_handle_moves_the_route_to_it(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    bellhop.replay("whoami", "whoami.json")
    assert _callboard("join", "enkii") == 0
    capsys.readouterr()
    assert _callboard("join", "enki") == 0
    assert capsys.readouterr() == (
        "joined as enki (route enki)\n",
        "callboard: moved this session from 'enkii' to 'enki' (route enki)\n",
    )
    assert [row[:3] for row in _rows()] == [("enki", "agent", "enki"), ("enkii", "agent", None)]
    assert _callboard("who", "--json") == 0
    assert json.loads(capsys.readouterr().out)["you"] == "enki"


def test_a_locked_store_is_a_clean_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _callboard("join", "niels", "--human") == 0
    capsys.readouterr()
    monkeypatch.setattr("callboard.store.BUSY_TIMEOUT_SECONDS", 0.1)
    with closing(sqlite3.connect(store_path(os.environ), isolation_level=None)) as holder:
        holder.execute("BEGIN IMMEDIATE")
        assert _callboard("join", "ana", "--human") == 1
        holder.execute("ROLLBACK")
    assert capsys.readouterr() == ("", "callboard: store error: database is locked\n")


def test_who_with_an_unknown_as_handle_exits_3_with_the_json_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _callboard("--as", "ghost", "who", "--json") == 3
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "status": "error",
        "exit_code": 3,
        "error": {
            "code": "unknown_handle",
            "message": "--as: no participant 'ghost'; run: callboard join ghost",
        },
    }


def test_who_on_a_newer_schema_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert _callboard("join", "niels", "--human") == 0
    with closing(sqlite3.connect(store_path(os.environ))) as conn:
        conn.execute("UPDATE meta SET value = '4' WHERE key = 'schema_version'")
        conn.commit()
    capsys.readouterr()
    assert _callboard("who") == 1
    assert capsys.readouterr().err == (
        "callboard: store schema version 4 is newer than this callboard supports (3);"
        " upgrade callboard\n"
    )


def test_who_with_an_unreadable_store_directory_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_home = tmp_path / "readonly-data"
    data_home.mkdir(mode=0o500)
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    assert _callboard("who", "--json") == 1
    payload = json.loads(capsys.readouterr().out)
    assert (payload["exit_code"], payload["error"]["code"]) == (1, "store_unavailable")


def test_as_after_the_command_is_honoured(capsys: pytest.CaptureFixture[str]) -> None:
    assert _callboard("who", "--as", "ghost", "--json") == 3
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "unknown_handle"
    assert _callboard("join", "niels", "--human") == 0
    capsys.readouterr()
    assert _callboard("--as", "ghost", "who", "--as", "niels", "--json") == 0
    assert json.loads(capsys.readouterr().out)["you"] == "niels"


def test_joining_by_agent_name_frees_the_handle_the_session_held_by_its_id(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    bellhop.replay("whoami", "whoami-no-agent.json")
    assert _callboard("join", "a") == 0
    with closing(sqlite3.connect(store_path(os.environ))) as conn:
        conn.execute("UPDATE participants SET route = ? WHERE handle = 'a'", (ENKI_SESSION,))
        conn.commit()
    bellhop.replay("whoami", "whoami.json")
    capsys.readouterr()
    assert _callboard("join", "enki") == 0
    assert capsys.readouterr() == (
        "joined as enki (route enki)\n",
        "callboard: moved this session from 'a' to 'enki' (route enki)\n",
    )
    assert [(row[0], row[2]) for row in _rows()] == [("a", None), ("enki", "enki")]


@pytest.mark.parametrize(
    ("argv", "error"),
    [
        (
            ("--as", "niels", "join", "enki"),
            "join does not take --as; it joins the session it runs in",
        ),
        (("join", "enki", "--as", "x"), "unrecognized arguments: --as x"),
    ],
)
def test_join_refuses_as(
    argv: tuple[str, ...], error: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _callboard(*argv) == 2
    assert capsys.readouterr().err == f"callboard: {error}\n"


def test_an_argument_that_is_not_utf8_is_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert _callboard("join", "niels", "--human", "--as", "x\udcff") == 2
    assert capsys.readouterr().err == "callboard: an argument is not valid UTF-8 text\n"


def _handle_taken(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    capsys.readouterr()
    assert _callboard(*argv, "--json") == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "handle_taken"
    return str(error["message"])


@pytest.mark.parametrize(("handle", "route"), [("enki", "enki"), ("nanna", "nanna")])
def test_join_human_cannot_take_a_handle_whose_agent_route_still_resolves(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str], handle: str, route: str
) -> None:
    seed((handle, route))
    bellhop.replay("sessions", "sessions.json")
    bellhop.replay("agents", "agents.json")
    assert _handle_taken(capsys, "join", handle, "--human") == (
        f"handle '{handle}' is taken by agent route {route}, which bellhop still knows;"
        " pick another handle"
    )
    assert _rows()[0][:3] == (handle, "agent", route)


def test_join_human_refuses_when_bellhop_cannot_say_the_session_ended(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    bellhop.replay("whoami", "whoami.json")
    assert _callboard("join", "enki") == 0
    assert _handle_taken(capsys, "join", "enki", "--human") == (
        "handle 'enki' is taken by agent route enki, and bellhop cannot say whether that route"
        " still resolves (bellhop sessions printed no schema_version 1 JSON (exit 2): fake"
        " bellhop: no fixture for 'sessions'); pick another handle"
    )


def test_join_human_takes_a_handle_whose_agent_session_ended(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(("scribe", "gone-session"))
    bellhop.replay("sessions", "sessions.json")
    bellhop.replay("agents", "agents.json")
    assert _callboard("join", "scribe", "--human") == 0
    assert _rows()[0][:3] == ("scribe", "human", None)


def test_an_agent_cannot_take_a_humans_handle(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _callboard("join", "niels", "--human") == 0
    bellhop.replay("whoami", "whoami.json")
    assert _handle_taken(capsys, "join", "niels") == (
        "handle 'niels' is taken by a human; pick another handle"
    )
    assert _rows() == [("niels", "human", None, "2026-11-14T09:00:00Z")]


def test_join_human_takes_an_agent_handle_that_lost_its_route(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    bellhop.replay("whoami", "whoami.json")
    assert _callboard("join", "enki") == 0
    assert _callboard("join", "enkii") == 0
    capsys.readouterr()
    assert _callboard("join", "enki", "--human", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert (payload["participant"], payload["warnings"]) == (
        {"handle": "enki", "kind": "human", "route": None, "created_at": "2026-11-14T09:00:00Z"},
        ["rebound 'enki' from no route to human, no route"],
    )


def test_a_mistyped_flag_on_a_command_without_text_gets_no_dash_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _callboard("who", "-json") == 2
    assert capsys.readouterr().err == "callboard: unrecognized arguments: -json\n"


def test_a_dash_text_error_names_the_double_dash(capsys: pytest.CaptureFixture[str]) -> None:
    assert _callboard("--as", "niels", "dm", "nanna", "-x") == 2
    assert capsys.readouterr().err == (
        "callboard: unrecognized arguments: -x; a TEXT that starts with '-' goes after --,"
        " as in: callboard dm nanna -- -x\n"
    )


def test_join_json_names_the_participant_and_what_it_replaced(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    bellhop.replay("whoami", "whoami.json")
    assert _callboard("join", "enkii") == 0
    capsys.readouterr()
    assert _callboard("join", "enki", "--json") == 0
    enki = {
        "handle": "enki",
        "kind": "agent",
        "route": "enki",
        "created_at": "2026-11-14T09:00:00Z",
    }
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "status": "ok",
        "warnings": ["moved this session from 'enkii' to 'enki' (route enki)"],
        "participant": enki,
        "previous": None,
        "displaced": ["enkii"],
    }
