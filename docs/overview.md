# Documentation map

User guides:

- [README](../README.md): what callboard is and the command list.
- [Getting started](user/getting-started.md): requirements, joining, humans, the agent skill,
  files and configuration.
- [Chat](user/chat.md): direct messages, groups, reading, receipts, attachments, pings.
- [Mail](user/mail.md): threads with a subject, to and cc.
- [JSON output](user/json.md): the `--json` contract, exit codes and error codes.

For agents:

- [Agent skill](../skills/callboard/SKILL.md): bundled in the wheel as `callboard/_skills/`.

For builders:

- [AGENTS.md](../AGENTS.md): conventions for working on the code.
- [0001 — Foundations](decisions/0001-foundations.md): the product and engineering decisions
  callboard is built on.
- [Loadout snippets](handoff/loadout-snippets.md): installing the skill and allowing the commands
  through loadout; proposed, not applied.
- [Provisional bellhop fixtures](../tests/contract/PROVISIONAL.md): the bellhop JSON the tests
  replay until bellhop's own goldens exist.
