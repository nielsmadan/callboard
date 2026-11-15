import pytest

from helpers import Callboard, rows, seed

pytestmark = pytest.mark.usefixtures("ringing")

THREAD = "mail:000000000002"


@pytest.fixture(autouse=True)
def people() -> None:
    seed(("enki", "enki"), ("nanna", "sess-nanna"), ("utu", "utu"), ("niels", None))


def _send(cb: Callboard, *extra: str) -> None:
    result = cb(
        "--as",
        "enki",
        "mail",
        "send",
        "--to",
        "nanna,niels",
        "--cc",
        "utu",
        "--subject",
        "Release plan",
        "draft attached",
        *extra,
    )
    assert result == (0, f"sent cb_000000000001 to {THREAD}\n", "")


def _receipts(message_id: str) -> list[tuple[str, str, str | None]]:
    return rows(
        "SELECT recipient, ping, ping_state FROM receipts WHERE message_id = ? ORDER BY recipient",
        message_id,
    )


def test_send_creates_a_thread_with_from_to_and_cc(cb: Callboard) -> None:
    _send(cb)
    assert rows("SELECT id, kind, subject, created_by FROM conversations") == [
        (THREAD, "mail", "Release plan", "enki")
    ]
    assert rows("SELECT handle, role FROM members ORDER BY handle") == [
        ("enki", "from"),
        ("nanna", "to"),
        ("niels", "to"),
        ("utu", "cc"),
    ]
    assert _receipts("cb_000000000001") == [
        ("nanna", "hold", "pending"),
        ("niels", "none", None),
        ("utu", "hold", "pending"),
    ]


def test_urgent_mail_rings_at_idle(cb: Callboard) -> None:
    _send(cb, "--urgent")
    assert _receipts("cb_000000000001") == [
        ("nanna", "idle", "pending"),
        ("niels", "none", None),
        ("utu", "idle", "pending"),
    ]


def test_a_reply_reaches_everyone_in_the_thread_but_the_replier(cb: Callboard) -> None:
    _send(cb)
    reply = cb("--as", "utu", "mail", "reply", "cb_000000000001", "looks good", "--urgent")
    assert reply == (0, f"sent cb_000000000003 to {THREAD}\n", "")
    assert rows("SELECT conversation_id, sender, parent_id FROM messages WHERE seq = 2") == [
        (THREAD, "utu", "cb_000000000001")
    ]
    assert _receipts("cb_000000000003") == [
        ("enki", "idle", "pending"),
        ("nanna", "idle", "pending"),
        ("niels", "none", None),
    ]


def test_a_reply_to_a_reply_stays_in_the_thread(cb: Callboard) -> None:
    _send(cb)
    assert cb("--as", "utu", "mail", "reply", "cb_000000000001", "one").code == 0
    assert cb("--as", "enki", "mail", "reply", "cb_000000000003", stdin="two\n").code == 0
    assert rows("SELECT body, parent_id FROM messages WHERE seq = 3") == [
        ("two", "cb_000000000003")
    ]
    assert rows("SELECT count(*) FROM conversations") == [(1,)]


def test_reply_refusals(cb: Callboard) -> None:
    _send(cb)
    assert cb("--as", "enki", "dm", "nanna", "chat").code == 0
    assert cb("--as", "nanna", "mail", "reply", "cb_000000000003", "x") == (
        2,
        "",
        "callboard: cb_000000000003 is not mail; reply with dm or group send\n",
    )
    assert cb("--as", "utu", "mail", "reply", "cb_0000000000ff", "x") == (
        3,
        "",
        "callboard: no message cb_0000000000ff\n",
    )
    seed(("anu", "anu"))
    assert cb("--as", "anu", "mail", "reply", "cb_000000000001", "x") == (
        3,
        "",
        f"callboard: 'anu' is not a member of {THREAD}\n",
    )


def test_subject_is_required(cb: Callboard) -> None:
    assert cb("--as", "enki", "mail", "send", "--to", "nanna", "hi").code == 2
    assert cb("--as", "enki", "mail", "send", "--to", "nanna", "--subject", " ", "hi") == (
        2,
        "",
        "callboard: --subject must not be empty\n",
    )
    assert rows("SELECT count(*) FROM conversations") == [(0,)]


def test_an_unknown_recipient_is_named_and_nothing_is_stored(cb: Callboard) -> None:
    result = cb(
        "--as", "enki", "mail", "send", "--to", "nanna", "--cc", "ghost", "--subject", "s", "x"
    )
    assert result == (3, "", "callboard: no participant 'ghost'\n")
    assert rows("SELECT count(*) FROM conversations") == [(0,)]


def test_mailing_only_yourself_is_a_usage_error(cb: Callboard) -> None:
    result = cb("--as", "enki", "mail", "send", "--to", "enki", "--subject", "s", "x")
    assert result == (2, "", "callboard: mail needs a recipient other than you\n")


def test_to_wins_over_cc_for_the_same_handle(cb: Callboard) -> None:
    assert (
        cb(
            "--as",
            "enki",
            "mail",
            "send",
            "--to",
            "nanna",
            "--cc",
            "nanna,utu",
            "--subject",
            "s",
            "x",
        ).code
        == 0
    )
    assert rows("SELECT handle, role FROM members WHERE role != 'from' ORDER BY handle") == [
        ("nanna", "to"),
        ("utu", "cc"),
    ]


def test_mail_shows_in_inbox_under_its_own_heading_and_reads(cb: Callboard) -> None:
    _send(cb)
    assert cb("--as", "enki", "dm", "nanna", "ping").code == 0
    assert cb("--as", "nanna", "inbox") == (
        0,
        f"@enki  1 unread\n\nmail:\n  {THREAD}  1 unread  from enki: Release plan\n",
        "",
    )
    entry = cb("--as", "nanna", "inbox", "--json").json()["conversations"][1]
    assert (entry["ref"], entry["kind"], entry["subject"], entry["sender"]) == (
        THREAD,
        "mail",
        "Release plan",
        "enki",
    )
    assert cb("--as", "nanna", "read", THREAD).out == (
        "cb_000000000001  2026-11-14T09:00:00Z  enki: draft attached\n"
    )
    assert cb("--as", "nanna", "inbox").out == "@enki  1 unread\n"


def test_repeated_to_and_cc_add_up(cb: Callboard) -> None:
    result = cb(
        "--as",
        "enki",
        "mail",
        "send",
        "--to",
        "nanna",
        "--to",
        "niels",
        "--cc",
        "utu",
        "--cc",
        "anu",
        "--subject",
        "s",
        "x",
    )
    assert result == (3, "", "callboard: no participant 'anu'\n")
    seed(("anu", None))
    assert (
        cb(
            "--as",
            "enki",
            "mail",
            "send",
            "--to",
            "nanna",
            "--to",
            "niels",
            "--cc",
            "utu",
            "--cc",
            "anu",
            "--subject",
            "s",
            "x",
        ).code
        == 0
    )
    assert rows("SELECT handle, role FROM members WHERE role != 'from' ORDER BY handle") == [
        ("anu", "cc"),
        ("nanna", "to"),
        ("niels", "to"),
        ("utu", "cc"),
    ]


def test_control_characters_in_subjects_cannot_forge_inbox_lines(cb: Callboard) -> None:
    subject = "Plan\nmail:fake  9 unread"
    assert cb("--as", "enki", "mail", "send", "--to", "nanna", "--subject", subject, "x").code == 0
    assert cb("--as", "nanna", "inbox").out == (
        "mail:\n  mail:000000000002  1 unread  from enki: Plan\\nmail:fake  9 unread\n"
    )
