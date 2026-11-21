import argparse
import json
import os
import random
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

MARKER = ".callboard-demo"
REPO = Path(__file__).resolve().parents[2]
BUILD = REPO / "app" / "build"
DEFAULT_CALLBOARD = f"uv run --project {shlex.quote(str(REPO))} callboard"
PEOPLE = ("niels", "enki", "nanna", "ishtar", "utu", "marduk")
GROUPS = {
    "ops": ("niels", "enki", "nanna"),
    "release": ("niels", "nanna", "ishtar", "utu"),
    "design": ("enki", "ishtar", "marduk"),
}
DMS = (("enki", "niels"), ("enki", "nanna"), ("ishtar", "niels"), ("utu", "marduk"))
LINES = (
    "the parser change is in; can you rebase on main?",
    "rebased, tests pass",
    "two typos, otherwise fine",
    "on it",
    "can you look at the ops group",
    "lgtm",
    "the build is green again",
    "I will take the flaky test",
    "release notes are drafted",
    "holding the tag until the docs land",
    "pushed a fix for the migration",
    "can someone check the contract fixtures?",
    "done, see the last commit",
    "the new layout looks good on my side",
    "taking lunch, back in 30",
)
MARKDOWN = """Status of the release:

- **parser**: merged
- *docs*: in review
- `just check`: green

Next: tag after the docs land."""


@dataclass(frozen=True)
class Post:
    sender: str
    args: tuple[str, ...]
    text: str


def inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def check_target(target: Path, temp_root: Path, home: Path) -> Path:
    resolved = target.resolve()
    roots = [BUILD.resolve()]
    if temp_root.resolve() != home.resolve():
        roots.append(temp_root.resolve())
    if not any(inside(resolved, root) for root in roots):
        raise SystemExit(f"demo: refusing target {resolved}; use app/build or a temp dir")
    if resolved in roots:
        raise SystemExit(f"demo: refusing target {resolved}; name a folder inside it")
    if (
        resolved.exists()
        and not (resolved / MARKER).exists()
        and (not resolved.is_dir() or any(resolved.iterdir()))
    ):
        raise SystemExit(f"demo: refusing to wipe {resolved}; it is not a demo store")
    return resolved


def wipe(target: Path) -> None:
    try:
        shutil.rmtree(target)
    except FileNotFoundError:
        pass
    except OSError as error:
        raise SystemExit(f"demo: cannot wipe {target}: {error}") from error


def child_env(target: Path, base: Mapping[str, str]) -> dict[str, str]:
    env = {name: value for name, value in base.items() if not name.startswith("CALLBOARD_")}
    env.update(
        HOME=str(target),
        XDG_DATA_HOME=str(target / "data"),
        XDG_CONFIG_HOME=str(target / "config"),
        XDG_STATE_HOME=str(target / "state"),
    )
    return env


def conversations(small: bool) -> tuple[list[tuple[str, tuple[str, ...]]], list[tuple[str, str]]]:
    groups = list(GROUPS.items())
    dms = list(DMS)
    return (groups[:2], dms[:1]) if small else (groups, dms)


def script(small: bool, rng: random.Random) -> list[Post]:
    groups, dms = conversations(small)
    targets = [(("group", "send", name), members) for name, members in groups] + [
        (("dm", to), (sender, to)) for sender, to in dms
    ]
    count = 6 if small else 60
    posts = []
    for index in range(count):
        route, members = targets[index % len(targets)]
        sender = rng.choice(members)
        if route[0] == "dm":
            route = ("dm", next(m for m in members if m != sender))
        posts.append(Post(sender, route, rng.choice(LINES)))
    return posts


class Callboard:
    def __init__(self, command: Sequence[str], env: Mapping[str, str]) -> None:
        self.command = list(command)
        self.env = dict(env)

    def run(self, *args: str, sender: str | None = None) -> dict[str, object]:
        argv = [*self.command, *args, "--json", *(["--as", sender] if sender else [])]
        try:
            done = subprocess.run(
                argv, env=self.env, capture_output=True, text=True, timeout=60, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SystemExit(f"demo: cannot run {shlex.join(argv)}: {error}") from error
        if done.returncode != 0:
            detail = done.stderr.strip() or done.stdout.strip()
            raise SystemExit(f"demo: {shlex.join(argv)} failed: {detail}")
        try:
            result: dict[str, object] = json.loads(done.stdout)
        except json.JSONDecodeError as error:
            raise SystemExit(f"demo: {shlex.join(argv)} printed no JSON: {error}") from error
        return result

    def send(self, post: Post, *extra: str) -> str:
        message = self.run(*post.args, post.text, *extra, sender=post.sender)["message"]
        return str(message["id"]) if isinstance(message, dict) else ""


def seed(cb: Callboard, target: Path, small: bool, rng: random.Random) -> None:
    for person in PEOPLE:
        cb.run("join", person, "--human")
    groups, _ = conversations(small)
    for name, members in groups:
        cb.run("group", "create", name, "--members", ",".join(members), sender=members[0])
    posts = script(small, rng)
    first, *rest = posts
    first_id = cb.send(first)
    for post in rest:
        cb.send(post)
    if not small:
        notes = target / "release-notes.txt"
        notes.write_text("callboard 0.1\n- the admin commands\n- the app\n", encoding="utf-8")
        cb.send(Post(first.sender, first.args, "release notes attached"), "--attach", str(notes))
        cb.send(Post(first.sender, first.args, MARKDOWN))
        cb.send(Post(first.sender, first.args, "that fixed it"), "--reply-to", first_id)


def live(cb: Callboard, small: bool, rng: random.Random) -> None:
    pool = script(small, rng)
    while True:
        template = rng.choice(pool)
        cb.send(Post(template.sender, template.args, rng.choice(LINES)))
        time.sleep(rng.uniform(1, 3))


def callboard_path(command: str) -> str:
    default = REPO / ".venv" / "bin" / "callboard"
    if command == DEFAULT_CALLBOARD:
        return str(default) if default.exists() else f"{default} (missing; run just setup)"
    return command


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed a demo callboard store for the app.")
    parser.add_argument("--live", action="store_true", help="keep posting until Ctrl-C")
    parser.add_argument("--target", type=Path, default=BUILD / "demo-data")
    parser.add_argument(
        "--callboard",
        default=DEFAULT_CALLBOARD,
        help="command that runs callboard",
    )
    parser.add_argument("--small", action="store_true", help="2 groups, 1 dm and 6 messages")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    target = check_target(args.target, Path(tempfile.gettempdir()), Path.home())
    try:
        command = shlex.split(args.callboard)
    except ValueError as error:
        raise SystemExit(f"demo: cannot read --callboard {args.callboard}: {error}") from error
    wipe(target)
    (target / "data").mkdir(parents=True)
    (target / MARKER).write_text("seeded by app/scripts/demo.py\n", encoding="utf-8")
    (target / "config" / "callboard").mkdir(parents=True)
    (target / "config" / "callboard" / "config.toml").write_text(
        'ping_command = ["false"]\n', encoding="utf-8"
    )
    cb = Callboard(command, child_env(target, os.environ))
    rng = random.Random(7)  # noqa: S311
    seed(cb, target, args.small, rng)
    print(f"seeded {target / 'data'}")
    print(f"Settings -> Store folder: {target / 'data'}")
    print(f"Settings -> callboard path: {callboard_path(args.callboard)}")
    if args.live:
        print("posting every 1-3 s; Ctrl-C to stop", flush=True)
        try:
            live(cb, args.small, rng)
        except KeyboardInterrupt:
            print("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
