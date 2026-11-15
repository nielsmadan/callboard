import itertools
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, NamedTuple, Protocol

import pytest

from callboard.models import Runtime
from callboard.paths import store_path
from callboard.store import join_participant, open_store

FAKES = Path(__file__).resolve().parent / "fakes"
GOLDEN = Path(__file__).resolve().parent / "golden"


class FakeBellhop:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, log: Path) -> None:
        self._monkeypatch = monkeypatch
        self.log = log

    def replay(self, command: str, fixture: str) -> None:
        self._monkeypatch.setenv(f"FAKE_BELLHOP_{command.upper()}", fixture)

    def behave(
        self, *, sleep: float = 0, exit_code: int | None = None, raw: str | None = None
    ) -> None:
        self._monkeypatch.setenv("FAKE_BELLHOP_SLEEP", str(sleep))
        if exit_code is not None:
            self._monkeypatch.setenv("FAKE_BELLHOP_EXIT", str(exit_code))
        if raw is not None:
            self._monkeypatch.setenv("FAKE_BELLHOP_RAW", raw)

    def keyed_ids(self) -> None:
        self._monkeypatch.setenv("FAKE_BELLHOP_KEYED_IDS", "1")

    def entries(self) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def calls(self) -> list[list[str]]:
        return [entry["argv"] for entry in self.entries()]


CLOCK = "2026-11-14T09:00:00Z"


def runtime(stdin: str = "", clock: str = CLOCK) -> Runtime:
    counter = itertools.count(1)
    return Runtime(os.environ, lambda: clock, lambda: f"{next(counter):012x}", lambda: stdin)


class Result(NamedTuple):
    code: int
    out: str
    err: str

    def json(self) -> dict[str, Any]:
        payload = json.loads(self.out)
        assert isinstance(payload, dict)
        return payload


class Callboard(Protocol):
    def __call__(self, *argv: str, stdin: str = "", deadline: float = 20.0) -> Result: ...


def seed(*people: tuple[str, str | None]) -> None:
    with closing(open_store(store_path(os.environ))) as conn:
        for handle, route in people:
            join_participant(conn, handle, "agent" if route else "human", route, CLOCK)


def rows(sql: str, *params: object) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(store_path(os.environ))) as conn:
        return conn.execute(sql, params).fetchall()


def load_golden(name: str) -> object:
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


def chat_scenario(cb: Callboard) -> None:
    seed(("enki", "enki"), ("nanna", "sess-nanna"), ("niels", None))
    steps = [
        (
            "--as",
            "enki",
            "group",
            "create",
            "ops",
            "--members",
            "nanna,niels",
            "--project",
            "bellhop",
        ),
        ("--as", "enki", "dm", "nanna", "first line\nsecond line"),
        ("--as", "enki", "group", "send", "ops", "@nanna please review"),
        ("--as", "niels", "group", "send", "ops", "on it", "--reply-to", "cb_000000000002"),
    ]
    assert [cb(*step).code for step in steps] == [0] * len(steps)
