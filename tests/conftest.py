import itertools
import os
import sys
from pathlib import Path

import pytest

from callboard.cli.dispatch import run
from callboard.models import Runtime
from helpers import CLOCK, FAKES, Callboard, FakeBellhop, Result


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", os.defpath)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data-home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state-home"))
    for name in [name for name in os.environ if name.startswith(("CALLBOARD_", "FAKE_BELLHOP_"))]:
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def bellhop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeBellhop:
    python_dir = Path(sys.executable).parent
    monkeypatch.setenv("PATH", os.pathsep.join([str(FAKES), str(python_dir), os.defpath]))
    log = tmp_path / "bellhop-calls.jsonl"
    monkeypatch.setenv("FAKE_BELLHOP_LOG", str(log))
    return FakeBellhop(monkeypatch, log)


@pytest.fixture
def cb(capsys: pytest.CaptureFixture[str]) -> Callboard:
    counter = itertools.count(1)

    def call(*argv: str, stdin: str = "", deadline: float = 20.0) -> Result:
        runtime = Runtime(
            os.environ, lambda: CLOCK, lambda: f"{next(counter):012x}", lambda: stdin, deadline
        )
        code = run(list(argv), runtime)
        out, err = capsys.readouterr()
        return Result(code, out, err)

    return call


@pytest.fixture
def ringing(bellhop: FakeBellhop) -> FakeBellhop:
    bellhop.replay("send", "send-pending.json")
    bellhop.replay("status", "status-pending.json")
    return bellhop
