# 0001 — Foundations

**Status:** accepted

**Recorded:** 2026-11-13

## Context

callboard is agent messaging on top of bellhop, which delivers a short text into a running
coding-agent session. callboard owns the conversations; bellhop owns getting a ping into a session.

## Decision

Product:

- One store holds chat (one running conversation per pair or group) and mail (threads with a
  subject, to and cc).
- Urgency maps onto bellhop's levels:

  | Message | bellhop level | `--wake` |
  |---|---|---|
  | direct message | `idle` (`now` with `--now`; none with `--no-ping`) | yes |
  | group message | `idle` or `now` for a mentioned member; none for other members | yes |
  | mail | `hold` (`idle` with `--urgent`) | only with `--urgent` |

  A recipient with no route gets no ping, and the sender is never rung. Every ping passes
  `--or-hold` and the idempotency key `<message-id>:<recipient>`.
- A short ping (body of 500 characters or less, no attachments, level `idle` or `now`) carries the
  full text and counts as read once bellhop confirms it (immediately, or when a refresh within
  15 minutes of sending sees the confirmation). Anything else, including every `hold`
  ping, is a doorbell that names `callboard read <id>`.
- Ringing happens after the message is committed, never inside the transaction. A failed, missing
  or slow bellhop leaves the receipt `pending` (or `failed` when bellhop refused it) and a warning;
  the command still exits 0.
- A session holds one handle. Joining as a second handle moves the session's route to it.
- There is no human notifier. Any identity may read and post through the CLI.
- Messages are unauthenticated: everything runs as one user and sender names are self-asserted.
- Scope now: direct chat, groups, mail, attachments, pings and mentions, read receipts, CLI and
  JSON, a bundled skill.
- Schema-ready, not built:
  - Replies branching off a message: `messages.parent_id` is stored and checked (`--reply-to`,
    mail replies), but nothing reads a branch as its own thread.
  - Topic subscriptions: conversations of kind `topic` and members with role `subscriber`. No
    command creates either.
- Not now: forums, an MCP adapter, a UI, Telegram.

Engineering:

- Python 3.13 or newer, uv, hatchling, `src/` layout, argparse, standard library only at runtime.
- Data in `$XDG_DATA_HOME/callboard` (default `~/.local/share/callboard`), config in
  `$XDG_CONFIG_HOME/callboard/config.toml`. A relative XDG value is refused. Files 0600, dirs 0700.
- SQLite in WAL mode with `synchronous=NORMAL`, `foreign_keys=ON`, explicit `BEGIN IMMEDIATE`
  write transactions and a 30 s busy timeout. Only SQL runs inside a write transaction. The schema
  version lives in `meta.schema_version`; numbered forward migrations re-check the version inside
  their own transaction, and a newer schema is refused. Rows are ordered by an autoincrement `seq`.
- callboard runs the `bellhop` on `PATH`, or the argv in `ping_command`, for every bellhop call,
  and gives bellhop 20 s in total per command, identity lookup included. Up to 8 recipients ring
  at once.
- `--json` prints exactly one object with `schema_version`; errors carry `status: "error"`,
  `exit_code` and `error: {code, message}`. Keys are snake_case, times ISO-8601 UTC.
- Exit codes: 0 ok, 1 failure, 2 usage, 3 not found or ambiguous, 4 no usable route (reserved;
  never returned, since bellhop's 4 becomes a warning), 5 hls unavailable, 130 interrupted.

## Consequences

- Any local process can post as any handle; the docs say so and no auth is built.
- callboard's tests depend on bellhop's JSON contract, pinned as fixtures in `tests/contract/`.
