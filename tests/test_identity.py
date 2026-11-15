import os
import sqlite3
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from callboard.bellhop_client import Caller, caller_for
from callboard.errors import CallboardError
from callboard.identity import resolve_caller, route_of, validate_handle, whoami
from callboard.models import BellhopSession
from callboard.store import join_participant, open_store
from helpers import FakeBellhop

ENKI_SESSION = "2e2042a9-937c-4e03-ba25-74b5ba14a58f"
UNNAMED_SESSION = "2e20ffff-0000-4000-8000-000000000002"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = open_store(tmp_path / "store" / "callboard.sqlite")
    yield connection
    connection.close()


def _bell(env: Mapping[str, str], budget: float = 20.0) -> Caller:
    return caller_for(("bellhop",), env, budget)


def _script(directory: Path, body: str) -> None:
    directory.mkdir(exist_ok=True)
    path = directory / "bellhop"
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


def _error(caught: pytest.ExceptionInfo[CallboardError]) -> tuple[str, int, str]:
    return caught.value.code, caught.value.exit_code, str(caught.value)


@pytest.mark.parametrize("handle", ["enki", "a", "0x", "agent_7", "re-view"])
def test_valid_handles_pass(handle: str) -> None:
    assert validate_handle(handle) == handle


@pytest.mark.parametrize("handle", ["", "Enki", "-x", "_x", "a b", "a.b", "é"])
def test_invalid_handles_are_usage_errors(handle: str) -> None:
    with pytest.raises(CallboardError) as caught:
        validate_handle(handle, "--as")
    assert _error(caught) == (
        "usage",
        2,
        (
            f"--as '{handle}' is not a valid handle; use lowercase letters, digits, '_' and '-',"
            " starting with a letter or digit"
        ),
    )


def test_whoami_reads_an_agent_bound_session(bellhop: FakeBellhop) -> None:
    bellhop.replay("whoami", "whoami.json")
    session = whoami(_bell(os.environ))
    assert session == BellhopSession(ENKI_SESSION, "claude", "alpha", "enki")
    assert route_of(session) == "enki"
    assert bellhop.calls() == [["whoami", "--json"]]


def test_whoami_without_an_agent_routes_by_session_id(bellhop: FakeBellhop) -> None:
    bellhop.replay("whoami", "whoami-no-agent.json")
    session = whoami(_bell(os.environ))
    assert session == BellhopSession(UNNAMED_SESSION, "codex", "beta", None)
    assert route_of(session) == UNNAMED_SESSION


def test_whoami_outside_a_session_is_not_found(bellhop: FakeBellhop) -> None:
    bellhop.replay("whoami", "whoami-caller-unknown.json")
    with pytest.raises(CallboardError) as caught:
        whoami(_bell(os.environ))
    assert _error(caught) == (
        "not_in_session",
        3,
        "bellhop whoami: CODEX_THREAD_ID=not-live is not a live session hooklinesinker lists",
    )


def test_whoami_without_bellhop_on_path_fails() -> None:
    with pytest.raises(CallboardError) as caught:
        whoami(_bell(os.environ))
    assert _error(caught) == ("bellhop_failed", 1, "bellhop not found on PATH")


def test_whoami_passes_hls_unavailable_through(tmp_path: Path) -> None:
    _script(
        tmp_path / "bin",
        """echo '{"schema_version":1,"status":"error","exit_code":5,"error":{"code":"hls_unavailable","message":"hls timed out"}}'
exit 5""",
    )
    with pytest.raises(CallboardError) as caught:
        whoami(_bell({"PATH": str(tmp_path / "bin")}))
    assert _error(caught) == ("hls_unavailable", 5, "bellhop whoami: hls timed out")


def test_whoami_reports_other_bellhop_errors_as_failures(tmp_path: Path) -> None:
    _script(
        tmp_path / "bin",
        """echo '{"schema_version":1,"status":"error","exit_code":1,"error":"broken"}'
exit 1""",
    )
    with pytest.raises(CallboardError) as caught:
        whoami(_bell({"PATH": str(tmp_path / "bin")}))
    assert _error(caught) == ("bellhop_failed", 1, "bellhop whoami: no message")


@pytest.mark.parametrize(
    ("output", "message"),
    [
        ("not json", "bellhop whoami printed no schema_version 1 JSON (exit 0)"),
        (
            '{"schema_version":2,"status":"ok"}',
            "bellhop whoami printed no schema_version 1 JSON (exit 0)",
        ),
        ('{"schema_version":1,"status":"ok","session":{}}', "bellhop whoami returned no session"),
    ],
)
def test_whoami_rejects_unexpected_output(tmp_path: Path, output: str, message: str) -> None:
    _script(tmp_path / "bin", f"echo '{output}'")
    with pytest.raises(CallboardError) as caught:
        whoami(_bell({"PATH": str(tmp_path / "bin")}))
    assert _error(caught) == ("bellhop_failed", 1, message)


def test_whoami_gives_up_after_the_timeout(tmp_path: Path) -> None:
    _script(tmp_path / "bin", "exec /bin/sleep 5")
    with pytest.raises(CallboardError) as caught:
        whoami(_bell({"PATH": str(tmp_path / "bin")}, 0.2))
    assert _error(caught) == ("bellhop_failed", 1, "bellhop whoami timed out after 0.2s")


def test_whoami_reports_a_bellhop_that_cannot_run(tmp_path: Path) -> None:
    _script(tmp_path / "bin", "")
    (tmp_path / "bin" / "bellhop").write_text("#!/nonexistent/interpreter\n")
    with pytest.raises(CallboardError) as caught:
        whoami(_bell({"PATH": str(tmp_path / "bin")}))
    assert caught.value.code == "bellhop_failed"
    assert str(caught.value).startswith("cannot run bellhop whoami: ")


def test_as_flag_wins_over_env_and_session(
    conn: sqlite3.Connection, bellhop: FakeBellhop, monkeypatch: pytest.MonkeyPatch
) -> None:
    for handle, route in [("ana", None), ("ben", None), ("enki", "enki")]:
        join_participant(conn, handle, "agent", route, "t")
    bellhop.replay("whoami", "whoami.json")
    monkeypatch.setenv("CALLBOARD_AS", "ben")
    assert resolve_caller(conn, "ana", _bell(os.environ)).handle == "ana"
    assert resolve_caller(conn, None, _bell(os.environ)).handle == "ben"
    monkeypatch.delenv("CALLBOARD_AS")
    assert resolve_caller(conn, None, _bell(os.environ)).handle == "enki"
    assert bellhop.calls() == [["whoami", "--json"]]


def test_session_is_matched_by_agent_name_before_session_id(
    conn: sqlite3.Connection, bellhop: FakeBellhop
) -> None:
    join_participant(conn, "by-session", "agent", ENKI_SESSION, "t")
    bellhop.replay("whoami", "whoami.json")
    assert resolve_caller(conn, None, _bell(os.environ)).handle == "by-session"
    join_participant(conn, "by-agent", "agent", "enki", "t")
    assert resolve_caller(conn, None, _bell(os.environ)).handle == "by-agent"


def test_an_unknown_explicit_handle_is_not_found(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(CallboardError) as caught:
        resolve_caller(conn, "ghost", _bell(os.environ))
    assert _error(caught) == (
        "unknown_handle",
        3,
        "--as: no participant 'ghost'; run: callboard join ghost",
    )
    monkeypatch.setenv("CALLBOARD_AS", "Bad Name")
    with pytest.raises(CallboardError) as caught:
        resolve_caller(conn, None, _bell(os.environ))
    assert caught.value.exit_code == 2


def test_an_unjoined_session_is_not_found_with_the_join_hint(
    conn: sqlite3.Connection, bellhop: FakeBellhop
) -> None:
    bellhop.replay("whoami", "whoami-no-agent.json")
    with pytest.raises(CallboardError) as caught:
        resolve_caller(conn, None, _bell(os.environ))
    assert _error(caught) == (
        "identity_not_found",
        3,
        "this session has not joined callboard; run: callboard join <handle>",
    )


def test_no_session_at_all_is_not_found_with_the_join_hint(
    conn: sqlite3.Connection, bellhop: FakeBellhop
) -> None:
    bellhop.replay("whoami", "whoami-caller-unknown.json")
    with pytest.raises(CallboardError) as caught:
        resolve_caller(conn, None, _bell(os.environ))
    assert _error(caught) == (
        "identity_not_found",
        3,
        (
            "cannot tell who you are; bellhop whoami: CODEX_THREAD_ID=not-live is not a live session hooklinesinker lists;"
            " run: callboard join <handle>"
        ),
    )


def test_two_handles_on_one_route_are_ambiguous(
    conn: sqlite3.Connection, bellhop: FakeBellhop
) -> None:
    conn.executemany(
        "INSERT INTO participants (handle, kind, route, created_at) VALUES (?, 'agent', 'enki', 't')",
        [("one",), ("two",)],
    )
    bellhop.replay("whoami", "whoami.json")
    with pytest.raises(CallboardError) as caught:
        resolve_caller(conn, None, _bell(os.environ))
    assert _error(caught) == (
        "identity_ambiguous",
        3,
        "this session is joined as one, two; pass --as HANDLE",
    )


def test_hls_or_bellhop_failures_are_not_reported_as_unjoined(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    with pytest.raises(CallboardError) as caught:
        resolve_caller(conn, None, _bell({"PATH": str(tmp_path / "empty")}))
    assert _error(caught) == ("bellhop_failed", 1, "bellhop not found on PATH")
    _script(
        tmp_path / "bin",
        """echo '{"schema_version":1,"status":"error","exit_code":5,"error":{"code":"hls_unavailable","message":"hls timed out"}}'
exit 5""",
    )
    with pytest.raises(CallboardError) as caught:
        resolve_caller(conn, None, _bell({"PATH": str(tmp_path / "bin")}))
    assert _error(caught) == ("hls_unavailable", 5, "bellhop whoami: hls timed out")
