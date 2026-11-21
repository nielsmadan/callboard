import argparse
import hashlib
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORMULA_TEMPLATE = Path(__file__).with_name("formula.rb.in")
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
VERSION_LINE = re.compile(r"(?m)^[ \t]*version[ \t]*=[ \t]*([\"'])([^\r\n]*?)\1[ \t]*(?:#.*)?$")
FORMULA_URL = re.compile(
    r'^  url "https://github\.com/nielsmadan/[a-z]+/archive/refs/tags/v([^"/]+)\.tar\.gz"$',
    re.MULTILINE,
)

type Version = tuple[int, int, int]


class ReleaseError(Exception):
    pass


def parsed(version: str) -> Version:
    match = VERSION.fullmatch(version)
    if match is None:
        raise ReleaseError(f"expected a canonical MAJOR.MINOR.PATCH version, not {version!r}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def project(manifest: Path) -> dict[str, object]:
    found = tomllib.loads(manifest.read_text(encoding="utf-8")).get("project")
    if not isinstance(found, dict):
        raise ReleaseError(f"{manifest} has no [project] table")
    return found


def with_version(source: str, version: str) -> str:
    parsed(version)
    matches = tuple(VERSION_LINE.finditer(source))
    current = tomllib.loads(source).get("project", {}).get("version")
    if len(matches) != 1 or matches[0][2] != current:
        raise ReleaseError("expected exactly one manifest version, in [project]")
    start, end = matches[0].span(2)
    return source[:start] + version + source[end:]


def tagged_version(tag: str, manifest: Path) -> str:
    version = tag.removeprefix("v")
    if tag == version:
        raise ReleaseError(f"release tag {tag!r} does not start with v")
    parsed(version)
    found = project(manifest).get("version")
    if found != version:
        raise ReleaseError(f"tag version {version!r} does not match project version {found!r}")
    return version


def rendered(template: str, version: str, sha256: str) -> str:
    parsed(version)
    if re.fullmatch(r"[a-f0-9]{64}", sha256) is None:
        raise ReleaseError("expected a SHA-256 digest for the source archive")
    return template.replace("@VERSION@", version).replace("@SHA256@", sha256)


def formula_version(content: str) -> Version:
    versions = FORMULA_URL.findall(content)
    if len(versions) != 1:
        raise ReleaseError("the formula does not name exactly one release archive")
    return parsed(versions[0])


def newer_published(formula: str, published: str | None) -> bool:
    return published is not None and formula_version(published) > formula_version(formula)


def prepare(args: argparse.Namespace) -> None:
    manifest = ROOT / "pyproject.toml"
    manifest.write_text(
        with_version(manifest.read_text(encoding="utf-8"), args.version), encoding="utf-8"
    )


def project_metadata(args: argparse.Namespace) -> None:
    print(f"version={tagged_version(args.tag, args.manifest)}")


def formula(args: argparse.Namespace) -> None:
    version = args.tag.removeprefix("v")
    digest = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    template = FORMULA_TEMPLATE.read_text(encoding="utf-8")
    args.output.write_text(rendered(template, version, digest), encoding="utf-8")


def publish_formula(args: argparse.Namespace) -> None:
    content = args.formula.read_text(encoding="utf-8")
    target: Path = args.tap_formula
    published = target.read_text(encoding="utf-8") if target.exists() else None
    if newer_published(content, published):
        print("skipped-newer")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    print("updated")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Prepare and publish a release.")
    commands = root.add_subparsers(dest="command", required=True)
    version = commands.add_parser("prepare", help="set the pyproject version")
    version.add_argument("version")
    version.set_defaults(run=prepare)
    metadata = commands.add_parser("project-metadata", help="check a tag against a manifest")
    metadata.add_argument("tag")
    metadata.add_argument("manifest", type=Path)
    metadata.set_defaults(run=project_metadata)
    render = commands.add_parser("formula", help="render the Homebrew formula for a tag")
    render.add_argument("tag")
    render.add_argument("archive", type=Path)
    render.add_argument("output", type=Path)
    render.set_defaults(run=formula)
    publish = commands.add_parser(
        "publish-formula", help="copy a formula into a tap unless the tap holds a newer release"
    )
    publish.add_argument("formula", type=Path)
    publish.add_argument("tap_formula", type=Path)
    publish.set_defaults(run=publish_formula)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        args.run(args)
    except (ReleaseError, OSError, ValueError) as error:
        print(f"release: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
