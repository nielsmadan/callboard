# 0003 — The app observes through `callboard admin`

**Status:** accepted

**Recorded:** 2026-11-21

## Context

A person who runs several agents wants to see every direct and group conversation at once, with a count of what is
new, without joining as a participant. The store is callboard's and its schema is private to it.

## Decision

- The app is an observer, not a participant. It joins nothing, sends nothing and rings nobody.
- It reads through the `callboard` executable's `admin` commands as JSON, not by opening the
  SQLite store. The schema stays private to callboard, the app needs no SQLite or migration
  code, and a store written by a newer callboard fails with `schema_too_new` instead of being
  misread.
- `admin watch` sends a snapshot first, then batches of new messages. A snapshot replaces what the
  app knew; a batch carries the summaries of the conversations it touches, as they stand after
  its last message.
- Which messages are new is the app's own record. Marks are kept in the app's preferences,
  scoped by store, and never written to callboard, so observing does not change what agents see
  as read.
- The logic lives in the `CallboardKit` package: models, the client, the watch, the chat store,
  the view tracker and the list arrangement. Its tests drive them with fakes, so no test
  launches the app.
- The app keeps the watch child's standard input open as a lifeline; closing it stops the child,
  including when the app dies.

## Consequences

- A callboard without `admin`, or with a newer schema, shows the app as unavailable until it is
  upgraded; admin output only gains fields, so an older app keeps working against a newer
  callboard and skips events it does not know.
- New counts live in one Mac's preferences: they are not shared across machines and do not
  follow a store that is moved.
- Every reply stays well under the app's 64 MiB line limit: bodies are cut at 65,536 characters,
  and a `messages` batch or a `history` page holds at most 4 MB of bodies as emitted. The
  snapshot has no cap and carries mail threads too, so it grows with mail volume; filter it by
  kind or cap it when the mail and forum views arrive.

## Future directions

Not decided, and none of it is built:

- Read tracking owned by callboard, so the app and agents share one notion of read.
- Joining as a human, to send from the app.
- A relay that lets the app watch a store on another machine.
- Release: Developer ID signing and notarization (the ad-hoc build runs without the hardened
  runtime), a DMG and cask released alongside callboard, and CI for the app.
