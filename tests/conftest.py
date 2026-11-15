import os
from pathlib import Path

import pytest


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
