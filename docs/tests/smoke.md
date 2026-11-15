# Live smoke

`just smoke` runs `tests/smoke/test_live.py` against two real agents. It unpacks a `git archive`
of the bellhop commit named in the Justfile (`bellhop_commit`, repo `$BELLHOP_REPO`, default
`../../bellhop/dev1`) into `.cache/bellhop-<commit>/` and runs pytest with that copy installed
next to callboard (`uv run --with`). Nothing is installed globally, and bellhop's working tree is
never imported. `bellhop_commit` is a full hash; a missing repo or commit stops the recipe with
`just smoke: no bellhop git repo at …; set BELLHOP_REPO` or `just smoke: bellhop commit … not
found in …`. The test asserts that the `callboard` and `bellhop` the agents run are the scripts
of that environment: callboard from this checkout's `src`, bellhop installed from the archive.

## Set-up

- `bellhop.testing.run.SmokeRun` on `tmux -L callboard-smoke`, one isolated home per run under
  `.cache/smoke/<run>/`: `HOME`, `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `PI_CODING_AGENT_DIR`, all
  four `XDG_*` and `TMPDIR` resolve inside it. bellhop's runtime directory is `/tmp/bellhop-smoke-<run>`, outside
  the run directory, because socket paths must stay under 104 bytes. It is removed at teardown.
- Agents:
  - `cl`: Claude Code with `haiku`, permission mode `default`, bellhop's MCP relay through
    `--mcp-config`. Its allow-list, passed to the helper (`SmokeRun(claude_allowed=…)`, written
    to the isolated `settings.json`), is the exact commands the cells ask for: `callboard join
    cl` and `callboard dm pi "pong <token>"` (the token is chosen before the launch), and
    `callboard read` with any argument, since message ids are not known at launch and `read`
    takes no path.
  - `pi`: Pi with `openrouter/deepseek/deepseek-v4.1-flash` and bellhop's extension (`-e`). Pi
    has no permission prompts, so it has no allow-list.
- The harness pair is Claude and Pi. Codex needs an isolated app-server daemon and adds minutes,
  and bellhop's own smoke covers it.
- Each agent's first prompt tells it to run `callboard join <handle>`, to do what a callboard
  message asks, and to run `callboard read <id>` when a ping is a doorbell. A human handle,
  `driver`, joins without a session and drives the cells with `--as driver`.
- Before the run and after it, the test checks: no `callboard-smoke` tmux server, no process whose
  command names `.cache/smoke`, no symlinked run entry; the helper reports no leftovers; the
  runtime directory is gone; the run's drainer is stopped; no session named after one of the
  run's agents (`cl`, `pi`, `scribe`, or bellhop's `-2` … `-9` variants) appeared on the default
  tmux server (listed only, with `$TMUX` removed; the user's own sessions may come and go); `~/.local/share/callboard`,
  `~/.local/state/bellhop` and `~/.config/bellhop` are unchanged (existence and modification
  time; on this machine all three are absent), and the real runtime directory
  `/tmp/bellhop-<uid>` exists before and after exactly when it did (existence only, since real
  sessions change it). These checks fail the run even when a cell failed; then they are added to
  the error as a note.
- The run's drainer is detached. The helper's teardown stops it after the agents and the tmux
  server (`bellhop.testing.run.stop_drainer`, which refuses any state directory outside a run)
  and reports one that survives as a leftover.
- Each run writes `logs/callboard-cells.json` (message ids and receipts per cell) or
  `logs/launch-cell.json` (the launch cell's steps), `logs/leftovers.json` and the final screen
  of each launched agent, also when a step fails.

## Cells

| Cell | Pass |
|---|---|
| short dm, inline, read | `dm pi` under 500 characters: receipt `idle`, `inline`, `confirmed`, `read_at` set; Pi's transcript holds `<id> dm from driver: …` |
| long dm with an image, doorbell | `dm cl` of about 660 characters with a PNG: receipt `idle`, not inline; Claude's transcript holds the doorbell (`(… chars, 1 attachment); read: callboard read <id>`); Claude runs `callboard read` and the receipt gets `read_at` |
| reply rings the other | the driver asks `cl` to run `callboard dm pi "pong <token>"`; that message exists, its receipt for `pi` is `confirmed` and read, and Pi's transcript holds `dm from cl: pong <token>` |
| group mention | `group send smoke "@pi …"` to `cl`, `pi` and `driver`: `pi` rings `idle` and confirms, `cl` gets `none` and its transcript never shows the token (checked 15 s after Pi's confirmation) |
| mail waits | `mail send --to cl`: receipt `hold`, `pending`; `callboard --as cl inbox` lists the thread with 1 unread from `driver` (checked before Claude can read it); the next dm to `cl` arrives with `(bellhop: 1 more waiting; …)` |
| urgent mail to a stopped agent starts it | `test_urgent_mail_to_a_stopped_agent_starts_it`, its own run. `[agents.scribe]` comes from the helper's `agent_block` (Claude, `haiku`, its isolated home prepared) with the isolated `HOME`, `CLAUDE_CONFIG_DIR`, `XDG_*`, `TMPDIR`, `BELLHOP_RUNTIME_DIR` and `PATH` added to its `env`; `write_bellhop_config` sets `tmux_socket = "callboard-smoke"`, and the test re-reads both, asserting the socket and every one of those values. `bellhop launch scribe --prompt <join>` starts it on `tmux -L callboard-smoke` and it joins; the test kills that session and waits for its processes to exit. `mail send --to scribe --urgent` then rings `idle` with `--wake`: the receipt is `pending`, a new `scribe` session is on `tmux -L callboard-smoke` (adopted with `adopt_session`, so teardown stops it), its binding is `live` with cause `send --wake from driver` and a new session id (the first start's binding was `live` with cause `launch`), the new session's own transcript holds `[bellhop <id> from driver] callboard <id> mail …` and Claude's answer `ACK <token>`, the wake's warning `--confirm does not wait …` is not shown, bellhop's message has route `launch`, detail `started with this prompt` and state `confirmed`, and the receipt settles at `confirmed` with `read_at` set (the inline mail counts as read). No `scribe` session appears on the default tmux server (listed, never touched) after the kill or at the end |

## Runs

2026-11-14, bellhop `843e3b6`, Claude Code 2.1.325, Pi 1.5.2, hooklinesinker 1.5.1, tmux 3.8,
macOS 27.2.

| Run | Result | Notes |
|---|---|---|
| `20261114-153906-d4c2` | 3 of 5 | the reply and group cells failed on two test bugs, fixed: the reply's receipt was asked for as `driver`, who is not in the `cl`–`pi` dm, and `group create` was given `--json`, which it does not take. The reply itself was delivered and read |
| `20261114-154423-da19` | 5 of 5, 34 s | every ping reached its transcript once. Pi answered the `pong` by sending one back to `cl`; the first prompt now tells agents not to send unasked |
| `20261114-155729-55d9` | 5 of 5, 35 s | the committed test, after review fixes (logs written on failure, inbox checked before the nudge, `python -m pytest` in the recipe). Every ping reached its transcript once; no agent sent anything unasked |
| `20261114-161015-b7ad` | 5 of 5, 37 s | after the K-9f fixes: exact allow-list entries, the drainer stopped only through its own lock, leftover checks that also fail a failed run. No problems recorded |

2026-11-14, bellhop `53618c7` (the launcher), Claude Code 2.1.325, Pi 1.5.2, hooklinesinker 1.5.1,
tmux 3.8, macOS 27.2. Each `just smoke` is two runs, one per test.

| Run | Result | Notes |
|---|---|---|
| `20261114-190045-6059` + `20261114-190125-b08d` | 5 of 5 and the launch cell, 63 s | the allow-list now comes from the helper's `settings.json`, and its teardown stops the drainer. The wake started `scribe` on `tmux -L callboard-smoke`, live a second after the send; the new session's transcript holds the mail's envelope once and Claude answered `ACK`. The receipt settled at `sent`, unread, and the send passed on bellhop's warning `--confirm does not wait for a message that starts its agent`. No problems recorded |
| `20261114-190953-087c` + `20261114-191052-7aa6` | 5 of 5 and the launch cell, 101 s | the committed test, after review fixes (the default tmux server is compared in the closing checks on every path, a woken session is adopted before any assert). The woken `scribe` was live 5 s after the send and answered `ACK`; every envelope reached its transcript once; the receipt settled at `sent`, unread, with the same `--confirm` warning. A bellhop smoke ran on `tmux -L bellhop-smoke` at the same time. No problems recorded |
| `20261114-192212-cbf5` + `20261114-192257-d075` | 5 of 5 and the launch cell, 69 s | after K-10f: the wake's `--confirm does not wait …` warning is routine (the send's `warnings` is empty), the default-server check looks only for this run's agent names, and the woken session's own transcript (`e70abdf4-…`) holds the envelope once and Claude's `ACK`. The wake was `sent` 1 s after it was stored; the receipt settled at `sent`, unread. No problems recorded |

2026-11-14, bellhop `f551bdf` (a start's first message is confirmed), Claude Code 2.1.325,
Pi 1.5.2, hooklinesinker 1.5.1, tmux 3.8, macOS 27.2.

| Run | Result | Notes |
|---|---|---|
| `20261114-201847-57c9` + `20261114-201934-e5eb` | 5 of 5 and the launch cell, 76 s | the woken mail (`bh_cce1a1dd22bf`) was stored at 20:19:56, `sent` at :57 and `confirmed` at :58 from the new session's transcript; the receipt reached `confirmed` with `read_at` set, so it counts as read. Every envelope reached its transcript once; Claude answered `ACK`; the send had no warnings. A bellhop smoke ran on `tmux -L bellhop-smoke` at the same time. No problems recorded |
