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
    @uv run --locked pytest -m smoke -q

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

clean:
    @rm -rf dist build .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml
