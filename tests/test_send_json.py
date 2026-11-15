from pathlib import Path

import pytest

from helpers import Callboard, load_golden, seed

pytestmark = pytest.mark.usefixtures("ringing")


@pytest.fixture
def outputs(cb: Callboard, tmp_path: Path) -> dict[str, dict[str, object]]:
    seed(("enki", "enki"), ("nanna", "sess-nanna"), ("niels", None))
    note = tmp_path / "notes.txt"
    note.write_text("hello\n")
    steps = {
        "send-dm": ("--as", "enki", "dm", "nanna", "see notes", "--attach", str(note), "--json"),
        "create": ("--as", "enki", "group", "create", "ops", "--members", "nanna,niels"),
        "send-group": ("--as", "niels", "group", "send", "ops", "@nanna ok", "--now", "--json"),
        "send-mail": (
            "--as",
            "enki",
            "mail",
            "send",
            "--to",
            "nanna",
            "--cc",
            "niels",
            "--subject",
            "Plan",
            "body",
            "--json",
        ),
        "send-mail-reply": (
            "--as",
            "nanna",
            "mail",
            "reply",
            "cb_000000000004",
            "ack",
            "--urgent",
            "--json",
        ),
    }
    results = {name: cb(*argv) for name, argv in steps.items()}
    assert {name: (result.code, result.err) for name, result in results.items()} == dict.fromkeys(
        steps, (0, "")
    )
    return {name: results[name].json() for name in steps if name != "create"}


@pytest.mark.parametrize("name", ["send-dm", "send-group", "send-mail", "send-mail-reply"])
def test_send_json_matches_the_golden(outputs: dict[str, dict[str, object]], name: str) -> None:
    assert outputs[name] == load_golden(f"{name}.json")


def test_send_text_stays_one_line(cb: Callboard) -> None:
    seed(("enki", "enki"), ("nanna", "sess-nanna"))
    assert cb("--as", "enki", "dm", "nanna", "hi") == (0, "sent cb_000000000001 to @nanna\n", "")
