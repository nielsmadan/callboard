# 0002 — bellhop calls get their worst case

**Status:** accepted; refines the bellhop budget in [ADR 0001](0001-foundations.md)

**Recorded:** 2026-11-14

## Context

ADR 0001 gave bellhop 20 s per command in total, identity lookup included. bellhop's own budget
for `send` is 10 s (its ADR 0003), a wake adds up to two 5 s tmux calls, and callboard always asked
for `--confirm 5`. A slow `whoami` could therefore leave a send less than its worst case, and
callboard killed a bellhop that had already pushed: the receipt kept no `bellhop_id` until
`doctor --reping`.

## Decision

- The 20 s stay the command's budget, and no bellhop call starts once it is spent.
- A call that starts is given at least bellhop's worst case for it, capped at the whole budget:
  10 s for `whoami`, `sessions`, `agents` and `status`; for `send`, 10 s plus the `--confirm`
  wait, or plus 10 s when it carries `--wake`, whichever is more.
- A ping's `--confirm` is the time left after bellhop's 10 s, from 0 to 5 s.
- A send that still times out is reported as "the outcome is unknown"; its receipt stays
  `pending` without a `bellhop_id`, and `doctor --reping` re-rings it with the same `--key`, so
  bellhop answers with the message it already holds.

## Consequences

- A command can run past 20 s by up to one call's worst case (at most 20 s more), since a call
  that starts just before the budget is spent keeps its worst case.
- Tests that give a command a short budget still see calls time out at that budget, because the
  worst case is capped at it.
