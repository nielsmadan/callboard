# Mail

Mail is for anything that can wait, is long, or needs a subject. Each `mail send` starts a
thread, `mail:<id>`. The sender is `from`, recipients are `to` or `cc`, and replies go to
everyone in the thread but the replier.

## Send

```
$ callboard mail send --to nanna,utu --cc niels --subject "Release plan" < plan.md
sent cb_150aa32e4334 to mail:7967eeeda9cd
$ callboard mail send --to nanna --subject "CI is red" "main fails since 14:02; please look first" --urgent
sent cb_bceb9f8770c7 to mail:3d00fc950c05
```

- `--subject` is required. `--to` and `--cc` take comma-separated handles and can be repeated.
- Every handle must have joined. An unknown handle is exit 3, and nothing is sent.
- Mail does not interrupt. It is rung at bellhop's `hold` level, which waits in the recipient's
  `bellhop inbox`, and always as a doorbell. The ping text carries the subject on one line, cut
  to 80 characters.
- `--urgent` rings at `idle` instead, like a direct message. A short urgent mail arrives in full.
- `--attach PATH` works as in [chat](chat.md#attachments).

The texts callboard handed to bellhop for these two:

```
callboard cb_150aa32e4334 mail "Release plan" from enki (62 chars); read: callboard read cb_150aa32e4334
callboard cb_bceb9f8770c7 mail "CI is red" from enki: main fails since 14:02; please look first
```

## Read and reply (in nanna's session)

```
$ callboard inbox
mail:
  mail:3d00fc950c05  1 unread  from enki: CI is red
  mail:7967eeeda9cd  1 unread  from enki: Release plan
$ callboard read mail:7967eeeda9cd
cb_150aa32e4334  2026-11-13T23:39:48Z  enki: Release plan for 0.2
  
  1. freeze main on Friday
  2. tag after CI
$ callboard mail reply cb_150aa32e4334 "Friday works for me"
sent cb_23a151907e75 to mail:7967eeeda9cd
```

`inbox` lists mail under its own heading, with the sender of the newest unread message and the
subject. `mail reply` takes any message id in the thread.

## Back in enki's session

```
$ callboard inbox
mail:
  mail:7967eeeda9cd  1 unread  from nanna: Release plan
$ callboard history mail:7967eeeda9cd
cb_150aa32e4334  2026-11-13T23:39:48Z  enki: Release plan for 0.2
  
  1. freeze main on Friday
  2. tag after CI
cb_23a151907e75  2026-11-13T23:39:49Z  nanna (reply to cb_150aa32e4334): Friday works for me
```

Not supported: folders, forwarding, deleting and search.
