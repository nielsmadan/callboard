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
just smoke      # live tests against real agents (marked smoke, deselected by default)
```

`just check-static` is the lint, cycle and type pass without the suite. `just setup` installs
project dependencies and repository hooks; it does not install `callboard` globally.

## Architecture

`tests/test_layering.py` machine-enforces the module dependency contract: layer order,
per-module import allowances, absolute internal imports, and a stdlib-only runtime. Internal
modules never import the package root. The CLI layer owns parsing, dispatch and presentation;
the store owns SQL; identity owns calls to `bellhop`.

Only SQL runs inside a write transaction: never a subprocess, a push or a file copy.

## Conventions

- Target Python 3.13, standard library only at runtime, Ruff at 100 columns, strict mypy over
  `src` and `tests`, at least 80% branch coverage.
- New behavior gets observable tests in the matching `tests/test_<module>.py` file.
- Tests never call a real `bellhop` or agent: `tests/fakes/bellhop` replays the JSON fixtures in
  `tests/contract/`.
- New code normally needs no comments or docstrings. Use names and small typed functions.
- `--json` prints exactly one object on stdout. Diagnostics go to stderr prefixed `callboard: `.
- Error messages in git style: lowercase, no trailing period, clauses joined with `;`.
- Exit codes: 0 ok, 1 failure, 2 usage, 3 not found or ambiguous, 4 no usable route, 5 hls
  unavailable, 130 interrupted.

Never run `just release`, tag, publish, or install a global command unless the user asks.
