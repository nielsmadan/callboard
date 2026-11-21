import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release.py"
SPEC = importlib.util.spec_from_file_location("release_script", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)

NAME = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["name"]
RECIPE = re.compile(r"^([a-z][a-z0-9-]*)(?:\s+[^:=]*)?:(?!=)", re.MULTILINE)


def run(*arguments: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, str(SCRIPT), *map(str, arguments)),
        capture_output=True,
        text=True,
        check=False,
    )


def formula(version: str) -> str:
    rendered: str = release.rendered(release.FORMULA_TEMPLATE.read_text(), version, "a" * 64)
    return rendered


@pytest.mark.parametrize("version", ["0.1.0", "2.10.3"])
def test_a_new_version_replaces_only_the_project_version(version: str) -> None:
    source = '[project]\nname = "example"\nversion = "0.0.1" # kept\n\n[tool.x]\nother = "0.0.1"\n'

    assert release.with_version(source, version) == source.replace(
        'version = "0.0.1"', f'version = "{version}"'
    )


@pytest.mark.parametrize("version", ["01.0.0", "v1.0.0", "1.0", "1.0.0rc1", "1.0.0\n"])
def test_a_version_that_is_not_canonical_is_refused(version: str) -> None:
    with pytest.raises(release.ReleaseError, match="canonical"):
        release.with_version('[project]\nversion = "0.1.0"\n', version)


def test_a_manifest_with_a_second_version_line_is_refused() -> None:
    source = '[project]\nversion = "0.1.0"\n\n[tool.x]\nversion = "9"\n'

    with pytest.raises(release.ReleaseError, match="exactly one manifest version"):
        release.with_version(source, "0.2.0")


def test_this_projects_manifest_accepts_a_new_version() -> None:
    updated = release.with_version((ROOT / "pyproject.toml").read_text(), "9.8.7")

    assert tomllib.loads(updated)["project"]["version"] == "9.8.7"


@pytest.mark.parametrize(
    ("manifest", "tag", "expected"),
    [
        ('[project]\nversion = "1.2.3"\n', "v1.2.3", "version=1.2.3\n"),
        ('[project]\nversion = "1.2.4"\n', "v1.2.3", "does not match project version '1.2.4'"),
        ('[project]\nversion = "1.2.3"\n', "1.2.3", "does not start with v"),
        ('[project]\nversion = "1.2"\n', "v1.2", "canonical"),
        ("[tool]\n", "v1.2.3", "no [project] table"),
        ("[", "v1.2.3", "release: "),
    ],
)
def test_project_metadata_prints_the_version_only_for_a_matching_tag(
    tmp_path: Path, manifest: str, tag: str, expected: str
) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text(manifest)

    result = run("project-metadata", tag, path)

    assert result.returncode == (0 if expected.startswith("version=") else 1)
    assert expected in result.stdout + result.stderr


def test_the_formula_names_the_tagged_archive_and_its_digest(tmp_path: Path) -> None:
    archive = tmp_path / "source.tar.gz"
    archive.write_bytes(b"release source")
    output = tmp_path / "formula.rb"

    result = run("formula", "v9.8.7", archive, output)

    assert result.returncode == 0, result.stderr
    rendered = output.read_text()
    url = f"https://github.com/nielsmadan/{NAME}/archive/refs/tags/v9.8.7.tar.gz"
    assert f'\n  url "{url}"\n' in rendered
    assert f'\n  sha256 "{hashlib.sha256(b"release source").hexdigest()}"\n' in rendered
    assert rendered.startswith(f"class {NAME.capitalize()} < Formula\n")
    assert release.formula_version(rendered) == (9, 8, 7)


def test_a_formula_for_a_malformed_tag_is_not_written(tmp_path: Path) -> None:
    archive = tmp_path / "source.tar.gz"
    archive.write_bytes(b"release source")
    output = tmp_path / "formula.rb"

    result = run("formula", "v9.8", archive, output)

    assert result.returncode == 1
    assert "canonical" in result.stderr
    assert not output.exists()


def test_a_formula_is_published_into_an_empty_tap(tmp_path: Path) -> None:
    source = tmp_path / "formula.rb"
    source.write_text(formula("1.2.3"))
    target = tmp_path / "tap" / "Formula" / f"{NAME}.rb"

    result = run("publish-formula", source, target)

    assert result.stdout == "updated\n"
    assert target.read_text() == formula("1.2.3")


def test_a_formula_replaces_an_older_published_one(tmp_path: Path) -> None:
    source = tmp_path / "formula.rb"
    source.write_text(formula("1.10.0"))
    target = tmp_path / f"{NAME}.rb"
    target.write_text(formula("1.9.0"))

    result = run("publish-formula", source, target)

    assert result.stdout == "updated\n"
    assert target.read_text() == formula("1.10.0")


def test_a_newer_published_formula_is_kept(tmp_path: Path) -> None:
    source = tmp_path / "formula.rb"
    source.write_text(formula("1.9.0"))
    target = tmp_path / f"{NAME}.rb"
    target.write_text(formula("1.10.0"))

    result = run("publish-formula", source, target)

    assert result.stdout == "skipped-newer\n"
    assert target.read_text() == formula("1.10.0")


def test_a_published_file_that_is_not_a_formula_stops_the_publish(tmp_path: Path) -> None:
    source = tmp_path / "formula.rb"
    source.write_text(formula("1.9.0"))
    target = tmp_path / f"{NAME}.rb"
    target.write_text("class Other < Formula\nend\n")

    result = run("publish-formula", source, target)

    assert result.returncode == 1
    assert "does not name exactly one release archive" in result.stderr
    assert target.read_text() == "class Other < Formula\nend\n"


def test_the_release_policy_runs_recipes_the_justfile_defines() -> None:
    policy = json.loads((ROOT / "scripts" / "release.json").read_text())
    stage_commands = [
        command for stage in policy["stages"] for command in stage["commands"] + stage["checks"]
    ]
    named = {command[1] for command in policy["checks"] + stage_commands if command[0] == "just"}

    assert named
    assert named <= set(RECIPE.findall((ROOT / "Justfile").read_text()))


def test_the_release_policy_names_this_project() -> None:
    policy = json.loads((ROOT / "scripts" / "release.json").read_text())

    assert policy["repository"] == f"nielsmadan/{NAME}"
    assert (ROOT / ".github" / "workflows" / policy["workflow"]).is_file()
