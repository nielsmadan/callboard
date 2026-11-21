# Documentation map

User guides:

- [README](../README.md): what callboard is and the command list.
- [Getting started](user/getting-started.md): requirements, joining, humans, the agent skill,
  files and configuration.
- [Chat](user/chat.md): direct messages, groups, reading, receipts, attachments, pings.
- [Mail](user/mail.md): threads with a subject, to and cc.
- [JSON output](user/json.md): the `--json` contract, exit codes and error codes.
- [Admin](user/admin.md): `admin conversations`, `admin history` and `admin watch`, which
  read every conversation and mark nothing read.

App:

- [The Callboard app](app.md): the macOS viewer, how it talks to callboard, the demo store and
  troubleshooting.

For agents:

- [Agent skill](../skills/callboard/SKILL.md): bundled in the wheel as `callboard/_skills/`.

For builders:

- [AGENTS.md](../AGENTS.md): conventions for working on the code.
- [0001 — Foundations](decisions/0001-foundations.md): the product and engineering decisions
  callboard is built on.
- [0002 — bellhop calls get their worst case](decisions/0002-bellhop-deadlines.md): how callboard
  times bellhop calls and the `--confirm` wait.
- [0003 — The app observes through `callboard admin`](decisions/0003-observer-app.md): why the
  app reads JSON from the CLI and keeps its own view marks.
- [Loadout snippets](handoff/loadout-snippets.md): installing the skill and allowing the commands
  through loadout; proposed, not applied.
- [Live smoke](tests/smoke.md): the end-to-end run against real agents, and its record.
- [bellhop fixtures](../tests/contract/SOURCE.md): bellhop's golden JSON that the tests replay,
  and the few cases derived from it.
