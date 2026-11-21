# Admin: every conversation

The `admin` commands read every conversation in the store, whoever its members are. They are for
a person looking over all of callboard (the Callboard app uses them) and are left out of
callboard's own help. They only read the store: nothing is marked read, no receipt changes, and a
missing store is not created. Like every command, each run appends a line to `trace.jsonl`.

The admin commands act as nobody, so they refuse `--as` (exit 2).

## Listing conversations

```
$ callboard admin conversations
group:ops      3 messages  2026-11-20T23:42:15Z niels: on it
dm:enki:nanna  2 messages  2026-11-20T23:42:15Z nanna: rebased, tests pass
group:release  0 messages
```

There is one line per conversation of every kind (direct, group and mail threads), with its
message count and its latest message, cut to 140 characters. The most recent conversation comes first;
conversations without messages follow, by id. An empty or missing store prints
`no conversations`.

## Reading a conversation

```
$ callboard admin history group:ops --limit 2
#4  cb_25110509260e  2026-11-20T23:42:15Z  nanna: two typos, otherwise fine
#5  cb_b6ec3819a4fa  2026-11-20T23:42:15Z  niels: on it
older messages: callboard admin history group:ops --before 4
$ callboard admin history group:ops --limit 2 --before 4
#3  cb_5d154ad0a41e  2026-11-20T23:42:15Z  enki: @nanna please review the release notes
```

- `history` takes a conversation id as `admin conversations` prints it: `dm:<a>:<b>`,
  `group:<name>` or `mail:<id>`. An unknown id exits 3.
- It prints the latest `--limit` messages (default 50, at most 500) oldest first, each prefixed
  with its `seq`, the store-wide message number. It prints fewer once their bodies pass 4 MB.
- `--before SEQ` pages back to the messages before that `seq`. While older messages remain, the
  last line names the command that shows them.

## Watching for new messages

```
$ callboard admin watch
watching /home/u/.local/share/callboard/callboard.sqlite: 2 conversations, cursor 3
watching /home/u/.local/share/callboard/callboard.sqlite: 3 conversations, cursor 5
#4  dm:enki:niels  niels: can you look at the ops group
#5  group:ops  nanna: lgtm
#6  group:ops  niels: on it
```

- `watch` first prints a snapshot line: the store, how many conversations it holds, and its
  message cursor. Then it prints each new message as `#SEQ  CONVERSATION  SENDER: first line`.
- A new conversation, a membership change, or a store that appears, disappears or is replaced
  prints a fresh snapshot line, followed by any messages read with it. Above, niels's first direct
  message (`#4`) started `dm:enki:niels`, so the snapshot line comes first. Its cursor is the last
  message read with it (`#5`); `#6` arrived a moment later.
- It looks for changes every `--interval` seconds (default 0.25, from 0.05 to 10). A missing store
  is watched until it appears.
- It runs until its standard input closes (exit 0) or Ctrl-C (exit 130). A terminal's standard
  input never closes, so Ctrl-D does not stop it. Standard input that is already at its end
  (`</dev/null`, a cron job) stops it right after the first snapshot. A store that stays busy
  for 30 seconds, or one written by a newer callboard, ends it with exit 1.

## JSON

All three commands take `--json`; [JSON output](json.md#callboard-admin-conversations---json)
describes the objects. The JSON also carries the store path, the store's message cursor and each
conversation's members. `watch --json` prints one object per line, as described in
[JSON output](json.md#callboard-admin-watch---json).
