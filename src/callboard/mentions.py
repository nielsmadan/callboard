import re
from collections.abc import Collection

MENTION = re.compile(r"(?<![\w.@+-])@([a-z0-9][a-z0-9_-]*+)(?![\w@])")


def _member(captured: str, members: Collection[str]) -> str | None:
    return next((handle for handle in (captured, captured.rstrip("_-")) if handle in members), None)


def mentioned(body: str, members: Collection[str], sender: str) -> tuple[str, ...]:
    found = (_member(match.group(1), members) for match in MENTION.finditer(body))
    unique = dict.fromkeys(handle for handle in found if handle is not None)
    return tuple(handle for handle in unique if handle != sender)
