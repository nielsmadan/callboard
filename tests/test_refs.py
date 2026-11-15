import pytest

from callboard.errors import CallboardError
from callboard.refs import ConversationRef, MessageRef, Ref, dm_id, parse_ref, ref_of


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("@nanna", ConversationRef("dm:enki:nanna")),
        ("@anu", ConversationRef("dm:anu:enki")),
        ("group:ops", ConversationRef("group:ops")),
        ("mail:3fa9c1d2e4b5", ConversationRef("mail:3fa9c1d2e4b5")),
        ("cb_19ab4c7d2e10", MessageRef("cb_19ab4c7d2e10")),
    ],
)
def test_every_ref_form_parses(text: str, expected: Ref) -> None:
    assert parse_ref(text, "enki") == expected


@pytest.mark.parametrize(
    "text",
    ["nanna", "@", "@Nanna", "group:", "group:Ops", "topic:x", "cb_19AB4C7D2E10", "cb_123", ""],
)
def test_an_unknown_ref_is_a_usage_error(text: str) -> None:
    with pytest.raises(CallboardError) as caught:
        parse_ref(text, "enki")
    assert (caught.value.code, caught.value.exit_code, str(caught.value)) == (
        "usage",
        2,
        f"unknown ref '{text}'; use @handle, group:<name>, mail:<id> or a message id cb_…",
    )


def test_dm_ids_sort_the_handles() -> None:
    assert dm_id("nanna", "enki") == dm_id("enki", "nanna") == "dm:enki:nanna"


def test_ref_of_names_the_other_party_of_a_dm() -> None:
    assert ref_of("dm:enki:nanna", "enki") == "@nanna"
    assert ref_of("dm:enki:nanna", "nanna") == "@enki"
    assert ref_of("group:ops", "enki") == "group:ops"
    assert ref_of("dm:enki:nanna", "niels") == "dm:enki:nanna"
