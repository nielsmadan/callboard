# Where these fixtures come from

`tests/fakes/bellhop` replays these files. They are bellhop's own contract, copied from
`bellhop/tests/golden/` at bellhop commit **3036bd3** with
`git -C <bellhop> show 3036bd3:tests/golden/<file>`, unchanged:

`agents.json`, `bind.json`, `bind-conflict.json`, `doctor-failed.json`, `inbox.json`,
`send-confirmed.json`, `send-degraded.json`, `send-hls-unavailable.json`, `send-no-route.json`,
`send-pending.json`, `send-push-rejected.json`, `send-sent.json`, `send-target-ambiguous.json`,
`send-target-not-found.json`, `send-usage.json`, `sessions.json`, `status.json`, `whoami.json`,
`whoami-caller-unknown.json`.

bellhop's `docs/user/json.md` at that commit documents every object and error code.

## Derived

callboard needs a few cases bellhop has no golden for. Each is the nearest real golden with the
fields named here changed, and nothing else:

| File | Derived from | Changed |
|---|---|---|
| `whoami-no-agent.json` | `whoami.json` | `session`: the `beta` session from `sessions.json` (`2e20ffff-…`, `codex`, `beta`), `agent: null` |
| `send-sending.json` | `send-sent.json` | `state: "sending"`, `detail` and `sent_at` null |
| `send-read.json` | `send-sent.json` | `urgency: "hold"`, `state: "read"`, `route: "none"`, `detail` and `sent_at` null |
| `send-replayed.json` | `send-sent.json` | `key: "cb_000000000002:utu"` (a send for a key bellhop already holds returns that message) |
| `send-held.json` | `send-pending.json` | `urgency: "hold"`, `degraded_from: "idle"` (what `--or-hold` returns when the target has no usable route) |
| `send-unconfirmed.json` | `send-sent.json` | `warnings: ["cannot confirm: no transcript to read for this session"]` (bellhop's documented `--confirm` warning) |
| `send-expired.json` | `send-sent.json` | `state: "failed"`, `detail: "expired"`, `sent_at` null (a `--key` replay of an expired message; bellhop answers `ok`) |
| `send-not-confirmed.json` | `send-sent.json` | `warnings: ["not confirmed within 5s"]` (bellhop's other documented `--confirm` warning) |
| `send-interrupted.json` | `send-push-rejected.json` | `exit_code: 130`, `error: {code: "interrupted", …}`, message `state: "sending"`, `detail` null (Ctrl-C after the store) |
| `send-internal-error.json` | `send-push-rejected.json` | `error: {code: "internal_error", …}`, message `state: "sent"`, `detail: "fake accepted"`, `sent_at` set (a failure after the push) |
| `status-confirmed.json` | `send-confirmed.json` | its `message` as the only entry of `messages`, no warnings |
| `status-pending.json` | `send-pending.json` | its `message` as the only entry of `messages`, no warnings |

## The fake

`FAKE_BELLHOP_<COMMAND>` names the fixture for that subcommand. The fixture is printed on stdout,
and the process exits with its `exit_code` (0 when absent).

- `FAKE_BELLHOP_LOG`, when set, receives one JSON line per call with its argv and stdin.
- `FAKE_BELLHOP_SLEEP` delays the answer by that many seconds.
- `FAKE_BELLHOP_EXIT` overrides the exit code.
- `FAKE_BELLHOP_RAW` prints that text instead of a fixture, for malformed output.
- `FAKE_BELLHOP_RAW_HEX` prints those bytes.
- `FAKE_BELLHOP_KEYED_IDS` makes a `send` answer with the `--key` it was given and an id derived
  from it, so several recipients get distinct bellhop ids.
