import io
import itertools
import json
import os
import queue
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

import pytest

from callboard import observe
from callboard.cli import admin
from callboard.cli.admin import (
    Seams,
    file_identity,
    json_formats,
    open_watched,
    print_line,
    stdin_wait,
    stream,
    text_formats,
)
from callboard.errors import CallboardError
from callboard.models import ADMIN_BODY_LIMIT
from callboard.observe import MAX_BATCH, MAX_BODY_BYTES, batch, fingerprint
from callboard.paths import attachments_dir, store_path
from callboard.store import open_readonly
from helpers import CLOCK, Callboard, FakeBellhop, chat_scenario, load_golden, seed

type Step = Callable[[], None]
type Opener = Callable[[Path], sqlite3.Connection | None]


@pytest.fixture
def scenario(cb: Callboard, ringing: FakeBellhop) -> None:
    chat_scenario(cb)


def store() -> Path:
    return store_path(os.environ)


@contextmanager
def opened() -> Iterator[sqlite3.Connection]:
    conn = open_readonly(store())
    assert conn is not None
    with closing(conn):
        yield conn


def ok(cb: Callboard, *argv: str) -> Step:
    def step() -> None:
        result = cb(*argv)
        assert result.code == 0, result.err

    return step


def insert(conversation_id: str, sender: str, bodies: list[str]) -> None:
    with closing(sqlite3.connect(store())) as conn, conn:
        start = int(conn.execute("SELECT coalesce(max(seq), 0) FROM messages").fetchone()[0])
        conn.executemany(
            "INSERT INTO messages (id, conversation_id, sender, body, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                (f"cb_bulk{start + index:08d}", conversation_id, sender, body, CLOCK)
                for index, body in enumerate(bodies, start=1)
            ],
        )


class Script:
    def __init__(self, *steps: Step) -> None:
        self.steps = list(steps)
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> bool:
        self.waits.append(seconds)
        if seconds == 0:
            return True
        if not self.steps:
            return False
        self.steps.pop(0)()
        return True


def watched(
    *steps: Step, open_store: Opener = open_watched, clock: Callable[[], float] = time.monotonic
) -> tuple[list[dict[str, Any]], Script]:
    script = Script(*steps)
    lines: list[str] = []
    seams = Seams(script, lines.append, file_identity, open_store, clock)
    formats = json_formats(store(), attachments_dir(os.environ))
    assert stream(store(), 0.25, formats, seams) == 0
    return [json.loads(line) for line in lines], script


def summary(event: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(
        item for item in event["conversations"] if item["id"] == conversation_id
    )
    return found


def seqs(events: list[dict[str, Any]]) -> list[list[int]]:
    return [
        [item["seq"] for item in event["messages"]]
        for event in events
        if event["event"] == "messages"
    ]


def busy_error(code: int = sqlite3.SQLITE_BUSY) -> sqlite3.OperationalError:
    error = sqlite3.OperationalError("database is locked")
    error.sqlite_errorcode = code
    return error


def busy_store(failures: int, code: int = sqlite3.SQLITE_BUSY) -> Opener:
    remaining = [failures]

    class Busy(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            if sql == "BEGIN" and remaining[0] > 0:
                remaining[0] -= 1
                raise busy_error(code)
            return super().execute(sql, parameters)

    def open_store(path: Path) -> sqlite3.Connection:
        uri = path.absolute().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, isolation_level=None, factory=Busy)
        conn.row_factory = sqlite3.Row
        return conn

    return open_store


@pytest.mark.usefixtures("scenario")
def test_batch_returns_new_messages_with_their_conversations_after_the_batch() -> None:
    with opened() as conn:
        found, _ = batch(conn, 1)
    assert [(item.seq, item.message.body) for item in found.messages] == [
        (2, "@nanna please review"),
        (3, "on it"),
    ]
    assert [(item.conversation.id, item.messages, item.first_seq) for item in found.touched] == [
        ("group:ops", 2, 2)
    ]
    assert (found.cursor, found.full) == (3, False)


@pytest.mark.usefixtures("scenario")
def test_batch_stops_at_the_message_cap() -> None:
    insert("group:ops", "enki", [f"bulk {index}" for index in range(MAX_BATCH + 50)])
    with opened() as conn:
        first, _ = batch(conn, 3)
        rest, _ = batch(conn, first.cursor)
    assert (len(first.messages), first.cursor, first.full) == (MAX_BATCH, 3 + MAX_BATCH, True)
    assert first.touched[0].messages == 2 + MAX_BATCH
    assert first.touched[0].last is not None
    assert first.touched[0].last.seq == first.cursor
    assert (len(rest.messages), rest.full) == (50, False)
    assert rest.touched[0].messages == 2 + MAX_BATCH + 50


@pytest.mark.usefixtures("scenario")
def test_batch_cap_counts_the_bodies_as_emitted_after_the_cut() -> None:
    per_body = ADMIN_BODY_LIMIT + 2
    fits = MAX_BODY_BYTES // per_body
    insert("group:ops", "enki", ["a" * (ADMIN_BODY_LIMIT * 16)] * (fits + 1))
    with opened() as conn:
        first, _ = batch(conn, 3)
        rest, _ = batch(conn, first.cursor)
    assert (len(first.messages), first.full) == (fits, True)
    assert (len(rest.messages), rest.full) == (1, False)


@pytest.mark.usefixtures("scenario")
def test_the_body_cap_counts_escaped_bytes() -> None:
    escaped = "\x01" * ADMIN_BODY_LIMIT
    fits = MAX_BODY_BYTES // (6 * ADMIN_BODY_LIMIT + 2)
    insert("group:ops", "enki", [escaped] * (fits + 1))
    with opened() as conn:
        first, _ = batch(conn, 3)
        rest, _ = batch(conn, first.cursor)
    assert (len(first.messages), first.full) == (fits, True)
    assert (len(rest.messages), rest.full) == (1, False)


def fingerprint_now() -> str:
    with opened() as conn:
        return fingerprint(conn)


@pytest.mark.usefixtures("ringing")
def test_the_fingerprint_follows_conversations_and_members(cb: Callboard) -> None:
    seed(("enki", None), ("nanna", None), ("utu", None), ("an", None))
    changes = [
        ("--as", "enki", "group", "create", "ops", "--members", "nanna"),
        ("--as", "enki", "dm", "nanna", "hello"),
        ("--as", "enki", "group", "add", "ops", "utu"),
        ("--as", "enki", "group", "remove", "ops", "nanna"),
    ]
    prints = [fingerprint_now()]
    for change in changes:
        ok(cb, *change)()
        prints.append(fingerprint_now())
    assert len(set(prints)) == len(prints)


@pytest.mark.usefixtures("ringing")
def test_the_fingerprint_sees_a_member_swap_that_reuses_the_rowid(cb: Callboard) -> None:
    seed(("enki", None), ("nanna", None), ("utu", None), ("an", None))
    ok(cb, "--as", "enki", "group", "create", "ops", "--members", "nanna,utu")()
    before = fingerprint_now()
    rowid = "SELECT count(*), max(rowid) FROM members"
    with closing(sqlite3.connect(store())) as conn:
        counted = conn.execute(rowid).fetchone()
    ok(cb, "--as", "enki", "group", "remove", "ops", "utu")()
    ok(cb, "--as", "enki", "group", "add", "ops", "an")()
    with closing(sqlite3.connect(store())) as conn:
        assert conn.execute(rowid).fetchone() == counted
    assert fingerprint_now() != before


@pytest.mark.usefixtures("scenario")
def test_the_fingerprint_stays_after_a_plain_send(cb: Callboard) -> None:
    before = fingerprint_now()
    ok(cb, "--as", "nanna", "group", "send", "ops", "lgtm")()
    assert fingerprint_now() == before


@pytest.mark.usefixtures("scenario")
def test_watch_starts_with_a_snapshot_and_exits_on_eof() -> None:
    events, script = watched()
    assert [(event["event"], event["cursor"]) for event in events] == [("snapshot", 3)]
    assert events[0]["store"] == str(store())
    assert [item["id"] for item in events[0]["conversations"]] == ["group:ops", "dm:enki:nanna"]
    assert script.waits == [0.25]


@pytest.mark.usefixtures("scenario")
def test_messages_committed_between_waits_arrive_once(cb: Callboard) -> None:
    def two() -> None:
        ok(cb, "--as", "nanna", "dm", "enki", "merged")()
        ok(cb, "--as", "enki", "group", "send", "ops", "thanks")()

    events, _ = watched(
        ok(cb, "--as", "nanna", "group", "send", "ops", "lgtm"), lambda: None, two, lambda: None
    )
    assert [event["event"] for event in events] == ["snapshot", "messages", "messages"]
    assert seqs(events) == [[4], [5, 6]]
    assert events[2]["cursor"] == 6
    assert [item["id"] for item in events[2]["conversations"]] == ["group:ops", "dm:enki:nanna"]
    assert summary(events[2], "group:ops")["last"]["preview"] == "thanks"
    assert events[1]["messages"][0]["body_truncated"] is False


@pytest.mark.usefixtures("scenario")
def test_watch_lines_match_the_goldens(cb: Callboard) -> None:
    reply = ("--as", "nanna", "group", "send", "ops", "lgtm", "--reply-to", "cb_000000000003")
    events, _ = watched(ok(cb, *reply))
    snapshot = load_golden("admin-watch-snapshot.json")
    assert isinstance(snapshot, dict)
    assert events == [{**snapshot, "store": str(store())}, load_golden("admin-watch-messages.json")]


@pytest.mark.usefixtures("scenario")
def test_a_membership_change_emits_a_snapshot(cb: Callboard) -> None:
    seed(("utu", None))
    events, _ = watched(ok(cb, "--as", "enki", "group", "add", "ops", "utu"))
    assert [event["event"] for event in events] == ["snapshot", "snapshot"]
    assert summary(events[1], "group:ops")["members"] == ["enki", "nanna", "niels", "utu"]


@pytest.mark.usefixtures("ringing")
def test_a_missing_store_streams_once_it_is_created(cb: Callboard) -> None:
    def empty_file() -> None:
        store().parent.mkdir(parents=True)
        store().touch()

    events, _ = watched(lambda: None, empty_file, lambda: None, lambda: chat_scenario(cb))
    assert [(event["event"], event["cursor"]) for event in events] == [
        ("snapshot", 0),
        ("snapshot", 3),
    ]
    assert events[0]["conversations"] == []
    assert len(events[1]["conversations"]) == 2


def remove_store() -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(f"{store()}{suffix}").unlink(missing_ok=True)


@pytest.mark.usefixtures("scenario")
def test_a_replaced_store_emits_a_fresh_snapshot(cb: Callboard) -> None:
    def replace() -> None:
        remove_store()
        seed(("enki", None), ("utu", None))
        ok(cb, "--as", "enki", "group", "create", "fresh", "--members", "utu")()

    events, _ = watched(replace, remove_store, lambda: None)
    assert [(event["event"], event["cursor"]) for event in events] == [
        ("snapshot", 3),
        ("snapshot", 0),
        ("snapshot", 0),
    ]
    assert [item["id"] for item in events[1]["conversations"]] == ["group:fresh"]
    assert events[2]["conversations"] == []


@pytest.mark.usefixtures("scenario")
@pytest.mark.parametrize(
    "code",
    [
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
        sqlite3.SQLITE_BUSY_RECOVERY,
        sqlite3.SQLITE_BUSY_SNAPSHOT,
    ],
)
def test_a_busy_store_is_retried(cb: Callboard, code: int) -> None:
    nothing: Step = lambda: None  # noqa: E731
    events, script = watched(
        *[nothing] * 3,
        ok(cb, "--as", "nanna", "group", "send", "ops", "lgtm"),
        open_store=busy_store(3, code),
    )
    assert [event["event"] for event in events] == ["snapshot", "messages"]
    assert seqs(events) == [[4]]
    assert len(script.waits) == 5


@pytest.mark.usefixtures("scenario")
def test_a_busy_open_is_retried() -> None:
    attempts = [0]

    def open_store(path: Path) -> sqlite3.Connection | None:
        attempts[0] += 1
        if attempts[0] == 1:
            raise CallboardError("cannot read store", code="store_unavailable") from busy_error()
        return open_watched(path)

    events, _ = watched(lambda: None, open_store=open_store)
    assert [event["event"] for event in events] == ["snapshot"]
    assert attempts == [2]


@pytest.mark.usefixtures("scenario")
def test_a_store_busy_for_thirty_seconds_fails() -> None:
    ticks = itertools.count(0, 10)
    with pytest.raises(CallboardError, match="stayed busy for 30 seconds") as raised:
        watched(*[lambda: None] * 10, open_store=busy_store(100), clock=lambda: next(ticks))
    assert raised.value.code == "store_unavailable"


@pytest.mark.usefixtures("scenario")
def test_other_store_errors_end_the_watch() -> None:
    def broken(path: Path) -> sqlite3.Connection:
        raise sqlite3.OperationalError("disk I/O error")

    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        watched(open_store=broken)


@pytest.mark.usefixtures("scenario")
def test_a_message_committed_right_after_a_read_is_not_lost(
    cb: Callboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads = itertools.count()

    def racing(conn: sqlite3.Connection, cursor: int) -> Any:
        found = batch(conn, cursor)
        if next(reads) == 0:
            ok(cb, "--as", "enki", "group", "send", "ops", "late")()
        return found

    monkeypatch.setattr(admin, "batch", racing)
    events, _ = watched(ok(cb, "--as", "nanna", "group", "send", "ops", "lgtm"), lambda: None)
    assert seqs(events) == [[4], [5]]


@pytest.mark.usefixtures("scenario")
def test_text_mode_prints_messages_read_with_a_snapshot(cb: Callboard) -> None:
    def both() -> None:
        ok(cb, "--as", "nanna", "group", "send", "ops", "lgtm")()
        ok(cb, "--as", "enki", "group", "create", "fresh", "--members", "nanna")()

    lines: list[str] = []
    seams = Seams(Script(both), lines.append, file_identity, open_watched)
    assert stream(store(), 1.0, text_formats(store()), seams) == 0
    assert lines == [
        f"watching {store()}: 2 conversations, cursor 3",
        f"watching {store()}: 3 conversations, cursor 4",
        "#4  group:ops  nanna: lgtm",
    ]


@pytest.mark.usefixtures("scenario")
def test_text_mode_drains_a_backlog_that_arrives_with_a_snapshot(cb: Callboard) -> None:
    def both() -> None:
        insert("group:ops", "enki", [f"bulk {index}" for index in range(450)])
        ok(cb, "--as", "enki", "group", "create", "fresh", "--members", "nanna")()

    lines: list[str] = []
    seams = Seams(Script(both), lines.append, file_identity, open_watched)
    assert stream(store(), 1.0, text_formats(store()), seams) == 0
    assert [line for line in lines if line.startswith("#")] == [
        f"#{seq}  group:ops  enki: bulk {seq - 4}" for seq in range(4, 454)
    ]


@pytest.mark.usefixtures("scenario")
def test_a_snapshot_is_read_in_one_transaction(
    cb: Callboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(("utu", None))
    changed = ok(cb, "--as", "enki", "group", "add", "ops", "utu")
    original = observe._fingerprint
    calls = itertools.count()

    def racing(conn: sqlite3.Connection) -> str:
        found = original(conn)
        if next(calls) == 0:
            changed()
        return found

    monkeypatch.setattr(observe, "_fingerprint", racing)
    events, _ = watched(lambda: None)
    assert [summary(event, "group:ops")["members"] for event in events] == [
        ["enki", "nanna", "niels"],
        ["enki", "nanna", "niels", "utu"],
    ]


@pytest.mark.usefixtures("scenario")
def test_a_backlog_drains_in_batches_without_waiting() -> None:
    events, script = watched(
        lambda: insert("group:ops", "enki", [f"bulk {index}" for index in range(450)])
    )
    assert [len(batch) for batch in seqs(events)] == [200, 200, 50]
    assert events[-1]["cursor"] == 453
    assert script.waits == [0.25, 0, 0, 0.25]


@pytest.mark.usefixtures("scenario")
def test_watch_text_lines(cb: Callboard) -> None:
    lines: list[str] = []
    script = Script(ok(cb, "--as", "enki", "group", "send", "ops", "ship it\nnow"))
    seams = Seams(script, lines.append, file_identity, open_watched)
    assert stream(store(), 1.0, text_formats(store()), seams) == 0
    assert lines == [
        f"watching {store()}: 2 conversations, cursor 3",
        "#4  group:ops  enki: ship it",
    ]


@pytest.mark.usefixtures("scenario")
def test_watch_command_stops_when_stdin_is_closed(
    cb: Callboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader, writer = os.pipe()
    os.close(writer)
    with open(reader, encoding="utf-8") as stdin:
        monkeypatch.setattr(sys, "stdin", stdin)
        result = cb("admin", "watch", "--json")
    assert (result.code, result.err) == (0, "")
    assert [json.loads(line)["event"] for line in result.out.splitlines()] == ["snapshot"]


def test_stdin_wait_sees_data_then_eof() -> None:
    reader, writer = os.pipe()
    with open(reader, encoding="utf-8") as stdin:
        wait = stdin_wait(stdin)
        assert wait(0) is True
        os.write(writer, b"x")
        assert wait(1) is True
        os.close(writer)
        assert wait(1) is False


def test_stdin_wait_treats_a_bad_descriptor_as_eof() -> None:
    reader, writer = os.pipe()
    os.close(reader)
    os.close(writer)

    class Closed(io.StringIO):
        def fileno(self) -> int:
            return reader

    assert stdin_wait(Closed())(0) is False


def test_stdin_wait_without_a_pipe_only_sleeps() -> None:
    assert stdin_wait(None)(0) is True


def test_print_line_prints_one_line(capsys: pytest.CaptureFixture[str]) -> None:
    print_line("hello")
    assert capsys.readouterr().out == "hello\n"


def test_file_identity(tmp_path: Path) -> None:
    present = tmp_path / "present"
    present.touch()
    assert file_identity(present) == (present.stat().st_dev, present.stat().st_ino)
    assert file_identity(tmp_path / "absent") is None
    with pytest.raises(CallboardError, match="cannot stat store") as raised:
        file_identity(tmp_path / ("x" * 5000))
    assert raised.value.code == "store_unavailable"


@pytest.mark.parametrize("interval", ["0", "11", "x", "nan"])
def test_interval_is_bounded(cb: Callboard, interval: str) -> None:
    result = cb("admin", "watch", "--interval", interval, "--json")
    assert result.code == 2
    assert result.json()["error"]["message"] == (
        f"argument --interval: must be a number of seconds from 0.05 to 10, got '{interval}'"
    )


def test_a_valid_interval_reaches_the_stream(
    cb: Callboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[float] = []

    def fake(path: Path, interval: float, formats: Any, seams: Any) -> int:
        seen.append(interval)
        return 0

    monkeypatch.setattr(admin, "stream", fake)
    assert cb("admin", "watch", "--interval", "0.5").code == 0
    assert seen == [0.5]


def next_line(lines: "queue.Queue[str]", deadline: float) -> dict[str, Any]:
    event: dict[str, Any] = json.loads(lines.get(timeout=max(deadline - time.monotonic(), 0)))
    return event


@pytest.mark.usefixtures("scenario")
def test_watch_end_to_end(cb: Callboard) -> None:
    command = [sys.executable, "-m", "callboard", "admin", "watch", "--json", "--interval", "0.05"]
    lines: queue.Queue[str] = queue.Queue()
    with subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    ) as process:
        assert process.stdin is not None and process.stdout is not None
        output = process.stdout

        def pump() -> None:
            for line in output:
                lines.put(line)

        reader = threading.Thread(target=pump)
        reader.start()
        try:
            deadline = time.monotonic() + 10
            first = next_line(lines, deadline)
            ok(cb, "--as", "nanna", "group", "send", "ops", "lgtm")()
            event = next_line(lines, deadline)
            while event["event"] != "messages":
                event = next_line(lines, deadline)
            process.stdin.close()
            assert process.wait(timeout=5) == 0
        finally:
            process.kill()
            reader.join(timeout=5)
    assert (first["event"], first["cursor"]) == ("snapshot", 3)
    assert [(item["seq"], item["body"]) for item in event["messages"]] == [(4, "lgtm")]
