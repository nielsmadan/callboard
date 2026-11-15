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
from helpers import FakeBellhop, runtime

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
        " to join without a session, run: callboard join <handle> --human\n"
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
    )


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
        "callboard: moved route enki from 'enkii' to 'enki'\n",
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
        conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
        conn.commit()
    capsys.readouterr()
    assert _callboard("who") == 1
    assert capsys.readouterr().err == (
        "callboard: store schema version 2 is newer than this callboard supports (1);"
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
