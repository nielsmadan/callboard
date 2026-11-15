import re
from collections.abc import Collection

MENTION = re.compile(r"(?<![\w.@+-])@([a-z0-9][a-z0-9_-]*)")


def mentioned(body: str, members: Collection[str], sender: str) -> tuple[str, ...]:
    found = dict.fromkeys(match.group(1) for match in MENTION.finditer(body))
    return tuple(handle for handle in found if handle in members and handle != sender)
