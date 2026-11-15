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
| `send-degraded.json` | `bellhop send … --or-hold --json` to a live target without a usable route: stored as `hold`, `degraded_from: "idle"` |
| `send-replayed.json` | `bellhop send … --key K --json` with a key bellhop already knows: the existing message, nothing pushed |
| `status.json` | `bellhop status bh_7f3a9c2e41d0 bh_000000000000 --json`: one confirmed message, the unknown id in `warnings` |
| `status-pending.json` | `bellhop status bh_7f3a9c2e41d0 --json` while the message is still pending |
| `sessions.json` | `bellhop sessions --json` with one agent-bound and one unbound session |
| `agents.json` | `bellhop agents --json`: a live bound agent, a configured stopped agent, a failed bound name |

`tests/fakes/bellhop` replays them: `FAKE_BELLHOP_<COMMAND>` names the fixture for that
subcommand, the fixture is printed on stdout, and the process exits with its `exit_code` (0 when
absent). `FAKE_BELLHOP_LOG`, when set, receives one JSON line per call with its argv and stdin.
`FAKE_BELLHOP_SLEEP` delays the answer by that many seconds, `FAKE_BELLHOP_EXIT` overrides the exit
code, and `FAKE_BELLHOP_RAW` prints that text instead of a fixture (for malformed output).
`FAKE_BELLHOP_KEYED_IDS` makes a `send` answer with the `--key` it was given and an id derived
from it, so several recipients get distinct bellhop ids.
