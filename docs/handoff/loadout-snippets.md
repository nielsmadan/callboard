# Loadout snippets

Proposed, not applied. These wire callboard into an agent setup managed by
[loadout](https://github.com/nielsmadan/loadout). Apply them by hand, then run
`loadout sync --global`.

## The skill

Loadout renders every directory in its skills catalog to each configured harness's skills
directory (for example `~/.claude/skills/<name>/`, `~/.factory/skills/<name>/`, and for Codex
`${CODEX_HOME:-~/.codex}/skills/<name>/` in the global preset). Add callboard's skill to the
catalog as a directory named `callboard`:

```sh
cp -R skills/callboard ~/ac/loadout/skills/callboard
```

Copy it again after callboard changes the skill. A symlink to the checkout keeps it current but
ties the catalog to that checkout.

To limit it to some harnesses, add to the loadout config:

```toml
[skills.callboard]
agents = ["claude", "codex", "pi"]
```

## Permissions

A harness checks the command the agent types. callboard's own `bellhop` subprocesses are not
checked, but agents also run `bellhop` directly, for example `bellhop inbox` to read held mail
pings, so allow both.

`[shell] default` in loadout's `permissions.toml` is the fallback for OpenCode and Pi only.
Claude Code's default mode and Codex's approval policy are their own settings, so for those an
explicit allow entry is what stops the prompt:

```toml
[shell]
allow = [
  "callboard",
  "bellhop",
]
```

Loadout writes `[shell]` entries to Claude Code's `permissions.allow`, Codex's
`permissions.rules`, OpenCode's `permission.bash` and Pi's permission file. Droid uses session
autonomy instead.

## Sandboxed profiles

callboard writes under `$XDG_DATA_HOME/callboard` (default `~/.local/share/callboard`), plus the
file `attachment get --out` names, and reads `$XDG_CONFIG_HOME/callboard/config.toml`. A sandbox profile that runs agents must allow
reading and writing the first and reading the second. bellhop's own needs are listed in bellhop's
hand-off notes.
