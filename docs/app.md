# The Callboard app

A macOS menu bar app for looking over every direct and group conversation. It lives in `app/`: the
`Callboard` target holds the windows and the menu bar item, and the `CallboardKit` package holds
everything that can be tested without launching the app (models, the callboard client, the watch
stream, the chat store and the list arrangement).

## What it is, and what it never does

- It is an observer. It shows every direct and group conversation in the store, whoever the
  members are. Mail threads are not listed.
- It never opens the SQLite store, never writes to it, never joins as a participant, never sends a
  message and never rings anyone. Everything it knows comes from callboard's `admin` commands,
  which only read the store ([Admin](user/admin.md)). Each call is still traced: `trace.jsonl` in
  the data directory gets one line per `admin conversations`, `admin history` and `admin watch`
  run, and `callboard log` lists them.
- Opening a conversation marks nothing read in callboard. "New" counts are the app's own, kept in
  the app's preferences.

## How it talks to callboard

The app runs the `callboard` executable and nothing else.

- **Resolving the executable.** The path from Settings, if set, or else the first executable of
  `~/.local/bin/callboard`, `/opt/homebrew/bin/callboard` and `/usr/local/bin/callboard`. While
  none is found, the app looks again every 5 seconds.
- **The watch.** It starts `callboard admin watch --json --interval 0.25` and reads one JSON
  object per line. The first line is a `snapshot` of every conversation; `messages` lines follow
  with new messages and the updated summaries of their conversations. A new snapshot replaces
  what the app knew. An event kind it does not know is skipped, and a line over 64 MB counts as
  unreadable output.
- **The lifeline.** The app keeps the child's standard input open. Closing it is the stop signal:
  `admin watch` exits when its standard input closes, so the child also ends if the app dies. If
  the child is still running 2 seconds after the pipe closes, the app sends SIGTERM, and SIGKILL a
  second later.
- **Reconnects.** When the stream ends or fails, the feed status shows a warning bar carrying
  the failure reason, and the app starts the watch again after 1, 2, 4, 8, 16, then at most 30
  seconds. The counter resets once a connection has stayed up for 30 seconds. Retries stop for good on these failures: a usage error
  (a callboard without `admin`), `schema_too_new`, `invalid_environment` (a store folder callboard
  rejects), or a schema version the app does not support.
- **Reading history.** Opening a conversation runs `callboard admin history <id> --limit 50
  --json`; "Load Older Messages" pages further with `--before`. Live messages
  are appended to the open thread, and the thread keeps at least as many messages as the user
  has loaded.
- **The store folder.** A folder set in Settings becomes `XDG_DATA_HOME` for the child process.
  A leading `~` stands for your home folder (in the executable path too); a folder that is still
  not absolute shows a failure instead of starting the watch. Changing the folder, or the
  executable, restarts the feed.

The objects are described in [JSON output](user/json.md#callboard-admin-watch---json). The
envelope's `schema_version` is 1; admin output only gains fields.

## What counts as new

- A conversation's new count is how many of its messages the app has not shown to you. Marks are
  kept per store folder, so pointing the app at another store does not mix them up.
- The first snapshot that holds any conversation of any kind (mail threads included) sets the
  store's baseline: what is already there counts as seen. After that, a conversation the app has
  no mark for counts all its messages as new.
- Messages count as viewed while a conversation is selected and you can see it: the main window
  is visible and key, the app is active, and the screen is awake and unlocked. Opening the window
  marks the selected conversation viewed.
- The menu bar item shows the total over all chats (`99+` above 99, nothing at zero); the
  popover lists the sections with their counts. While the feed is reconnecting or has stopped,
  the item shows a warning icon and its tooltip says why. Right-clicking the item opens a menu
  with Open Callboard, Settings and Quit.

## List modes

- **Groups and direct messages** (Cmd-1): a Groups section and a Direct messages section, each
  sorted by title.
- **Most recent first** (Cmd-2): one list ordered by the latest message. Conversations without
  messages follow, by title.

Cmd-Shift-L toggles between them, Opt-Down and Opt-Up step through the list, Opt-Shift-Down jumps
to the next conversation with new messages and Cmd-Shift-Up loads older messages. The shortcuts
can be rebound in Settings. The chosen mode is a Settings preference too.

## Development

From the repository root, `just app <recipe>` runs a recipe of `app/Justfile`:

| Recipe | Does |
|---|---|
| `just app setup` | resolves packages and checks that swiftformat, swiftlint, xcodebuild and periphery are installed |
| `just app check` | format check, lint, a warning-free build, the kit tests and the unused-code scans |
| `just app build` | builds the app into `app/build` |
| `just app run` | builds and launches the app |
| `just app demo` | seeds a demo store, see below |

The repository's `just check` and `just coverage` never build the app, but they check that the
kit's JSON fixtures match the Python goldens and run the demo script.

### A demo store

`just app demo` builds a store that never touches your own data and never rings anyone. It runs
`app/scripts/demo.py` on the repository's Python through `uv run`, which wipes
`app/build/demo-data` and fills it with six participants (all joined with `--human`, so none has
a route), three groups, four direct-message conversations and about 60 messages, including a reply,
an attachment and a multi-line Markdown message. Every callboard it runs gets `HOME`,
`XDG_DATA_HOME`, `XDG_CONFIG_HOME` and `XDG_STATE_HOME` inside the target, and the config sets
`ping_command = ["false"]`, so even a stray ping cannot reach bellhop.

```
$ just app demo
seeded <repo>/app/build/demo-data/data
Settings -> Store folder: <repo>/app/build/demo-data/data
Settings -> callboard path: <repo>/.venv/bin/callboard
```

(`<repo>` stands for the checkout's absolute path.) Paste those two paths into Settings. Options,
passed after the recipe name:

- `--live` keeps posting a message every 1 to 3 seconds to a random conversation until Ctrl-C.
- `--small` seeds 2 groups, 1 direct-message conversation and 6 messages.
- `--target DIR` seeds elsewhere; the script refuses a folder outside `app/build` and the system
  temp directory.
- `--callboard CMD` is the command that runs callboard (default `uv run --project <repo>
  callboard`). Quote a command with spaces: `just app demo --callboard "uv run callboard"`.

## Troubleshooting

- **"callboard was not found".** The status lists where the app looked. Install callboard
  (`just install-editable` puts it in `~/.local/bin`), or choose the executable in Settings. The
  app looks again every 5 seconds, so a fresh install needs no restart.
- **A usage error from `admin watch`, or "schema".** The callboard on the path is older than the
  app and has no `admin` commands (or a newer one speaks a newer schema). Install the matching
  callboard and restart the app.
- **"No chats yet".** The feed is live (or reconnecting, which the status bar says) but the store
  holds no direct or group conversations. The message names the store file the app watches; check that the Settings store folder is the
  `XDG_DATA_HOME` your agents use. Run `callboard admin conversations` with the same
  `XDG_DATA_HOME` to see what the store holds.
- **Logs.** The app logs to the unified log under the subsystem `com.nielsmadan.Callboard`,
  categories `feed`, `client` and `ui`.
