import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from importlib.metadata import distribution
from pathlib import Path
from typing import Any

import pytest
from bellhop.testing import drainer_running
from bellhop.testing.run import SmokeRun, descendants, ps
from bellhop.testing.tmux import SmokeTmux

import callboard

pytestmark = pytest.mark.smoke

REAL_ENV = dict(os.environ)
REAL_HOME = Path(REAL_ENV.get("HOME", str(Path.home())))
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache" / "smoke"
SOCKET = "callboard-smoke"
REAL_STATE = (
    REAL_HOME / ".local/share/callboard",
    REAL_HOME / ".local/state/bellhop",
    REAL_HOME / ".config/bellhop",
)
REAL_RUNTIME = Path(f"/tmp/bellhop-{os.getuid()}")  # noqa: S108
WAIT = 240.0
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
JOIN = (
    "This is a messaging test. Run the shell command `callboard join {handle}` and then reply "
    "with exactly JOINED. Later, messages starting with `callboard cb_` may arrive: do what "
    "each one asks, and when one ends with `read: callboard read <id>`, run that command. "
    "Answer in your reply; never send a callboard message unless one asks you to."
)

type Payload = dict[str, Any]
type Cell = Callable[[], Payload]


def token() -> str:
    return secrets.token_hex(4)


def allowed(handle: str, *also: str) -> tuple[str, ...]:
    return (f"callboard join {handle}", "callboard read:*", *also)


def installed_from(name: str) -> str:
    return str(json.loads(distribution(name).read_text("direct_url.json") or "{}").get("url"))


def executables() -> str:
    bindir = Path(sys.executable).parent
    found = [shutil.which(name, path=REAL_ENV["PATH"]) for name in ("callboard", "bellhop")]
    assert [Path(str(path)).parent for path in found] == [bindir, bindir], found
    shebangs = [Path(str(path)).read_text().splitlines()[0] for path in found]
    assert shebangs == [f"#!{sys.executable}"] * 2, shebangs
    assert Path(callboard.__file__).is_relative_to(ROOT / "src")
    assert installed_from("bellhop").startswith(f"file://{ROOT}/.cache/bellhop-")
    return str(bindir)


def wait_for(probe: Callable[[], Any], timeout: float = WAIT, every: float = 3.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = probe()
        if found:
            return found
        time.sleep(every)
    return None


def smoke_tmux_alive() -> bool:
    result = subprocess.run(
        ["tmux", "-L", SOCKET, "list-sessions"], capture_output=True, check=False, env=REAL_ENV
    )
    return result.returncode == 0


def real_state() -> list[tuple[str, int | bool | None]]:
    return [
        *(
            (str(path), path.lstat().st_mtime_ns if os.path.lexists(path) else None)
            for path in REAL_STATE
        ),
        (str(REAL_RUNTIME), os.path.lexists(REAL_RUNTIME)),
    ]


def leftovers() -> dict[str, object]:
    entries = sorted(CACHE.iterdir()) if CACHE.is_dir() else []
    return {
        "tmux_server": smoke_tmux_alive(),
        "processes": [proc.command[:160] for proc in ps() if str(CACHE) in proc.command],
        "symlinked_runs": [str(entry) for entry in entries if entry.is_symlink()],
    }


CLEAN = {"tmux_server": False, "processes": [], "symlinked_runs": []}
RUN_SESSIONS = frozenset(
    f"{agent}{suffix}"
    for agent in ("cl", "pi", "scribe")
    for suffix in ("", *(f"-{number}" for number in range(2, 10)))
)


class Board:
    def __init__(self, run: SmokeRun, path: str) -> None:
        self.run = run
        self.env = {**run.env, "PATH": f"{path}{os.pathsep}{run.env['PATH']}"}

    def raw(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["callboard", *args],
            capture_output=True,
            text=True,
            timeout=120,
            env=self.env,
            check=False,
        )

    def call(self, *args: str, as_handle: str = "driver") -> tuple[int, Payload]:
        result = self.raw("--as", as_handle, *args, "--json")
        payload: Payload = json.loads(result.stdout)
        return result.returncode, payload

    def bellhop(self, *args: str) -> tuple[int, Payload]:
        result = subprocess.run(
            ["bellhop", *args, "--json"],
            capture_output=True,
            text=True,
            timeout=120,
            env=self.env,
            check=False,
        )
        payload: Payload = json.loads(result.stdout)
        return result.returncode, payload

    def routes(self) -> dict[str, str | None]:
        _, payload = self.call("who")
        return {p["handle"]: p["route"] for p in payload.get("participants", [])}

    def receipt(self, message_id: str, handle: str, viewer: str = "driver") -> Payload:
        _, payload = self.call("receipts", message_id, as_handle=viewer)
        found = [r for r in payload.get("receipts", []) if r["recipient"] == handle]
        return found[0] if found else {}

    def settled(
        self,
        message_id: str,
        handle: str,
        done: Callable[[Payload], bool],
        viewer: str = "driver",
    ) -> Payload:
        found = wait_for(lambda: (r := self.receipt(message_id, handle, viewer)) and done(r) and r)
        return found if isinstance(found, dict) else self.receipt(message_id, handle, viewer)

    def lines(self, harness: str) -> list[str]:
        layout = self.run.layout
        root = layout.claude_dir / "projects" if harness == "claude" else layout.pi_dir / "sessions"
        return [
            line
            for path in sorted(root.rglob("*.jsonl"))
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        ]

    def landed(self, harness: str, *parts: str) -> bool:
        return any(all(part in line for part in parts) for line in self.lines(harness))


def read_and_confirmed(receipt: Payload) -> bool:
    return receipt.get("ping_state") == "confirmed" and receipt.get("read_at") is not None


class Cells:
    def __init__(self, board: Board, pong: str) -> None:
        self.board = board
        self.pong = pong

    def dm(self, to: str, *args: str) -> tuple[int, Payload]:
        code, payload = self.board.call("dm", to, *args)
        return code, payload.get("message", {})

    def short_dm_is_inline_and_read(self) -> Payload:
        tok = token()
        code, sent = self.dm("pi", f"Reply with exactly ACK {tok}.")
        first = sent["receipts"][0]
        final = self.board.settled(sent["id"], "pi", read_and_confirmed)
        landed = self.board.landed(
            "pi", f"{sent['id']} dm from driver: Reply with exactly ACK {tok}"
        )
        ok = (
            code == 0
            and (first["ping"], first["inline"]) == ("idle", True)
            and read_and_confirmed(final)
            and landed
        )
        return {"ok": ok, "id": sent["id"], "sent": first, "final": final, "landed": landed}

    def long_dm_with_image_is_a_doorbell(self) -> Payload:
        tok = token()
        image = self.board.run.layout.root / "pixel.png"
        image.write_bytes(PNG)
        body = "This long note only pads the message past the inline limit. " * 10
        body += f"After reading it, reply in your session with exactly READ {tok}."
        code, sent = self.dm("cl", body, "--attach", str(image))
        first = sent["receipts"][0]
        final = self.board.settled(sent["id"], "cl", read_and_confirmed)
        doorbell = self.board.landed("claude", f"{sent['id']} dm from driver (", "1 attachment")
        ok = (
            code == 0
            and (first["ping"], first["inline"]) == ("idle", False)
            and read_and_confirmed(final)
            and doorbell
        )
        return {"ok": ok, "id": sent["id"], "sent": first, "final": final, "doorbell": doorbell}

    def reply_rings_the_other_agent(self) -> Payload:
        tok = self.pong
        code, asked = self.dm(
            "cl",
            f'Run the shell command `callboard dm pi "pong {tok}"` and reply with exactly SENT.',
        )

        def reply() -> Payload | None:
            _, history = self.board.call("history", "@cl", as_handle="pi")
            found = [
                m
                for m in history.get("messages", [])
                if m["sender"] == "cl" and m["body"] == f"pong {tok}"
            ]
            return found[0] if found else None

        found = wait_for(reply)
        if not isinstance(found, dict):
            return {"ok": False, "asked": asked["id"], "detail": "cl never sent the reply"}
        final = self.board.settled(found["id"], "pi", read_and_confirmed, viewer="cl")
        landed = self.board.landed("pi", f"{found['id']} dm from cl: pong {tok}")
        ok = code == 0 and read_and_confirmed(final) and landed
        return {
            "ok": ok,
            "asked": asked["id"],
            "reply": found["id"],
            "final": final,
            "landed": landed,
        }

    def group_mention_rings_only_the_mentioned(self) -> Payload:
        created = self.board.raw(
            "--as", "driver", "group", "create", "smoke", "--members", "cl,pi,driver"
        ).returncode
        tok = token()
        code, payload = self.board.call(
            "group", "send", "smoke", f"@pi reply with exactly ACK {tok}"
        )
        sent = payload.get("message", {})
        rings = {r["recipient"]: r["ping"] for r in sent.get("receipts", [])}
        final = self.board.settled(sent["id"], "pi", read_and_confirmed)
        landed = self.board.landed("pi", f"{sent['id']} group smoke from driver", tok)
        time.sleep(15)
        cl_silent = not self.board.landed("claude", tok)
        ok = (
            (created, code) == (0, 0)
            and rings == {"cl": "none", "pi": "idle"}
            and read_and_confirmed(final)
            and landed
            and cl_silent
        )
        return {
            "ok": ok,
            "id": sent["id"],
            "rings": rings,
            "final": final,
            "landed": landed,
            "cl_silent": cl_silent,
        }

    def mail_waits_and_shows_in_inbox(self) -> Payload:
        tok = token()
        code, payload = self.board.call(
            "mail", "send", "--to", "cl", "--subject", f"smoke {tok}", "Nothing to do here."
        )
        mail = payload.get("message", {})
        held = mail["receipts"][0]
        _, inbox = self.board.call("inbox", as_handle="cl")
        threads = [
            (c["kind"], c["unread"], c["sender"])
            for c in inbox.get("conversations", [])
            if c.get("subject") == f"smoke {tok}"
        ]
        nudge = token()
        _, sent = self.dm("cl", f"Reply with exactly ACK {nudge}.")
        final = self.board.settled(sent["id"], "cl", read_and_confirmed)
        waiting = self.board.landed("claude", nudge, "1 more waiting")
        ok = (
            code == 0
            and (held["ping"], held["ping_state"]) == ("hold", "pending")
            and read_and_confirmed(final)
            and waiting
            and threads == [("mail", 1, "driver")]
        )
        return {
            "ok": ok,
            "mail": mail["id"],
            "held": held,
            "nudge": sent["id"],
            "final": final,
            "waiting_line": waiting,
            "inbox": threads,
        }


def run_cells(cells: Mapping[str, Cell]) -> dict[str, Payload]:
    results: dict[str, Payload] = {}
    for name, cell in cells.items():
        try:
            results[name] = cell()
        except Exception as error:  # noqa: BLE001
            results[name] = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    return results


def smoke_run(claude_allowed: tuple[str, ...]) -> SmokeRun:
    return SmokeRun(
        CACHE,
        REAL_ENV,
        socket=SOCKET,
        sops_exec=REAL_HOME / "ac" / "bin" / "sops-exec",
        hls_source=REAL_HOME / ".local/share/hooklinesinker/bin/hooklinesinker",
        user_home=REAL_HOME,
        claude_allowed=claude_allowed,
    )


def isolated(run: SmokeRun) -> bool:
    keys = ("HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "PI_CODING_AGENT_DIR", "TMPDIR")
    xdg = [key for key in run.env if key.startswith("XDG_")]
    root = run.layout.root.resolve()
    inside = [Path(run.env[key]).resolve().is_relative_to(root) for key in (*keys, *xdg)]
    runtime = run.env["BELLHOP_RUNTIME_DIR"] == str(run.layout.runtime_dir)
    return (
        all(inside)
        and len(xdg) == 4
        and runtime
        and run.layout.runtime_dir.name.endswith(run.run_id)
    )


def launch(run: SmokeRun, board: Board) -> None:
    claude = run.layout.root / "claude-integration"
    pi = run.layout.root / "pi-integration"
    assert board.bellhop("integration", "export", "claude", "--to", str(claude))[0] == 0
    assert board.bellhop("integration", "export", "pi", "--to", str(pi))[0] == 0
    path = {"PATH": board.env["PATH"]}
    run.launch(
        "claude",
        "cl",
        extra=[
            "--mcp-config",
            str(claude / "bellhop-mcp.json"),
            "--strict-mcp-config",
            "--",
        ],
        prompt=JOIN.format(handle="cl"),
        env=path,
    )
    run.launch(
        "pi", "pi", extra=["-e", str(pi / "bellhop.ts")], prompt=JOIN.format(handle="pi"), env=path
    )
    run.wait_ready("cl")
    run.wait_ready("pi")


def default_sessions() -> list[str]:
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True,
        text=True,
        check=False,
        env={key: value for key, value in REAL_ENV.items() if key != "TMUX"},
    )
    return sorted(result.stdout.split())


def attempt(label: str, step: Callable[[], list[str]]) -> list[str]:
    try:
        return step()
    except Exception as error:  # noqa: BLE001
        return [f"{label} failed: {type(error).__name__}: {error}"]


def strays(default_before: list[str]) -> list[str]:
    return sorted((set(default_sessions()) - set(default_before)) & RUN_SESSIONS)


def closing_problems(
    run: SmokeRun, board: Board, state: object, default_before: list[str]
) -> list[str]:
    after = leftovers()
    found = strays(default_before)
    checks = {
        f"this run's agent sessions on the default tmux server: {found}": bool(found),
        f"leftovers after the run: {after}": after != CLEAN,
        f"helper leftovers: {run.leftovers}": bool(run.leftovers),
        f"runtime dir {run.layout.runtime_dir} still exists": run.layout.runtime_dir.exists(),
        f"real state changed: {real_state()}": real_state() != state,
        "the run's drainer is still running": drainer_running(board.env),
    }
    return [problem for problem, failed in checks.items() if failed]


@contextmanager
def checked_run(claude_allowed: tuple[str, ...]) -> Iterator[tuple[SmokeRun, Board]]:
    before = leftovers()
    assert before == CLEAN, f"leftovers before the run: {before}"
    state = real_state()
    default_before = default_sessions()
    run = smoke_run(claude_allowed)
    assert run.socket == SmokeTmux(SOCKET, Path(), {}).socket == "callboard-smoke"
    assert isolated(run)
    board = Board(run, executables())
    problems: list[str] = []
    try:
        with run:
            try:
                yield run, board
            finally:
                for name in run.launched:
                    with suppress(RuntimeError):
                        run.save_pane(name, "end")
    except BaseException as error:
        problems += attempt(
            "leftover check", lambda: closing_problems(run, board, state, default_before)
        )
        error.add_note(f"leftovers: {problems}")
        raise
    else:
        problems += attempt(
            "leftover check", lambda: closing_problems(run, board, state, default_before)
        )
    finally:
        record = {"before": before, "after": leftovers(), "problems": problems}
        run.layout.logs.mkdir(parents=True, exist_ok=True)
        (run.layout.logs / "leftovers.json").write_text(json.dumps(record, indent=2))
    assert problems == []


def test_two_agents_chat_mail_and_read_through_callboard() -> None:
    results: dict[str, Payload] = {}
    pong = token()
    with checked_run(allowed("cl", f'callboard dm pi "pong {pong}"')) as (run, board):
        try:
            assert board.raw("join", "driver", "--human").returncode == 0
            launch(run, board)
            joined = wait_for(lambda: all(board.routes().get(h) for h in ("cl", "pi")))
            assert joined, f"agents did not join: {board.routes()}"
            cells = Cells(board, pong)
            results = run_cells(
                {
                    "short-dm-inline-read": cells.short_dm_is_inline_and_read,
                    "doorbell-read": cells.long_dm_with_image_is_a_doorbell,
                    "reply-rings-other": cells.reply_rings_the_other_agent,
                    "group-mention-only": cells.group_mention_rings_only_the_mentioned,
                    "mail-waiting-inbox": cells.mail_waits_and_shows_in_inbox,
                }
            )
        finally:
            (run.layout.logs / "callboard-cells.json").write_text(json.dumps(results, indent=2))
        assert {name: cell.get("ok") for name, cell in results.items()} == dict.fromkeys(
            results, True
        )
        assert len(results) == 5


def scribe_block(run: SmokeRun, board: Board) -> str:
    block = tomllib.loads(run.agent_block("claude", "scribe"))["agents"]["scribe"]
    keys = ("HOME", "CLAUDE_CONFIG_DIR", "TMPDIR", "BELLHOP_RUNTIME_DIR", "PATH")
    xdg = tuple(key for key in board.env if key.startswith("XDG_"))
    env = block["env"] | {key: board.env[key] for key in (*keys, *xdg)}
    table = ", ".join(f"{key} = {json.dumps(value)}" for key, value in env.items())
    fields = [f"{key} = {json.dumps(block[key])}" for key in ("harness", "cwd", "command")]
    return "\n".join(["[agents.scribe]", *fields, f"env = {{ {table} }}"]) + "\n"


def pane_processes(run: SmokeRun, name: str) -> set[tuple[int, str, str]]:
    procs = ps()
    owned = descendants(procs, {run.launched[name].pane_pid})
    return {proc.identity for proc in procs if proc.pid in owned}


def binding(board: Board, name: str) -> Payload:
    _, payload = board.bellhop("agents")
    rows = [row for row in payload.get("agents", []) if row.get("agent") == name]
    found = rows[0].get("binding") if rows else None
    return found if isinstance(found, dict) else {}


def bellhop_message(board: Board, bellhop_id: str) -> Payload:
    _, payload = board.bellhop("status", bellhop_id)
    rows = payload.get("messages", [])
    return rows[0] if rows else {}


def text_of(record: Payload) -> str:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    parts = content if isinstance(content, list) else []
    return " ".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))


def records(path: Path) -> list[Payload]:
    found: list[Payload] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        with suppress(json.JSONDecodeError):
            record = json.loads(line)
            found += [record] if isinstance(record, dict) else []
    return found


def said(run: SmokeRun, session_id: object, kind: str, *parts: str) -> bool:
    paths = sorted((run.layout.claude_dir / "projects").rglob(f"{session_id}.jsonl"))
    return any(
        record.get("type") == kind and all(part in text_of(record) for part in parts)
        for path in paths
        for record in records(path)
    )


def test_urgent_mail_to_a_stopped_agent_starts_it() -> None:
    result: Payload = {}
    with checked_run(allowed("scribe")) as (run, board):
        try:
            config = run.write_bellhop_config(scribe_block(run, board))
            written = tomllib.loads(config.read_text())
            scribe = written["agents"]["scribe"]
            assert written["tmux_socket"] == SOCKET
            homes = ("HOME", "CLAUDE_CONFIG_DIR", "TMPDIR", "BELLHOP_RUNTIME_DIR")
            assert {key: scribe["env"][key] for key in homes} == {
                key: run.env[key] for key in homes
            }
            assert scribe["env"]["BELLHOP_RUNTIME_DIR"] == str(run.layout.runtime_dir)
            assert scribe["env"]["PATH"] == board.env["PATH"]
            assert all(
                scribe["env"][key] == run.env[key] for key in run.env if key.startswith("XDG_")
            )
            default_before = default_sessions()
            assert board.raw("join", "driver", "--human").returncode == 0
            launched, started = board.bellhop(
                "launch", "scribe", "--prompt", JOIN.format(handle="scribe"), "--from", "driver"
            )
            result["launch"] = {"exit": launched, "agent": started.get("agent")}
            assert launched == 0
            run.adopt_session("scribe")
            assert "scribe" in run.tmux.sessions()
            assert wait_for(lambda: board.routes().get("scribe") == "scribe")
            first = binding(board, "scribe")
            assert (first.get("state"), first.get("cause")) == ("live", "launch")
            stopped = pane_processes(run, "scribe")
            run.tmux.run("kill-session", "-t", "=scribe")
            assert wait_for(lambda: stopped.isdisjoint(p.identity for p in ps()), 30, 0.5)
            assert strays(default_before) == []
            tok = token()
            code, payload = board.call(
                "mail",
                "send",
                "--to",
                "scribe",
                "--subject",
                f"wake {tok}",
                "--urgent",
                f"Reply with exactly ACK {tok}.",
            )
            sent = payload["message"]
            receipt = sent["receipts"][0]
            result["mail"] = {"exit": code, "receipt": receipt, "warnings": payload["warnings"]}
            assert code == 0
            run.adopt_session("scribe")
            assert payload["warnings"] == []
            assert (receipt["ping"], receipt["ping_state"]) == ("idle", "pending")
            assert "scribe" in run.tmux.sessions()
            final = board.settled(sent["id"], "scribe", read_and_confirmed)
            woke = binding(board, "scribe")
            message = bellhop_message(board, receipt["bellhop_id"])
            envelope = f"[bellhop {receipt['bellhop_id']} from driver] callboard {sent['id']} mail"
            asked = (envelope, f"Reply with exactly ACK {tok}")
            landed = said(run, woke.get("session_id"), "user", *asked)
            answered = wait_for(
                lambda: said(run, woke.get("session_id"), "assistant", f"ACK {tok}"), 60, 2
            )
            result |= {"first": first, "woke": woke, "final": final, "bellhop": message}
            result |= {"landed": landed, "answered": bool(answered)}
            assert read_and_confirmed(final)
            assert (message.get("route"), message.get("detail"), message.get("state")) == (
                "launch",
                "started with this prompt",
                "confirmed",
            )
            assert (woke.get("state"), woke.get("cause")) == ("live", "send --wake from driver")
            assert woke.get("session_id") != first.get("session_id")
            assert landed
            assert answered
            assert strays(default_before) == []
        finally:
            (run.layout.logs / "launch-cell.json").write_text(json.dumps(result, indent=2))
