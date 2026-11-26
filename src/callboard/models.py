from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

ADMIN_BODY_LIMIT = 65_536

type ParticipantKind = Literal["agent", "human"]
type ConversationKind = Literal["dm", "group", "mail", "topic"]
type MemberRole = Literal["member", "from", "to", "cc", "subscriber"]
type Ping = Literal["none", "hold", "idle", "now"]
type PingState = Literal["pending", "sending", "sent", "confirmed", "read", "failed"]


class Emit(Protocol):
    def __call__(self, event: str, /, **fields: object) -> None: ...


def quiet(event: str, /, **fields: object) -> None:
    return None


@dataclass(frozen=True)
class Runtime:
    env: Mapping[str, str] = field(repr=False)
    clock: Callable[[], str]
    token: Callable[[], str]
    stdin: Callable[[], str]
    deadline: float = 20.0
    trace: Emit = quiet


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
class NewGroup:
    name: str
    project: str | None
    joinable: bool


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
class Sequenced:
    seq: int
    message: Message


@dataclass(frozen=True)
class ConversationSummary:
    conversation: Conversation
    members: tuple[str, ...]
    messages: int
    first_seq: int | None
    last: Sequenced | None


@dataclass(frozen=True)
class Snapshot:
    cursor: int
    conversations: tuple[ConversationSummary, ...]


@dataclass(frozen=True)
class Page:
    summary: ConversationSummary
    messages: tuple[Sequenced, ...]
    files: Mapping[str, Sequence[Attachment]]
    more: bool


@dataclass(frozen=True)
class Batch:
    cursor: int
    messages: tuple[Sequenced, ...]
    files: Mapping[str, Sequence[Attachment]]
    touched: tuple[ConversationSummary, ...]
    full: bool


@dataclass(frozen=True)
class BellhopMessage:
    id: str
    state: PingState
    urgency: str | None
    detail: str | None
