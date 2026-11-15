from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

type ParticipantKind = Literal["agent", "human"]
type ConversationKind = Literal["dm", "group", "mail", "topic"]
type MemberRole = Literal["member", "from", "to", "cc", "subscriber"]
type Ping = Literal["none", "hold", "idle", "now"]
type PingState = Literal["pending", "sending", "sent", "confirmed", "read", "failed"]


@dataclass(frozen=True)
class Runtime:
    env: Mapping[str, str] = field(repr=False)
    clock: Callable[[], str]
    token: Callable[[], str]
    stdin: Callable[[], str]
    deadline: float = 20.0


@dataclass(frozen=True)
class Participant:
    handle: str
    kind: ParticipantKind
    route: str | None
    created_at: str


@dataclass(frozen=True)
class JoinOutcome:
    current: Participant
    previous: Participant | None
    displaced: tuple[str, ...]


@dataclass(frozen=True)
class BellhopSession:
    session_id: str
    agent: str | None


@dataclass(frozen=True)
class Conversation:
    id: str
    kind: ConversationKind
    name: str | None
    subject: str | None
    project: str | None
    created_by: str
    created_at: str


@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    sender: str
    body: str
    parent_id: str | None
    created_at: str


@dataclass(frozen=True)
class Receipt:
    message_id: str
    recipient: str
    ping: Ping
    ping_state: PingState | None
    bellhop_id: str | None
    inline: bool
    read_at: str | None


@dataclass(frozen=True)
class InboxEntry:
    conversation: Conversation
    unread: int
    mentions: int
    sender: str


@dataclass(frozen=True)
class Attachment:
    id: str
    sha256: str
    filename: str
    media_type: str
    size: int


@dataclass(frozen=True)
class BellhopMessage:
    id: str
    state: PingState
    urgency: str | None
    detail: str | None
