from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

type Code = Literal["internal_error", "interrupted", "usage"]

INTERNAL_ERROR: Code = "internal_error"
INTERRUPTED: Code = "interrupted"
USAGE: Code = "usage"

OK_EXIT = 0
FAILURE_EXIT = 1
USAGE_EXIT = 2
NOT_FOUND_EXIT = 3
NO_ROUTE_EXIT = 4
HLS_UNAVAILABLE_EXIT = 5
INTERRUPTED_EXIT = 130

EXIT_CODES: Mapping[Code, int] = MappingProxyType(
    {
        INTERNAL_ERROR: FAILURE_EXIT,
        INTERRUPTED: INTERRUPTED_EXIT,
        USAGE: USAGE_EXIT,
    }
)


def exit_code_for(code: Code) -> int:
    return EXIT_CODES[code]
