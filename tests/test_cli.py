import io
import json
import os
import re
import subprocess
import sys

import pytest

from callboard import __version__
from callboard.cli import main, random_token, read_stdin, utc_now


def test_version_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out == f"callboard {__version__}\n"


def test_missing_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert capsys.readouterr().err == "callboard: missing command; see callboard --help\n"


def test_unknown_option_in_json_mode_prints_the_error_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--bogus", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "schema_version": 1,
        "status": "error",
        "exit_code": 2,
        "error": {"code": "usage", "message": "unrecognized arguments: --bogus --json"},
    }


def test_module_entry_point_runs_the_cli() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "callboard", "--version"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ},
    )
    assert (result.returncode, result.stdout) == (0, f"callboard {__version__}\n")


def test_interrupt_exits_130_and_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupted(*_args: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr("callboard.cli.run", interrupted)
    assert main(["who"]) == 130
    assert capsys.readouterr() == ("", "callboard: interrupted\n")
    assert main(["who", "--json"]) == 130
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "status": "error",
        "exit_code": 130,
        "error": {"code": "interrupted", "message": "interrupted"},
    }


def test_a_closed_stdout_exits_quietly() -> None:
    script = (
        "import sys, callboard.cli as cli\n"
        "def broken(*_args):\n"
        "    raise BrokenPipeError\n"
        "cli.run = broken\n"
        "sys.exit(cli.main(['who']))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert (result.returncode, result.stdout, result.stderr) == (1, "", "")


def test_utc_now_is_iso_8601_utc_to_the_second() -> None:
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", utc_now())


def test_random_tokens_are_12_hex_characters() -> None:
    assert re.fullmatch(r"[0-9a-f]{12}", random_token())


def test_stdin_is_read_unless_it_is_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    piped = io.StringIO("piped text\n")
    monkeypatch.setattr(sys, "stdin", piped)
    assert read_stdin() == "piped text\n"
    terminal = io.StringIO("typed")
    monkeypatch.setattr(terminal, "isatty", lambda: True)
    monkeypatch.setattr(sys, "stdin", terminal)
    assert read_stdin() == ""


def test_an_unexpected_failure_still_prints_one_envelope(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(*_args: object) -> int:
        raise OverflowError("int too large")

    monkeypatch.setattr("callboard.cli.run", broken)
    assert main(["history", "@x", "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "status": "error",
        "exit_code": 1,
        "error": {
            "code": "internal_error",
            "message": "internal error: OverflowError: int too large",
        },
    }
    assert main(["history", "@x"]) == 1
    assert capsys.readouterr() == ("", "callboard: internal error: OverflowError: int too large\n")
