from pathlib import Path

import pytest

from callboard.errors import CallboardError
from callboard.paths import data_dir, store_path


def test_data_dir_is_under_xdg_data_home() -> None:
    assert data_dir({"XDG_DATA_HOME": "/x/data"}) == Path("/x/data/callboard")


def test_data_dir_defaults_under_home_when_xdg_is_unset_or_empty() -> None:
    expected = Path("/h/.local/share/callboard")
    assert data_dir({"HOME": "/h"}) == expected
    assert data_dir({"HOME": "/h", "XDG_DATA_HOME": ""}) == expected


def test_relative_xdg_data_home_is_refused() -> None:
    with pytest.raises(CallboardError) as caught:
        data_dir({"XDG_DATA_HOME": "rel/data"})
    assert (caught.value.code, caught.value.exit_code, str(caught.value)) == (
        "invalid_environment",
        1,
        "XDG_DATA_HOME must be an absolute path; got 'rel/data'",
    )


def test_store_lives_in_the_data_dir() -> None:
    assert store_path({"XDG_DATA_HOME": "/x"}) == Path("/x/callboard/callboard.sqlite")
