import json
from collections.abc import Mapping, Sequence

from callboard.errors import CallboardError

SCHEMA_VERSION = 1


def ok_payload(fields: Mapping[str, object], warnings: Sequence[str] = ()) -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "status": "ok", "warnings": list(warnings), **fields}


def error_payload(error: CallboardError) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "error",
        "exit_code": error.exit_code,
        "error": {"code": error.code, "message": str(error)},
    }


def render(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False)
