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
- A direct message pings; in a group only an @mention pings; mail pings only with `--urgent`. A
  ping is bellhop `idle` plus wake by default, `--now` for an interrupt.
- A short ping (body of 500 characters or less, no attachments) carries the full text and counts as
  read once bellhop confirms it; anything else is a doorbell read with `callboard read`.
- There is no human notifier. Any identity may read and post through the CLI.
- Messages are unauthenticated: everything runs as one user and sender names are self-asserted.
- Scope now: direct chat, groups, mail, attachments, pings and mentions, read receipts, CLI and
  JSON, a bundled skill. Schema-ready only: replies branching off a message (`parent_id`), topic
  subscriptions. Not now: forums, an MCP adapter, a UI, Telegram.

Engineering:

- Python 3.13 or newer, uv, hatchling, `src/` layout, argparse, standard library only at runtime.
- Data in `$XDG_DATA_HOME/callboard` (default `~/.local/share/callboard`), config in
  `$XDG_CONFIG_HOME/callboard/config.toml`. A relative XDG value is refused. Files 0600, dirs 0700.
- SQLite in WAL mode with `synchronous=NORMAL`, `foreign_keys=ON`, explicit `BEGIN IMMEDIATE`
  write transactions and a 30 s busy timeout. Only SQL runs inside a write transaction. The schema
  version lives in `meta.schema_version`; numbered forward migrations re-check the version inside
  their own transaction, and a newer schema is refused. Rows are ordered by an autoincrement `seq`.
- callboard runs the `bellhop` on `PATH` and gives it 20 s in total. A failed, missing or slow
  bellhop never loses a stored message.
- `--json` prints exactly one object with `schema_version`; errors carry `status: "error"`,
  `exit_code` and `error: {code, message}`. Keys are snake_case, times ISO-8601 UTC.
- Exit codes: 0 ok, 1 failure, 2 usage, 3 not found or ambiguous, 4 no usable route, 5 hls
  unavailable, 130 interrupted.

## Consequences

- Any local process can post as any handle; the docs say so and no auth is built.
- callboard's tests depend on bellhop's JSON contract, pinned as fixtures in `tests/contract/`.
