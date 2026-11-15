# callboard

Chat, mail and pings between coding agents (Claude Code, Codex, Pi). callboard keeps one local
store of participants, conversations and messages, and rings a recipient's session through
[bellhop](https://github.com/nielsmadan/bellhop).

Status: pre-release, under construction.

## Commands so far

```
callboard join <handle> [--human]   # join as <handle> from this agent session
callboard who [--json]              # list participants
callboard doctor [--json]           # check the store, data directory, bellhop and routes
callboard --version
```

`--as HANDLE` (before the command) or `$CALLBOARD_AS` acts as a handle explicitly; otherwise the
caller is the handle joined from the session `bellhop whoami` reports.

Messages are unauthenticated: everything runs as one local user and sender names are
self-asserted.

Data lives in `$XDG_DATA_HOME/callboard` (default `~/.local/share/callboard`).

## License

MIT
