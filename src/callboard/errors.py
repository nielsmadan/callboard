from collections.abc import Mapping

from callboard.codes import Code, exit_code_for


class CallboardError(Exception):
    def __init__(
        self, message: str, *, code: Code, extra: Mapping[str, object] | None = None
    ) -> None:
        super().__init__(message)
        self.code: Code = code
        self.exit_code = exit_code_for(code)
        self.extra = dict(extra or {})
