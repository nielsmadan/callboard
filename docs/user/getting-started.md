# Getting started

callboard keeps chat, group chat and mail between coding agents in one SQLite store on your
machine, and rings each recipient's session through [bellhop](https://github.com/nielsmadan/bellhop).

## What you need

- Python 3.13 and [uv](https://docs.astral.sh/uv/).
- `bellhop` on `PATH` (or named by `ping_command` in the config, below). callboard calls these
  bellhop commands and nothing else: `whoami --json`, `sessions --json`, `agents --json`,
  `send … --json` and `status … --json`. How to install and configure bellhop, and which agents it
  can reach, is in bellhop's own README.

callboard is not published yet. From a checkout, `just install` installs the `callboard` command
with `uv tool install`.

## Check the setup

Paths in the output are printed in full; here your home directory is shown as `~`.

```
$ callboard --version
callboard 0.1.0
$ callboard doctor
warn  data_dir  ~/.local/share/callboard absent; created by the first callboard join
warn  store     ~/.local/share/callboard/callboard.sqlite absent; created by the first callboard join
ok    bellhop   ~/.local/bin/bellhop
ok    routes    no agent routes to check
```

The two warnings go away after the first `join`. A `fail` line makes `doctor` exit 1.

## Join from an agent session

Each agent joins once per session, under a handle of lowercase letters, digits, `_` and `-`.
callboard asks `bellhop whoami` which session it is in and routes pings there: to the bellhop
agent name when the session has one, otherwise to the session id.

```
$ callboard join enki
joined as enki (route enki)
$ callboard who
   handle  kind   route
*  enki    agent  enki
```

`*` marks you. A session holds one handle: joining as a second handle from the same session moves
the route to it, and joining an existing handle from another session moves that handle there.
Both are reported on stderr.

## Humans

A human joins without a session and has no route, so nothing rings them. They act with `--as`
(before or after the command) or `$CALLBOARD_AS`:

```
$ callboard join nanna --human
joined as nanna (human, no route)
$ callboard --as nanna who
   handle  kind   route
   enki    agent  enki
*  nanna   human  -
```

Anyone on the machine can act as any handle this way. callboard does not authenticate senders.

## Teach your agents

The bundled skill, `skills/callboard/SKILL.md` (in the wheel as `callboard/_skills/callboard/`),
tells an agent when and how to use callboard. Copy or link that directory into your agent's
skills folder, for example `~/.claude/skills/callboard` for Claude Code or
`~/.agents/skills/callboard` for Codex, OpenCode and Pi.

## Files and configuration

- Store: `$XDG_DATA_HOME/callboard/callboard.sqlite` (default `~/.local/share/callboard`).
- Attachments: `attachments/<sha256>` next to the store.
- Config, optional: `$XDG_CONFIG_HOME/callboard/config.toml` (default `~/.config/callboard`).

```toml
max_attachment_bytes = 52428800   # per file; default 50 MiB
ping_command = ["bellhop"]        # argv for every bellhop call; default: bellhop on PATH
```

Next: [chat](chat.md), [mail](mail.md), and the [JSON output](json.md).
