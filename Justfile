bellhop_commit := "14de6c2e38c2e132fa19b50a31d7abf4315edf63"
bellhop_repo := env("BELLHOP_REPO", justfile_directory() / "../../bellhop/dev1")

[private]
default:
    @just --list

setup:
    @uv sync --locked --all-groups
    @lefthook install

test:
    @uv run --locked pytest -q

coverage:
    @uv run --locked pytest --cov --cov-report=term-missing --cov-report=html --cov-report=xml -q

smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    repo="{{bellhop_repo}}"
    commit="{{bellhop_commit}}"
    if ! git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
        echo "just smoke: no bellhop git repo at $repo; set BELLHOP_REPO" >&2
        exit 1
    fi
    if ! git -C "$repo" cat-file -e "$commit^{commit}" 2>/dev/null; then
        echo "just smoke: bellhop commit $commit not found in $repo" >&2
        exit 1
    fi
    archive=".cache/bellhop-$commit"
    rm -rf "$archive"
    mkdir -p "$archive"
    git -C "$repo" archive "$commit" | tar -x -C "$archive"
    uv run --locked --with "./$archive" python -m pytest -m smoke -q

check-package:
    @uv run --locked pytest -m packaging -q

lint:
    @uv run --locked ruff check

format:
    @uv run --locked ruff format

typecheck:
    @uv run --locked mypy

check-static:
    @uv run --locked ruff check
    @uv run --locked ruff format --check
    @uv run --locked pylint src/callboard
    @uv run --locked mypy

check: check-static test

build:
    @rm -rf dist build
    @uv build --sdist
    @uv build --wheel dist/callboard-*.tar.gz

install:
    @uv tool install --reinstall --force .

install-editable:
    @uv tool install --reinstall --force --editable .

uninstall:
    @uv tool uninstall callboard

[positional-arguments]
app *args:
    @cd app && just "$@"

clean:
    @rm -rf dist build .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml
