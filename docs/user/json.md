# JSON output

Every command that takes `--json` prints exactly one JSON object on stdout and nothing else.
Diagnostics go to stderr, prefixed `callboard: `. The contract below is `schema_version` 1.

## Envelope

Success:

```json
{"schema_version": 1, "status": "ok", "warnings": [], "...": "command fields"}
```

`warnings` holds non-fatal problems as strings. The same text also goes to stderr.

Failure:

```json
{
  "schema_version": 1,
  "status": "error",
  "exit_code": 3,
  "error": {"code": "not_a_member", "message": "'utu' is not a member of group:ops"}
}
```

Keys are snake_case. Times are ISO-8601 UTC (`2026-11-14T09:00:00Z`). Usage errors are reported
in this envelope too, whenever `--json` appears on the command line.

## Exit codes and error codes

| Exit | Meaning | `error.code` values |
|---|---|---|
| 0 | ok | — |
| 1 | failure | `bellhop_failed`, `doctor_failed`, `group_exists`, `invalid_environment`, `schema_too_new`, `store_unavailable` |
| 2 | usage | `usage` |
| 3 | not found or ambiguous | `conversation_not_found`, `identity_ambiguous`, `identity_not_found`, `message_not_found`, `not_a_member`, `not_in_session`, `unknown_handle` |
| 4 | no usable route | — (reserved for ringing) |
| 5 | hls unavailable | `hls_unavailable` |
| 130 | interrupted | `interrupted` |

- `bellhop_failed`: bellhop is missing from `PATH`, timed out, printed no `schema_version` 1
  JSON, or reported an error that is neither "not in a session" nor "hls unavailable".
- `not_in_session`: `bellhop whoami` found no session for the caller (`callboard join` fails
  with it).
- `identity_not_found`: the caller's session has not joined. The message ends with
  `run: callboard join <handle>`.
- `identity_ambiguous`: more than one handle is routed to the caller's session; pass `--as`.
- `unknown_handle`: `--as`, `$CALLBOARD_AS`, a recipient or a group member names no participant.
- `store_unavailable`: the store cannot be created, opened, written or migrated.
- `schema_too_new`: the store was written by a newer callboard.

## Shared objects

A participant:

```json
{"handle": "enki", "kind": "agent", "route": "enki", "created_at": "2026-11-14T09:00:00Z"}
```

`kind` is `agent` or `human`. `route` is the bellhop target (an agent name or session id), or
`null` for humans.

A message:

```json
{
  "id": "cb_000000000003",
  "conversation_id": "group:ops",
  "sender": "niels",
  "body": "on it",
  "parent_id": "cb_000000000002",
  "created_at": "2026-11-14T09:00:00Z"
}
```

`conversation_id` is `dm:<a>:<b>` (handles sorted), `group:<name>` or `mail:<id>`.

A conversation, as listed by `inbox`:

```json
{"ref": "@enki", "id": "dm:enki:nanna", "kind": "dm", "name": null, "subject": null, "project": null}
```

`ref` is what `read` and `history` accept: `@<other handle>` for a direct conversation, otherwise
the id itself.

## `callboard who --json`

```json
{"schema_version": 1, "status": "ok", "warnings": [], "you": "enki", "participants": [participant, ...]}
```

`you` is the caller's handle, or `null` when the caller cannot be resolved. In that case,
ambiguity, an hls outage or a bellhop failure is reported in `warnings`. Participants are sorted
by handle.

## `callboard doctor --json`

```json
{
  "schema_version": 1, "status": "ok", "warnings": [],
  "checks": [
    {"name": "data_dir", "status": "ok", "detail": "/home/u/.local/share/callboard"},
    {"name": "store", "status": "ok", "detail": "schema version 1, 3 participants"},
    {"name": "bellhop", "status": "ok", "detail": "/usr/local/bin/bellhop"},
    {"name": "routes", "status": "warn", "detail": "1 of 2 routes no longer resolve"}
  ],
  "unresolved": [{"handle": "gone", "route": "0b0b0b0b-dead-4c8e-9d3b-1f6a2e8c0d47"}]
}
```

Each check's `status` is `ok`, `warn` or `fail`. When any check fails, the object is the error
envelope (`doctor_failed`, exit 1) with `checks` and `unresolved` still present. A route resolves
when it is a session id or agent name in `bellhop sessions --json`. A configured agent that is not
running currently shows as unresolved.

## `callboard inbox --json`

```json
{"schema_version": 1, "status": "ok", "warnings": [], "conversations": [
  {"ref": "group:ops", "id": "group:ops", "kind": "group", "name": "ops", "subject": null,
   "project": "bellhop", "unread": 2, "mentions": 1}
]}
```

There is one entry per conversation with unread messages for the caller. Conversations with
unread mentions come first, then the most recent activity first. `mentions` counts unread
messages that mention the caller.

## `callboard read <ref> --json`

```json
{"schema_version": 1, "status": "ok", "warnings": [], "ref": "group:ops", "peek": false,
 "messages": [message, ...]}
```

For a conversation ref, `messages` are the caller's unread messages in `seq` order, and they are
now marked read unless `peek` is true. For a message id, `messages` holds that one message.

## `callboard history <ref> --json`

```json
{"schema_version": 1, "status": "ok", "warnings": [], "ref": "@enki", "messages": [message, ...]}
```

This returns the latest `--limit` messages (default 20) in `seq` order and marks nothing read. A
message id selects that message's conversation.

## `callboard receipts <message-id> --json`

```json
{"schema_version": 1, "status": "ok", "warnings": [], "message": message, "receipts": [
  {"recipient": "nanna", "ping": "idle", "ping_state": "pending", "bellhop_id": null,
   "inline": false, "read_at": null}
]}
```

There is one receipt per recipient, sorted by handle; the sender has none. `ping` is `none`,
`hold`, `idle` or `now`. `ping_state` is `null` when `ping` is `none`; otherwise it starts as
`pending` and later mirrors the bellhop message state.
