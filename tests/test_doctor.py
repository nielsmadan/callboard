import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from callboard.cli.dispatch import run
from callboard.cli.doctor import Check, check_data_dir, check_store
from callboard.paths import data_dir, store_path
from callboard.store import join_participant, open_store
from helpers import FAKES, FakeBellhop, runtime


def _doctor(capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, object]]:
    code = run(["doctor", "--json"], runtime())
    return code, json.loads(capsys.readouterr().out)


def _statuses(payload: dict[str, object]) -> dict[str, str]:
    checks = payload["checks"]
    assert isinstance(checks, list)
    return {check["name"]: check["status"] for check in checks}


def _seed(*members: tuple[str, str | None]) -> None:
    with closing(open_store(store_path(os.environ))) as conn:
        for handle, route in members:
            join_participant(conn, handle, "agent" if route else "human", route, "t")


def test_a_fresh_install_warns_about_the_missing_store_and_passes(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    code, payload = _doctor(capsys)
    assert code == 0
    assert payload["status"] == "ok"
    assert _statuses(payload) == {
        "data_dir": "warn",
        "store": "warn",
        "bellhop": "ok",
        "routes": "ok",
    }
    assert payload["unresolved"] == []
    assert not data_dir(os.environ).exists()


def test_routes_that_no_longer_resolve_are_listed(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    bellhop.replay("sessions", "sessions.json")
    _seed(
        ("enki", "enki"),
        ("reviewer", "7c1d0b5e-4a2f-4c8e-9d3b-1f6a2e8c0d47"),
        ("gone", "0b0b0b0b-dead-4c8e-9d3b-1f6a2e8c0d47"),
        ("niels", None),
    )
    code, payload = _doctor(capsys)
    assert code == 0
    assert _statuses(payload) == {
        "data_dir": "ok",
        "store": "ok",
        "bellhop": "ok",
        "routes": "warn",
    }
    assert payload["unresolved"] == [
        {"handle": "gone", "route": "0b0b0b0b-dead-4c8e-9d3b-1f6a2e8c0d47"}
    ]
    assert bellhop.calls() == [["sessions", "--json"]]


def test_all_routes_resolving_passes_in_text(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    bellhop.replay("sessions", "sessions.json")
    _seed(("enki", "enki"))
    assert run(["doctor"], runtime()) == 0
    assert capsys.readouterr() == (
        (
            f"ok    data_dir  {data_dir(os.environ)}\n"
            "ok    store     schema version 1, 1 participants\n"
            f"ok    bellhop   {FAKES / 'bellhop'}\n"
            "ok    routes    1 routes resolve\n"
        ),
        "",
    )


def test_a_failing_bellhop_sessions_call_is_a_warning(
    bellhop: FakeBellhop, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(("enki", "enki"))
    code, payload = _doctor(capsys)
    assert code == 0
    checks = payload["checks"]
    assert isinstance(checks, list)
    assert checks[3] == {
        "name": "routes",
        "status": "warn",
        "detail": "cannot check routes; bellhop sessions printed no schema_version 1 JSON (exit 2)",
    }


def test_missing_bellhop_fails_with_the_error_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(("enki", "enki"))
    code, payload = _doctor(capsys)
    assert code == 1
    assert {key: payload[key] for key in ("schema_version", "status", "exit_code", "error")} == {
        "schema_version": 1,
        "status": "error",
        "exit_code": 1,
        "error": {"code": "doctor_failed", "message": "1 check failed: bellhop"},
    }
    assert _statuses(payload) == {
        "data_dir": "ok",
        "store": "ok",
        "bellhop": "fail",
        "routes": "warn",
    }


def test_failures_are_named_on_stderr_in_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "file-home"))
    (tmp_path / "file-home").mkdir()
    (tmp_path / "file-home" / "callboard").write_text("")
    assert run(["doctor"], runtime()) == 1
    captured = capsys.readouterr()
    assert captured.err == "callboard: 2 checks failed: data_dir, bellhop\n"
    assert captured.out.splitlines()[0] == (
        f"fail  data_dir  {tmp_path / 'file-home' / 'callboard'} is not a directory"
    )


def test_data_dir_checks(tmp_path: Path) -> None:
    uid = os.getuid()
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    assert check_data_dir(tmp_path, uid) == Check("data_dir", "ok", str(tmp_path))
    assert check_data_dir(tmp_path, uid + 1) == Check(
        "data_dir", "fail", f"{tmp_path} is owned by uid {uid}, not {uid + 1}"
    )
    assert check_data_dir(locked, uid) == Check("data_dir", "fail", f"{locked} is not writable")


def test_store_checks(tmp_path: Path) -> None:
    path = tmp_path / "callboard.sqlite"
    open_store(path).close()
    assert check_store(path) == (Check("store", "ok", "schema version 1, 0 participants"), [])
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("UPDATE meta SET value = '3' WHERE key = 'schema_version'")
        conn.commit()
    assert check_store(path) == (
        Check("store", "fail", "schema version 3 is newer than this callboard (1)"),
        [],
    )
    empty = tmp_path / "empty.sqlite"
    sqlite3.connect(empty).close()
    assert check_store(empty) == (
        Check("store", "warn", "schema version 0; migrates to 1 on next use"),
        [],
    )
    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_bytes(b"definitely not sqlite" * 50)
    check, members = check_store(corrupt)
    assert (check.status, members) == ("fail", [])
    assert check.detail.startswith(f"cannot read {corrupt}: ")


def test_an_inaccessible_data_dir_fails_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(("niels", None))
    directory = data_dir(os.environ)
    directory.chmod(0o000)
    try:
        code, payload = _doctor(capsys)
    finally:
        directory.chmod(0o700)
    assert code == 1
    checks = payload["checks"]
    assert isinstance(checks, list)
    assert checks[:2] == [
        {"name": "data_dir", "status": "fail", "detail": f"{directory} is not writable"},
        {
            "name": "store",
            "status": "fail",
            "detail": f"cannot access {directory / 'callboard.sqlite'}: Permission denied",
        },
    ]


def test_an_unstatable_data_dir_fails_cleanly(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    parent.chmod(0o000)
    try:
        assert check_data_dir(parent / "callboard", os.getuid()) == Check(
            "data_dir", "fail", f"cannot access {parent / 'callboard'}: Permission denied"
        )
    finally:
        parent.chmod(0o700)
