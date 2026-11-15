# Provisional bellhop fixtures

These files were written by hand from the "bellhop JSON (schema_version 1)" section of the
bellhop + callboard plan (`bellhop/docs/plans/2026-11-13-bellhop-callboard.md`), before bellhop
had a working `whoami` or `send`. They will be replaced by bellhop's own golden JSON from
`bellhop/tests/golden/`, with a note naming the bellhop commit they were copied from.

| File | bellhop command |
|---|---|
| `whoami-agent.json` | `bellhop whoami --json` in a session bound to agent `enki` |
| `whoami-session.json` | `bellhop whoami --json` in a session with no agent name |
| `whoami-not-found.json` | `bellhop whoami --json` outside any known session (exit 3) |
| `send-<state>.json` | `bellhop send … --json` returning a message in that state (`send-failed.json` exits 1) |
| `sessions.json` | `bellhop sessions --json` with one agent-bound and one unbound session |

`tests/fakes/bellhop` replays them: `FAKE_BELLHOP_<COMMAND>` names the fixture for that
subcommand, the fixture is printed on stdout, and the process exits with its `exit_code` (0 when
absent). `FAKE_BELLHOP_LOG`, when set, receives one JSON line per call with its argv and stdin.
