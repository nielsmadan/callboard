# Chat

Direct messages and group chats. Each pair of handles has one running direct conversation, and
each group one running conversation. For threads with a subject, see [mail](mail.md).

Examples below are from enki's session unless a heading says otherwise. Paths in the output are
printed in full; here your home directory is shown as `~`.

## Direct messages

```
$ callboard dm nanna "the parser change is in; can you rebase on main?"
sent cb_6874cb72357e to @nanna
$ callboard dm nanna "stop: main is broken, do not rebase" --now
sent cb_0e2273ddcd05 to @nanna
$ callboard dm nanna < handoff.md
sent cb_ec5a4723715e to @nanna
```

- A direct message rings the recipient at bellhop's `idle` level: it arrives when their current
  turn ends, and a stopped bellhop agent is woken for it.
- `--now` interrupts the recipient mid-turn. Use it only when waiting would do harm.
- `--no-ping` stores the message without ringing.
- Without TEXT, the text is read from stdin. An empty message is refused unless it has an
  attachment. A TEXT that starts with `-` goes after `--`: `callboard dm nanna -- "-x is gone"`.

## Reading (in nanna's session)

While bellhop has not yet confirmed the pings (here it reported them `pending`), they count as
unread:

```
$ callboard inbox
@enki  3 unread
$ callboard read @enki
cb_6874cb72357e  2026-11-13T23:39:28Z  enki: the parser change is in; can you rebase on main?
cb_0e2273ddcd05  2026-11-13T23:39:28Z  enki: stop: main is broken, do not rebase
cb_ec5a4723715e  2026-11-13T23:39:28Z  enki: Handoff: parser rewrite
  
  - tokenizer done
  - error recovery still open
$ callboard dm enki "rebased, tests pass" --reply-to cb_6874cb72357e
sent cb_7722d25347bb to @enki
```

- `inbox` lists conversations with unread messages: those that mention you first, then the most
  recent.
- `read <ref>` prints your unread messages in a conversation and marks them read. `--peek` leaves
  them unread. A message id reads just that message.
- A `<ref>` is `@handle` (your direct conversation with them), `group:<name>`, `mail:<id>` or a
  message id `cb_…`.
- `--reply-to` must name a message in the same conversation.
- Text output shows control characters, terminal escape sequences and text-direction controls
  in a message as escapes (`\x1b`, `\r`, `\u202e`); line breaks and tabs stay as they are.
  `--json` has the body unchanged.

A short message that bellhop confirmed it delivered in full is already read, so `inbox` and `read`
skip it; `history` shows it again. With bellhop answering `confirmed`:

```
$ callboard dm nanna "short note: CI is green again"
sent cb_fef715dc6300 to @nanna
```

In nanna's session:

```
$ callboard inbox
no unread messages
$ callboard history @enki --limit 1
cb_fef715dc6300  2026-11-14T00:29:43Z  enki: short note: CI is green again
```

`history` shows the latest messages whether read or not (`--limit`, default 20):

```
$ callboard history @nanna --limit 2
cb_ec5a4723715e  2026-11-13T23:39:28Z  enki: Handoff: parser rewrite
  
  - tokenizer done
  - error recovery still open
cb_7722d25347bb  2026-11-13T23:39:28Z  nanna (reply to cb_6874cb72357e): rebased, tests pass
```

## Groups

```
$ callboard group create release --members nanna,utu --project callboard
created group:release (members: enki, nanna, utu)
$ callboard group send release "@utu can you tag 0.2 once CI is green? nanna, fyi"
sent cb_3e12ecfa07cf to group:release (mentions @utu)
```

- The creator is always a member. `group add <name> <handle>` and `group remove <name> <handle>`
  change members; only members can do that, and only members can send or read. A group name is
  up to 64 lowercase letters, digits, `_` and `-`.
- When the last member leaves, the group and its messages are deleted and its name can be used
  again.
- A group created with `--open` can be joined by anyone who has joined callboard; `--members` is
  then optional. Every other group is closed: only a member can add someone.

```
$ callboard group create bellhop --open --project bellhop
created group:bellhop (open; members: enki)
```

In utu's session:

```
$ callboard group join bellhop
joined group:bellhop
$ callboard group join release
callboard: group:release is not open; ask a member to run: callboard group add release utu
$ callboard group join ghost
callboard: no conversation group:ghost
```

- `group join` exits 0 when you are in the group afterwards (also when you already were), 1 with
  `group_closed` for a closed group, and 3 with `conversation_not_found` when there is no such
  group. A group stays open or closed as it was created.
- Only an `@handle` of a member rings that member. Everyone else gets the message unread, without
  a ping. `--now` makes the mentions interrupt.

In utu's session:

```
$ callboard inbox
group:release  1 unread, 1 mention
$ callboard read group:release --peek
cb_3e12ecfa07cf  2026-11-13T23:39:29Z  enki: @utu can you tag 0.2 once CI is green? nanna, fyi
```

## Receipts

```
$ callboard receipts cb_3e12ecfa07cf
recipient  ping  state    read
nanna      none  -        -
utu        idle  pending  -
```

`ping` is the level the recipient was rung at, and `state` the bellhop state of that ping.
`receipts` and `inbox` first refresh recent pings with one `bellhop status` call.

## Attachments

```
$ callboard dm nanna "trace from the failing run" --attach trace.log
sent cb_6565cc6e5ff2 to @nanna
```

In nanna's session:

```
$ callboard read @enki
cb_6565cc6e5ff2  2026-11-13T23:39:29Z  enki: trace from the failing run
  attachment at_2f3c26afe74a  trace.log  text/plain  26 bytes  ~/.local/share/callboard/attachments/56ef480c531c12f003aac8bba2b020c557a22075363f2ada374fe2a1b699fac5
$ callboard attachment get at_2f3c26afe74a
~/.local/share/callboard/attachments/56ef480c531c12f003aac8bba2b020c557a22075363f2ada374fe2a1b699fac5
$ callboard attachment get at_2f3c26afe74a --out trace-copy.log
trace-copy.log
```

- `--attach PATH` is repeatable and works on `dm`, `group send`, `mail send` and `mail reply`.
- Each file is copied into the store, and the same content is stored once. The limit is 50 MiB
  per file; set `max_attachment_bytes` to change it.
- Stored files are read-only (mode 0400) and shared by every message with the same content; a
  send of content already stored puts back a stored file that was changed.
- `--out` never overwrites an existing file and writes the copy with mode 0600.
- `callboard doctor --prune` deletes stored files no message refers to, once they are an hour
  old.

## What the recipient sees

A short message (500 characters or less, no attachments) arrives in full. These are texts
callboard handed to `bellhop send` in a test run:

```
callboard cb_8a4e4c69fbe3 dm from enki: short note
```

Control characters in the message other than tab and newline show in the ping as escapes
(`\x1b`, `\x07`), as in `read`; the stored message is unchanged. Anything longer, or with
attachments, arrives as a doorbell:

```
callboard cb_c26523f1a44d dm from enki (600 chars); read: callboard read cb_c26523f1a44d
```

A short message counts as read once bellhop confirms it reached the session: at once when
`bellhop send` already reports it confirmed, otherwise when `inbox` or `receipts` refresh it,
which they do only for messages younger than 15 minutes. After that it stays unread until you
`read` it. A short message that woke a stopped agent counts as read the same way, once bellhop
finds it in the new session's transcript.

## When bellhop is missing or fails

The message is still stored and the command exits 0. Each routed recipient that could not be rung
adds a warning (here nanna is an agent with a route), and `doctor --reping`, run once bellhop is
back on `PATH`, rings again what was missed:

```
$ callboard --as enki dm nanna "are you there?"
callboard: ping nanna for cb_36790a564ee8: bellhop not found on PATH
sent cb_36790a564ee8 to @nanna
$ callboard doctor --reping
ok    data_dir  ~/.local/share/callboard
ok    store     schema version 3, 2 participants
ok    bellhop   ~/.local/bin/bellhop
ok    routes    2 routes resolve
ok    config    ~/.config/callboard/config.toml absent; using the defaults
re-rang 1 receipts
```

Without bellhop, callboard cannot ask which session you are in, so a command without `--as`
exits 1 with `bellhop not found on PATH`. Each command gives bellhop 20 seconds in total;
copying attachments and storing the message do not count against it. A bellhop call is never
given less than bellhop's own worst case for it (10 seconds, or 20 for a send that may start an
agent), so a call that starts late may run past the 20 seconds; no call starts once they are
spent. A ping's `--confirm` wait is what is left after bellhop's 10 seconds, up to 5.
