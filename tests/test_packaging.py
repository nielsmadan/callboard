import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENVIRONMENT = dict(os.environ)
SKILL = (ROOT / "skills" / "callboard" / "SKILL.md").read_bytes()

pytestmark = pytest.mark.packaging


@pytest.fixture(scope="module")
def dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("dist")
    uv = shutil.which("uv", path=ENVIRONMENT.get("PATH"))
    assert uv is not None
    built = subprocess.run(
        [uv, "build", "--out-dir", str(out), str(ROOT)],
        env=ENVIRONMENT,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert built.returncode == 0, built.stderr
    return out


def test_the_wheel_bundles_the_skill(dist: Path) -> None:
    (wheel,) = dist.glob("callboard-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        assert archive.read("callboard/_skills/callboard/SKILL.md") == SKILL
        assert "callboard/cli/__init__.py" in archive.namelist()


def test_the_sdist_carries_the_skill_and_the_docs(dist: Path) -> None:
    (sdist,) = dist.glob("callboard-*.tar.gz")
    with tarfile.open(sdist) as archive:
        names = {name.split("/", 1)[1] for name in archive.getnames() if "/" in name}
    assert {"skills/callboard/SKILL.md", "docs/user/getting-started.md", "README.md"} <= names
