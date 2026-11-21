from pathlib import Path

import pytest

from helpers import GOLDEN

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "app" / "CallboardKit" / "Tests" / "CallboardKitTests" / "Fixtures"
NAMES = [
    "admin-conversations.json",
    "admin-history.json",
    "admin-watch-snapshot.json",
    "admin-watch-messages.json",
]


@pytest.mark.parametrize("name", NAMES)
def test_swift_fixture_is_the_golden(name: str) -> None:
    assert (FIXTURES / name).read_bytes() == (GOLDEN / name).read_bytes()
