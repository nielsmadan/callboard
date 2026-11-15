import json
import os
import subprocess
import sys

import pytest

from callboard import __version__
from callboard.cli import main


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
