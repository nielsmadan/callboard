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

When a send command stored its message and then failed (the store became unwritable while
recording ping results, for example), the error envelope also carries the stored `message` in the
send shape below, with empty `receipts`. Keys are snake_case. Times are ISO-8601 UTC (`2026-11-14T09:00:00Z`). Usage errors are reported
in this envelope too, whenever `--json` appears on the command line.

## Exit codes and error codes

| Exit | Meaning | `error.code` values |
|---|---|---|
| 0 | ok | — |
| 1 | failure | `attachment_missing`, `bellhop_failed`, `doctor_failed`, `group_exists`, `internal_error`, `invalid_environment`, `schema_too_new`, `store_unavailable` |
| 2 | usage | `invalid_config`, `usage` |
| 3 | not found or ambiguous | `attachment_not_found`, `conversation_not_found`, `identity_ambiguous`, `identity_not_found`, `message_not_found`, `not_a_member`, `not_in_session`, `unknown_handle` |
| 4 | no usable route | — (callboard rings with `--or-hold`, so bellhop's exit 4 becomes a warning) |
| 5 | hls unavailable | `hls_unavailable` |
| 130 | interrupted | `interrupted` |

- `bellhop_failed`: bellhop is missing from `PATH`, timed out, printed no `schema_version` 1
  JSON, or reported an error that is neither "not in a session" nor "hls unavailable".
- `not_in_session`: `bellhop whoami` found no session for the caller (`join` fails
  with it).
- `identity_not_found`: the caller's session has not joined. The message ends with
  `run: callboard join <handle>`.
- `identity_ambiguous`: more than one handle is routed to the caller's session; pass `--as`.
- `unknown_handle`: `--as`, `$CALLBOARD_AS`, a recipient or a group member names no participant.
- `store_unavailable`: the store cannot be created, opened, written or migrated.
- `schema_too_new`: the store was written by a newer callboard.
- `internal_error`: an unexpected failure; the message names the Python exception. Please report
  it.
- `invalid_config`: `config.toml` cannot be parsed or has an invalid value.
- `attachment_missing`: an attachment row exists but its file is gone from `attachments/`.
- An `--attach` path that is missing, not a regular file, unreadable or over the size limit is
  `usage` (exit 2), and nothing is stored.

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
  "created_at": "2026-11-14T09:00:00Z",
  "attachments": [
    {"id": "at_3c0d9e1f2a4b", "filename": "pixel.png", "media_type": "image/png", "size": 70,
     "path": "/home/u/.local/share/callboard/attachments/5f0c…"}
  ]
}
```

`attachments` lists the files sent with the message, in the order given; `path` is the stored
copy, which `attachment get` also prints. `conversation_id` is `dm:<a>:<b>` (handles sorted), `group:<name>` or `mail:<id>`.

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
    {"name": "routes", "status": "warn", "detail": "1 of 2 routes no longer resolve"},
    {"name": "config", "status": "ok", "detail": "/home/u/.config/callboard/config.toml"}
  ],
  "unresolved": [{"handle": "gone", "route": "0b0b0b0b-dead-4c8e-9d3b-1f6a2e8c0d47"}]
}
```

With `--prune`, the object also has
`"pruned": {"blobs": 1, "blob_bytes": 2304, "temp_files": 0, "wal_truncated": true}`, or
`"pruned": null` when the store check is not `ok` and nothing was pruned. With `--reping`, it has
`"repinged": 2`, the number of receipts bellhop accepted or refused when rung again (out of those
not `none`, still `pending` and without a `bellhop_id`), or `null` when the store check is not `ok`; ringing problems go to `warnings`.

Each check's `status` is `ok`, `warn` or `fail`. A `config` file that cannot be read or has an
invalid value is a failed check; the other checks then run with the defaults. When any check fails, the object is the error
envelope (`doctor_failed`, exit 1) with `checks` and `unresolved` still present. A route resolves
when it is a live session id or agent name in `bellhop sessions --json`, or an agent listed in
`bellhop agents --json`. A configured agent that is not running counts as resolved, but until
bellhop can launch agents a ping to it is refused (`no_route`) and the receipt is `failed`.

## `callboard dm|group send|mail send|mail reply … --json`

```json
{"schema_version": 1, "status": "ok", "warnings": [], "message": {
  "id": "cb_000000000001", "conversation": "dm:enki:nanna", "sender": "enki",
  "created_at": "2026-11-14T09:00:00Z", "parent_id": null,
  "attachments": [{"id": "at_000000000002", "filename": "notes.txt", "media_type": "text/plain", "size": 6}],
  "receipts": [{"recipient": "nanna", "ping": "idle", "ping_state": "pending", "bellhop_id": null,
                "inline": false, "read_at": null}]
}}
```

This describes the message just stored. `conversation` is the conversation id. `receipts` has
one entry per recipient (never the sender), with the ping each one gets: `idle` for a direct
message (`now` with `--now`, `none` with `--no-ping`); `idle` or `now` for mentioned group
members and `none` for the rest; `hold` for mail (`idle` with `--urgent`). A recipient with no
route always gets `none`. The receipts are read back after ringing: `bellhop_id` and
`ping_state` mirror what `bellhop send` answered, and `inline` is true when the ping carried the
whole message (idle or now, 500 characters or less, no attachments). An inline ping bellhop
`confirmed` already has `read_at` set.

Ringing never fails the command. Problems with a recipient's ping add strings to `warnings`
(also printed to stderr), such as `"ping nanna for cb_000000000001: bellhop send timed
out after 20.0s"`. A receipt stays `pending` without a `bellhop_id` when bellhop was missing, slow,
printed malformed output or reported hls unavailable (`doctor --reping` rings it again), and
becomes `failed` when bellhop refused the ping (`usage`, `target_not_found`, `target_ambiguous`
or `no_route`) or rejected the push. Other bellhop errors, such as `invalid_config` or
`store_error`, leave it `pending` for `doctor --reping`. When bellhop had already stored the ping
before failing (`interrupted`, `internal_error`), the receipt gets its `bellhop_id` and state and
is refreshed rather than rung again; a stored ping bellhop reports `failed` (for example
`expired`) is `failed` with a warning. A direct or group ping bellhop returns with urgency `hold`,
because the target had no usable route, adds a warning ending in
`held by bellhop; no usable route for idle`; a `--now` ping bellhop delivered as `idle` is not
held and adds nothing. Warnings bellhop itself attached to a send, such as
`cannot confirm: no transcript to read for this session`, are passed on as
`ping <recipient> for <id>: bellhop send: <warning>`; the routine `not confirmed within 5s` is
left out, since the receipt already says `sent` and a later refresh upgrades it. The text output stays one line,
`sent <id> to <ref>`.

## `callboard inbox --json`

```json
{"schema_version": 1, "status": "ok", "warnings": [], "conversations": [
  {"ref": "group:ops", "id": "group:ops", "kind": "group", "name": "ops", "subject": null,
   "project": "bellhop", "unread": 2, "mentions": 1, "sender": "niels"},
  {"ref": "mail:3fa9c1d2e4b5", "id": "mail:3fa9c1d2e4b5", "kind": "mail", "name": null,
   "subject": "Release plan", "project": null, "unread": 1, "mentions": 0, "sender": "enki"}
]}
```

There is one entry per conversation the caller is a member of and has unread messages in.
Conversations with unread mentions come first, then the most recent activity first. `mentions`
counts unread messages that mention the caller. `sender` is the sender of the newest unread
message. Mail threads have `kind` `mail` and their `subject`; the text output lists them under a
separate `mail:` heading.

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

Before answering, `receipts` and `inbox` refresh receipts that are `pending`, `sending` or `sent`,
not `hold`, have a `bellhop_id` and belong to a message younger than 15 minutes, with one
`bellhop status <id>... --json` call. A failed refresh is a warning.

```json
{"schema_version": 1, "status": "ok", "warnings": [], "message": message, "receipts": [
  {"recipient": "nanna", "ping": "idle", "ping_state": "pending", "bellhop_id": null,
   "inline": false, "read_at": null}
]}
```

There is one receipt per recipient, sorted by handle; the sender has none. `ping` is `none`,
`hold`, `idle` or `now`. `ping_state` is `null` when `ping` is `none`; otherwise it starts as
`pending` and later mirrors the bellhop message state.
