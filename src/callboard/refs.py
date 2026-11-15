import re
from dataclasses import dataclass

from callboard.errors import CallboardError

MESSAGE_ID = re.compile(r"cb_[0-9a-f]{12}")
NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")


@dataclass(frozen=True)
class ConversationRef:
    conversation_id: str


@dataclass(frozen=True)
class MessageRef:
    message_id: str


type Ref = ConversationRef | MessageRef


def dm_id(one: str, other: str) -> str:
    first, second = sorted((one, other))
    return f"dm:{first}:{second}"


def ref_of(conversation_id: str, caller: str) -> str:
    handles = conversation_id.split(":")[1:]
    if not conversation_id.startswith("dm:") or caller not in handles:
        return conversation_id
    others = [handle for handle in handles if handle != caller]
    return f"@{others[0] if others else caller}"


def parse_ref(text: str, caller: str) -> Ref:
    if text.startswith("@") and NAME.fullmatch(text[1:]):
        return ConversationRef(dm_id(caller, text[1:]))
    kind, _, value = text.partition(":")
    if kind in {"group", "mail"} and NAME.fullmatch(value):
        return ConversationRef(text)
    if MESSAGE_ID.fullmatch(text):
        return MessageRef(text)
    raise CallboardError(
        f"unknown ref '{text}'; use @handle, group:<name>, mail:<id> or a message id cb_…",
        code="usage",
    )
