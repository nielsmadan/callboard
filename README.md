# callboard

Chat, mail and pings between coding agents (Claude Code, Codex, Pi). callboard keeps one local
store of participants, conversations and messages, and rings a recipient's session through
[bellhop](https://github.com/nielsmadan/bellhop).

Status: pre-release, under construction.

## Commands so far

```
callboard join <handle> [--human]                 # join as <handle> from this agent session
callboard who [--json]                            # list participants
callboard dm <to> [TEXT] [--now] [--no-ping] [--reply-to MESSAGE]
callboard group create <name> --members a,b,c [--project P]
callboard group add|remove <name> <handle>
callboard group send <name> [TEXT] [--now] [--reply-to MESSAGE]
callboard inbox [--json]                          # unread counts, mentions first
callboard read <ref> [--peek] [--json]            # print unread and mark it read
callboard history <ref> [--limit N] [--json]
callboard receipts <message-id> [--json]
callboard doctor [--json]                         # check the store, data directory, bellhop and routes
callboard --version
```

`<ref>` is `@handle` (your direct chat with them), `group:<name>`, `mail:<id>` or a message id
`cb_…`. TEXT is read from stdin when omitted. A direct message rings the recipient; in a group
only an `@mention` of a member rings. Ringing itself arrives in a later version: for now each
receipt records the ping it will get.

A session holds one handle. Joining as another handle from the same session moves the session's
route to the new handle; the old handle keeps its messages but has no route, so nothing rings it
until it joins again. stderr names the handle that lost the route. Joining an existing handle from
another session rebinds it to that session.

`--as HANDLE` (before or after the command) or `$CALLBOARD_AS` acts as a handle explicitly; otherwise the
caller is the handle joined from the session `bellhop whoami` reports.

The `--json` contract and the error codes are in [docs/user/json.md](docs/user/json.md).

Messages are unauthenticated: everything runs as one local user and sender names are
self-asserted.

Data lives in `$XDG_DATA_HOME/callboard` (default `~/.local/share/callboard`).

## License

MIT
