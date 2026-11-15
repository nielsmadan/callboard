# Where these fixtures come from

`tests/fakes/bellhop` replays these files. They are bellhop's own contract, copied from
`bellhop/tests/golden/` at bellhop commit **14de6c2** with
`git -C <bellhop> archive 14de6c2 tests/golden`, unchanged:

`agents.json`, `bind.json`, `bind-conflict.json`, `doctor-failed.json`, `inbox.json`,
`integration-export.json`, `integration-show.json`, `integration-show-claude.json`,
`launch-failed.json`, `launch-live.json`, `launch-started.json`,
`send-confirmed.json`, `send-degraded.json`, `send-held.json`, `send-hls-unavailable.json`,
`send-no-route.json`, `send-not-running.json`, `send-pending.json`, `send-push-rejected.json`,
`send-read.json`, `send-sending.json`, `send-sent.json`, `send-target-ambiguous.json`,
`send-target-not-found.json`, `send-usage.json`, `send-wake.json`, `send-wake-cannot-launch.json`,
`send-wake-confirm.json`, `send-wake-failed.json`,
`sessions.json`, `status.json`, `whoami.json`, `whoami-caller-unknown.json`.

bellhop's `docs/user/json.md` at that commit documents every object and error code.

Copied but read by no test, kept so the set stays bellhop's whole contract (`UNUSED` in
`test_bellhop_contract.py`): `bind.json`, `bind-conflict.json`, `doctor-failed.json`,
`inbox.json`, `integration-export.json`, `integration-show.json`, `integration-show-claude.json`,
`launch-failed.json`, `launch-live.json`, `launch-started.json`.

## Derived

Derived files keep their source's `key` (null for most) unless the row says otherwise. callboard always sends `--key` but never
reads `key` back, so it does not matter to any test.

callboard needs a few cases bellhop has no golden for. Each is the nearest real golden with the
fields named here changed, and nothing else:

| File | Derived from | Changed |
|---|---|---|
| `whoami-no-agent.json` | `whoami.json` | `session`: the `beta` session from `sessions.json` (`2e20ffff-…`, `codex`, `beta`), `agent: null` |
| `whoami-caller-ambiguous.json` | `whoami-caller-unknown.json` | `error.message: "the caller runs inside more than one live session"`, `candidates`: the `alpha` and `beta` sessions from `sessions.json` as bellhop describes them (`<id> (<harness>, <title>)`) |
| `send-replayed.json` | `send-sent.json` | `key: "cb_000000000002:utu"` (a send for a key bellhop already holds returns that message) |
| `send-unconfirmed.json` | `send-sent.json` | `warnings: ["cannot confirm: no transcript to read for this session"]` (bellhop's documented `--confirm` warning) |
| `send-expired.json` | `send-sent.json` | `state: "failed"`, `detail: "expired"`, `sent_at` null (an expired message, as a `--key` replay returns it; bellhop answers `ok`) |
| `send-not-confirmed.json` | `send-sent.json` | `warnings: ["not confirmed within 5s"]` (bellhop's other documented `--confirm` warning) |
| `send-interrupted.json` | `send-push-rejected.json` | `exit_code: 130`, `error: {code: "interrupted", …}`, message `state: "sending"`, `detail` null (Ctrl-C after the store) |
| `send-internal-error.json` | `send-push-rejected.json` | `error: {code: "internal_error", …}`, message `state: "sent"`, `detail: "fake accepted"`, `sent_at` set (a failure after the push) |
| `status-woken.json` | `launch-live.json` | its `message` (`sent`, route `launch`, detail `started with this prompt`) as the only entry of `messages`, no warnings |
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
