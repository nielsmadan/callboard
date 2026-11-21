import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "app" / "scripts" / "demo.py"
TOOLS = [shutil.which("just"), shutil.which("uv")]


def run_demo(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": os.defpath}
    return subprocess.run(
        [
            sys.executable,
            str(DEMO),
            "--callboard",
            f"{shlex.quote(sys.executable)} -m callboard",
            "--target",
            str(target),
            *args,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def admin_conversations(target: Path) -> list[dict[str, object]]:
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("CALLBOARD_")},
        "HOME": str(target),
        "XDG_DATA_HOME": str(target / "data"),
        "XDG_CONFIG_HOME": str(target / "config"),
        "XDG_STATE_HOME": str(target / "state"),
    }
    done = subprocess.run(
        [sys.executable, "-m", "callboard", "admin", "conversations", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    conversations: list[dict[str, object]] = json.loads(done.stdout)["conversations"]
    return conversations


def test_small_demo_seeds_its_conversations_and_messages(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    done = run_demo(target, "--small")
    assert done.returncode == 0, done.stderr
    conversations = admin_conversations(target)
    kinds = sorted(str(conversation["id"]).split(":")[0] for conversation in conversations)
    assert kinds == ["dm", "group", "group"]
    assert sum(int(str(conversation["messages"])) for conversation in conversations) == 6
    assert f"Store folder: {target / 'data'}" in done.stdout


def test_full_demo_seeds_the_reply_attachment_and_markdown(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    done = run_demo(target)
    assert done.returncode == 0, done.stderr
    conversations = admin_conversations(target)
    kinds = sorted(str(conversation["id"]).split(":")[0] for conversation in conversations)
    assert kinds == ["dm"] * 4 + ["group"] * 3
    assert sum(int(str(conversation["messages"])) for conversation in conversations) == 63
    assert f"callboard path: {shlex.quote(sys.executable)} -m callboard" in done.stdout


def test_demo_wipes_a_previous_demo_store(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    assert run_demo(target, "--small").returncode == 0
    assert run_demo(target, "--small").returncode == 0
    assert sum(int(str(c["messages"])) for c in admin_conversations(target)) == 6


def test_demo_refuses_to_wipe_a_folder_it_did_not_create(tmp_path: Path) -> None:
    target = tmp_path / "other-work"
    target.mkdir()
    (target / "keep.txt").write_text("mine", encoding="utf-8")
    done = run_demo(target, "--small")
    assert done.returncode != 0
    assert "not a demo store" in done.stderr
    assert (target / "keep.txt").read_text(encoding="utf-8") == "mine"


def test_demo_refuses_a_target_that_climbs_out_of_the_build_dir() -> None:
    done = run_demo(ROOT / "app" / "build" / ".." / "demo-escape", "--small")
    assert done.returncode != 0
    assert "refusing target" in done.stderr
    assert not (ROOT / "app" / "demo-escape").exists()


def test_demo_refuses_a_target_outside_the_build_and_temp_dirs() -> None:
    done = run_demo(ROOT / "docs" / "demo-never-created", "--small")
    assert done.returncode != 0
    assert "refusing target" in done.stderr
    assert not (ROOT / "docs" / "demo-never-created").exists()


def test_demo_refuses_a_target_that_is_a_file(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("mine", encoding="utf-8")
    done = run_demo(target, "--small")
    assert done.returncode == 1
    assert done.stderr == f"demo: refusing to wipe {target.resolve()}; it is not a demo store\n"
    assert target.read_text(encoding="utf-8") == "mine"


def test_demo_reports_a_callboard_command_it_cannot_run(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-callboard"
    done = run_demo(tmp_path / "demo", "--small", "--callboard", str(missing))
    assert done.returncode == 1
    assert done.stderr.startswith(f"demo: cannot run {missing} join niels --human --json: ")


@pytest.mark.skipif(None in TOOLS, reason="needs just and uv")
def test_just_app_demo_keeps_a_quoted_callboard_command_whole(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    command = f"{shlex.quote(sys.executable)} -m callboard"
    tools = [str(Path(str(tool)).parent) for tool in TOOLS]
    done = subprocess.run(
        ["just", "app", "demo", "--small", "--target", str(target), "--callboard", command],
        cwd=ROOT,
        env={**os.environ, "PATH": os.pathsep.join([*tools, os.defpath])},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert f"Settings -> callboard path: {command}" in done.stdout
    assert len(admin_conversations(target)) == 3


def test_demo_rejects_an_unreadable_callboard_command_before_wiping(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    assert run_demo(target, "--small").returncode == 0
    done = run_demo(target, "--small", "--callboard", "'unclosed")
    assert done.returncode == 1
    assert done.stderr == "demo: cannot read --callboard 'unclosed: No closing quotation\n"
    assert sum(int(str(c["messages"])) for c in admin_conversations(target)) == 6


def test_demo_reports_the_error_a_failing_callboard_prints_on_stdout(tmp_path: Path) -> None:
    script = tmp_path / "failing"
    script.write_text('#!/bin/sh\necho \'{"error": "boom"}\'\nexit 1\n', encoding="utf-8")
    script.chmod(0o755)
    done = run_demo(tmp_path / "demo", "--small", "--callboard", str(script))
    assert done.returncode == 1
    assert done.stderr.endswith(' failed: {"error": "boom"}\n')


def test_demo_reports_a_callboard_that_prints_no_json(tmp_path: Path) -> None:
    done = run_demo(tmp_path / "demo", "--small", "--callboard", "true")
    assert done.returncode == 1
    assert done.stderr.startswith("demo: true join niels --human --json printed no JSON: ")
