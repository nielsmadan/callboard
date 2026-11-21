# JSON output

Every command takes `--json` and then prints exactly one JSON object on stdout and nothing else.
The one exception is `admin watch`, which prints one object per line until it stops.
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
| 1 | failure | `attachment_missing`, `bellhop_failed`, `doctor_failed`, `group_exists`, `handle_taken`, `internal_error`, `invalid_environment`, `schema_too_new`, `store_unavailable` |
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
- `identity_ambiguous`: more than one handle is routed to the caller's session, or bellhop places
  the caller in more than one live session; pass `--as`.
- `unknown_handle`: `--as`, `$CALLBOARD_AS`, a recipient or a group member names no participant.
- `store_unavailable`: the store cannot be created, opened, written or migrated.
- `schema_too_new`: the store was written by a newer callboard.
- `internal_error`: an unexpected failure; the message names the Python exception. Please report
  it.
- `invalid_config`: `config.toml` cannot be parsed, has an invalid value, or has a key callboard
  does not know (the message names it).
- `handle_taken`: `join --human` named an agent's handle whose route still resolves in bellhop
  (a live session or a configured agent; also when bellhop cannot say), or `join` from an agent
  session named a human's handle.
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
{"schema_version": 1, "status": "ok", "warnings": [], "you": "enki", "you_from": "session",
 "participants": [participant, ...]}
```

`you` is the caller's handle, or `null` when the caller cannot be resolved. `you_from` says how it
was found: `"--as"`, `"CALLBOARD_AS"` or `"session"` (`bellhop whoami`), or `null` with `you`. In that case,
ambiguity, an hls outage or a bellhop failure is reported in `warnings`. Participants are sorted
by handle.

## `callboard join <handle> --json`

```json
{"schema_version": 1, "status": "ok", "warnings": [], "participant": {"handle": "enki", "kind": "agent",
 "route": "enki", "created_at": "2026-11-14T21:06:17Z"}, "previous": null, "displaced": []}
```

`participant` is the handle as joined. `previous` is the same handle as it was before, or `null`
for a new one. `displaced` lists other handles this session held, which lose their route.
`warnings` repeats what the text mode prints on stderr about them.

## `callboard group create|add|remove … --json`

```json
{"schema_version": 1, "status": "ok", "warnings": [], "conversation": "group:release", "name": "release",
 "project": "callboard", "members": ["enki", "nanna"]}
{"schema_version": 1, "status": "ok", "warnings": [], "conversation": "group:release", "handle": "niels", "added": true}
{"schema_version": 1, "status": "ok", "warnings": [], "conversation": "group:release", "handle": "niels", "group_deleted": false}
```

A top-level `conversation` is always a conversation id string, as in the send output below;
message objects name the same id `conversation_id`. `create` returns the group's name, project
and sorted members. `add` says whether the handle was added
(`false` when it was already a member). `remove` says whether the group was deleted because its
last member left.

## `callboard attachment get <attachment-id> --json`

```json
{"schema_version": 1, "status": "ok", "warnings": [], "attachment": {"id": "at_296f71e85086",
 "filename": "notes.txt", "media_type": "text/plain", "size": 6,
 "path": "/home/u/.local/share/callboard/attachments/5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"},
 "out": null}
```

`attachment` is the shared attachment object. `out` is the absolute path the `--out` copy was
written to, or `null` without `--out`.

## `callboard log --json`

```json
{"schema_version": 1, "status": "ok", "warnings": [],
 "file": "/home/u/.local/share/callboard/trace.jsonl",
 "events": [
   {"at": "2026-11-15T15:27:43.781Z", "pid": 59960, "event": "sent", "message": "cb_000000000001",
    "conversation": "dm:enki:nanna", "sender": "enki",
    "receipts": [{"recipient": "nanna", "ping": "idle", "ping_state": "pending",
                  "bellhop_id": "bh_000000000001", "inline": true, "read_at": null}]},
   {"at": "2026-11-15T15:27:43.782Z", "pid": 59960, "event": "command",
    "argv": ["--as", "enki", "dm", "nanna", "hello", "--json"], "cwd": "/work", "exit": 0, "ms": 40}
 ]}
```

`events` holds the last N (`-n`, default 40) trace events that contain every TEXT, oldest first.
A `command` event has `argv`, `cwd`, `as` (`$CALLBOARD_AS` when set), `exit`, `code` and `error`
when it failed, and `ms`. A `sent` event has `message`, `conversation`, `sender`, `receipts` (the
shared receipt objects as they stood after the ring) and `warnings`. An empty field is left out.
The fields are for people and may grow. `log` itself is not recorded.

## `callboard doctor --json`

```json
{
  "schema_version": 1, "status": "ok", "warnings": [],
  "checks": [
    {"name": "data_dir", "status": "ok", "detail": "/home/u/.local/share/callboard"},
    {"name": "store", "status": "ok", "detail": "schema version 2, 3 participants"},
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
`bellhop agents --json`. A configured agent that is not running counts as resolved: an `idle`
or `now` ping asks bellhop to start it (`--wake`), with the ping as its first prompt. The receipt
is `pending` until the agent is up, `sent` once it is, and `confirmed` when bellhop finds the
ping in the new session's transcript; an inline ping that started its recipient is then read.
When bellhop cannot start the agent, the receipt stays `pending` and bellhop's warning is passed
on; when the agent's last start failed, bellhop answers `launch_failed` and the receipt is
`failed`.

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
(also printed to stderr), such as `"ping nanna for cb_000000000001: bellhop not found on PATH"`.
Text from bellhop in them (error messages, details, warnings) shows control characters escaped
and is cut to 300 characters.
A receipt stays `pending` without a `bellhop_id` when bellhop was missing, slow, printed malformed
output or reported hls unavailable (`doctor --reping` rings it again). A send that timed out may
already have been pushed, so its warning ends `the outcome is unknown; callboard doctor --reping
settles it`: the re-ring uses the same `--key`, and bellhop answers with the message it already
holds. A bellhop `usage` answer means callboard and bellhop do not match, so the receipt stays
`pending` and the warning says so. A receipt becomes `failed` when bellhop refused the ping
(`target_not_found`, `target_ambiguous` or `no_route`), rejected the push, or answered
`launch_failed`. A receipt's `ping_state` never moves backwards: once `confirmed` or `read`, a
late refusal or an older status does not change it. Other bellhop errors, such as `invalid_config` or
`store_error`, leave it `pending` for `doctor --reping`. When bellhop had already stored the ping
before failing (`interrupted`, `internal_error`), the receipt gets its `bellhop_id` and state and
is refreshed rather than rung again; a stored ping bellhop reports `failed` (for example
`expired`) is `failed` with a warning. A direct or group ping bellhop returns with urgency `hold`,
because the target had no usable route, adds a warning ending in
`held by bellhop; no usable route for idle`; a `--now` ping bellhop delivered as `idle` is not held
and adds nothing. Warnings bellhop itself attached to a send, such as
`cannot confirm: no transcript to read for this session`, are passed on as
`ping <recipient> for <id>: bellhop send: <warning>`. Two routine ones are left out:
`not confirmed within 5s`, since the receipt already says `sent` and a later refresh upgrades it,
and `--confirm does not wait for a message that starts its agent`, since the receipt of a ping that
woke its recipient is `pending` until the agent is up. Every other bellhop warning is passed on,
among them `the now message waits: <why>` for a `--now` ping bellhop could not deliver yet,
`key '<key>' is already stored for <id> with another target or text` when a reping no longer matches
what bellhop stored, and `'<agent>' is not running; the message waits (use --wake to start it)`,
which only a `ping_command` that drops `--wake` can produce. A receipt refresh passes on bellhop's
own warnings the same way, as `refreshing receipts: bellhop status: <warning>`, for example
`cannot recheck transcripts: <why>`. The text output stays one line, `sent <id> to <ref>`.

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
`pending` and later mirrors the bellhop message state, except for `hold` pings and pings older
than 15 minutes, which are not refreshed and keep the state they had.

## `callboard admin conversations --json`

The [admin commands](admin.md) read every conversation, whoever its members are, and mark nothing
read.

```json
{"schema_version": 1, "status": "ok", "warnings": [],
 "store": "/home/u/.local/share/callboard/callboard.sqlite", "cursor": 5, "conversations": [
  {"id": "group:ops", "kind": "group", "name": "ops", "subject": null, "project": "bellhop",
   "created_by": "enki", "created_at": "2026-11-20T23:42:15Z", "members": ["enki", "nanna", "niels"],
   "messages": 3, "first_seq": 3,
   "last": {"seq": 5, "id": "cb_b6ec3819a4fa", "sender": "niels",
            "created_at": "2026-11-20T23:42:15Z", "preview": "on it"}},
  {"id": "dm:enki:nanna", "kind": "dm", "name": null, "subject": null, "project": null,
   "created_by": "enki", "created_at": "2026-11-20T23:42:15Z", "members": ["enki", "nanna"],
   "messages": 2, "first_seq": 1,
   "last": {"seq": 2, "id": "cb_bcf0a84b8008", "sender": "nanna",
            "created_at": "2026-11-20T23:42:15Z", "preview": "rebased, tests pass"}},
  {"id": "group:release", "kind": "group", "name": "release", "subject": null, "project": null,
   "created_by": "enki", "created_at": "2026-11-20T23:42:15Z", "members": ["enki", "niels"],
   "messages": 0, "first_seq": null, "last": null}
]}
```

`store` is the store file read. `cursor` is the highest message `seq` the store has ever handed
out (deleted messages included), or 0 for an empty or missing store; a missing store is not
created. Each conversation summary has the conversation's fields, its sorted `members`, its
message count `messages`, the `seq` of its first message `first_seq`, and its latest message
`last`, both `null` without messages. `kind` is `dm`, `group`, `mail` or `topic`. `preview` is the
body on one line (control characters escaped), cut to 140 characters. Conversations are ordered
by their latest message, newest first, then those without messages by id.

## `callboard admin history <conversation-id> --json`

```json
{"schema_version": 1, "status": "ok", "warnings": [],
 "store": "/home/u/.local/share/callboard/callboard.sqlite",
 "conversation": {"id": "dm:enki:nanna", "kind": "dm", "name": null, "subject": null,
  "project": null, "created_by": "enki", "created_at": "2026-11-20T23:42:15Z",
  "members": ["enki", "nanna"], "messages": 2, "first_seq": 1,
  "last": {"seq": 2, "id": "cb_bcf0a84b8008", "sender": "nanna",
           "created_at": "2026-11-20T23:42:15Z", "preview": "rebased, tests pass"}},
 "messages": [
  {"seq": 2, "id": "cb_bcf0a84b8008", "conversation_id": "dm:enki:nanna", "sender": "nanna",
   "body": "rebased, tests pass", "body_truncated": false, "parent_id": null,
   "created_at": "2026-11-20T23:42:15Z", "attachments": []}
 ], "more": true}
```

`conversation` is the summary `admin conversations` lists. `messages` are the latest `--limit`
messages (default 50, 1 to 500) with a `seq` below `--before`, oldest first: the shared message
object plus `seq` and `body_truncated`. A body longer than 65,536 characters is cut to that length
and has `body_truncated` true. `more` is true when older messages exist before `messages[0]`.
An unknown conversation id, or a missing store, is `conversation_not_found` (exit 3).

## `callboard admin watch --json`

`admin watch --json` prints one object per line and flushes each line. The first line is a
`snapshot`; `messages` lines follow as messages arrive:

```json
{"schema_version": 1, "status": "ok", "warnings": [], "event": "snapshot",
 "store": "/home/u/.local/share/callboard/callboard.sqlite", "cursor": 1, "conversations": [
  {"id": "group:ops", "kind": "group", "name": "ops", "subject": null, "project": null,
   "created_by": "enki", "created_at": "2026-11-21T00:02:17Z", "members": ["enki", "nanna", "niels"],
   "messages": 1, "first_seq": 1,
   "last": {"seq": 1, "id": "cb_6d4063a14921", "sender": "enki",
            "created_at": "2026-11-21T00:02:17Z", "preview": "@nanna please review the release notes"}}
]}
{"schema_version": 1, "status": "ok", "warnings": [], "event": "messages", "cursor": 2,
 "messages": [
  {"seq": 2, "id": "cb_0dcb2511f8a5", "conversation_id": "group:ops", "sender": "nanna",
   "body": "two typos, otherwise fine", "parent_id": null, "created_at": "2026-11-21T00:02:17Z",
   "attachments": [], "body_truncated": false}
 ], "conversations": [
  {"id": "group:ops", "kind": "group", "name": "ops", "subject": null, "project": null,
   "created_by": "enki", "created_at": "2026-11-21T00:02:17Z", "members": ["enki", "nanna", "niels"],
   "messages": 2, "first_seq": 1,
   "last": {"seq": 2, "id": "cb_0dcb2511f8a5", "sender": "nanna",
            "created_at": "2026-11-21T00:02:17Z", "preview": "two typos, otherwise fine"}}
 ]}
```

(Each object is shown wrapped here; the stream puts each on one line.)

- A `snapshot` has the fields of `admin conversations` and replaces everything known before it.
  A missing store, or one with no schema yet, is a snapshot with `cursor` 0 and no
  conversations. A fresh snapshot follows whenever a conversation is created or dropped, its
  members change, or the store file appears, disappears or is replaced. It covers the messages
  read with it, which do not appear in a `messages` line.
- A `messages` line has 1 to 200 new messages, oldest first, with at most 4,000,000 characters of
  bodies between them. Each is the message object of `admin history`. `cursor` is the `seq` of
  the last one. `conversations` holds the summaries of the conversations those messages belong
  to, as they stand after the last one, newest first.
- The stream ends with exit 0 when standard input closes. A store that stays busy (locked) for
  30 seconds ends it with a `store_unavailable` error object and exit 1; a store written by a
  newer callboard ends it with `schema_too_new` and exit 1. Ctrl-C prints the `interrupted`
  error object as the last line and exits 130.
