# AGENTS.md

This file is the canonical coding-agent guidance for callboard.

## Project

callboard is a Python 3.13 CLI for messaging between coding agents: direct chat, group chat, mail,
attachments, pings and read receipts. It keeps one SQLite store under `$XDG_DATA_HOME/callboard`
and rings recipients by running the `bellhop` CLI. `README.md` defines the public CLI contract;
the [documentation map](docs/overview.md) links the rest.

## Commands

```sh
just check      # ruff lint and format check, pylint cycle detection, strict mypy, pytest
just coverage   # the suite with branch coverage; fails under 80%
just smoke      # live tests against real agents from a bellhop archive (docs/tests/smoke.md)
```

`just check-static` is the lint, cycle and type pass without the suite. `just check-package`
builds the wheel and sdist and checks that the skill is bundled; it is deselected from the normal
suite. `just setup` installs
project dependencies and repository hooks; it does not install `callboard` globally.
`just release` cuts a release with curtains and `just changelog <version>` regenerates
`CHANGELOG.md`; [docs/release.md](docs/release.md) has the whole path from tag to Homebrew formula.
`scripts/release.py` is the release helper the policy and the workflow call; it is
standard-library only and covered by `tests/test_release.py`.

## Architecture

`tests/test_layering.py` machine-enforces the module dependency contract: layer order,
per-module import allowances, absolute internal imports, and a stdlib-only runtime. Internal
modules never import the package root. The CLI layer owns parsing, dispatch and presentation;
the store owns SQL; identity owns calls to `bellhop`. `observe` holds the read-only queries behind
`callboard admin`, each one read transaction over a connection from `store.open_readonly`.

Only SQL runs inside a write transaction: never a subprocess, a push or a file copy.

`trace` appends one JSON line per command (`cli/dispatch`) and per sent message (`cli/chat`) to
`trace.jsonl` in the data directory; `Runtime.trace` carries the emitter (`quiet` in tests) and an
emit never raises. `callboard log` reads it. What a ring did is in bellhop's trace.

## App

`app/` holds the macOS menu bar app, which only observes through `callboard admin ... --json`: the
`Callboard` target (windows, menu bar) and the `CallboardKit` package (everything testable).
Run it through `just app <recipe>` (`setup`, `check`, `build`, `demo`; `run` launches the app, so
leave that to the user). `just check` and `just coverage` never build it, but they compare the
kit's JSON fixtures with `tests/golden/` and run the demo script; `just app check` builds and
tests it. `just app demo` seeds a store under `app/build/demo-data` with `app/scripts/demo.py`,
which runs callboard with `HOME` and the three `XDG_*_HOME` folders inside the target. Details in
[docs/app.md](docs/app.md).

App conventions: the `Callboard` target builds in Swift 5 mode with complete strict concurrency
and MainActor default isolation; `CallboardKit` is Swift 6 with no default isolation. Logic that
can be tested goes in the kit, behind Swift Testing tests with a plain `import CallboardKit` and
fakes instead of processes; views stay thin and are only compile-checked. Use `@Observable`,
never `ObservableObject`, and keep `@AppStorage` keys in `AppStorageKeys`. Only `WindowManager`
changes the activation policy. `just app check` fails on any warning in our code and on unused
code (Periphery, with the kit scan including tests). A change to the admin JSON updates the
goldens in `tests/golden/`, which `tests/test_app_contract.py` pins to the kit's fixtures.

## Conventions

- Target Python 3.13, standard library only at runtime, Ruff at 100 columns, strict mypy over
  `src`, `tests` and `app/scripts`, at least 80% branch coverage.
- New behavior gets observable tests in the matching `tests/test_<module>.py` file.
- Tests never call a real `bellhop` or agent: `tests/fakes/bellhop` replays the JSON fixtures in
  `tests/contract/`.
- The agent skill lives in `skills/callboard/SKILL.md` and is bundled into the wheel as
  `callboard/_skills/`. Keep it under 150 lines.
- Every `$ callboard …` line in `README.md`, `docs/user/` and the skill must parse
  (`tests/test_docs.py`). Example output in the docs is pasted from real runs, never written by
  hand; a run against a temporary `HOME` and `tests/fakes/bellhop` is enough.
- New code normally needs no comments or docstrings. Use names and small typed functions.
- `--json` prints exactly one object on stdout; `admin watch` alone prints one object per line.
  Diagnostics go to stderr prefixed `callboard: `.
- Error messages in git style: lowercase, no trailing period, clauses joined with `;`.
- Exit codes: 0 ok, 1 failure, 2 usage, 3 not found or ambiguous, 4 no usable route (reserved;
  never returned), 5 hls unavailable, 130 interrupted.

Never run `just release`, tag, publish, or install a global command unless the user asks.
