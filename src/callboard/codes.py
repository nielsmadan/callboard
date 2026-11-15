from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

type Code = Literal[
    "attachment_missing",
    "attachment_not_found",
    "bellhop_failed",
    "conversation_not_found",
    "doctor_failed",
    "group_exists",
    "hls_unavailable",
    "identity_ambiguous",
    "identity_not_found",
    "internal_error",
    "interrupted",
    "invalid_config",
    "invalid_environment",
    "message_not_found",
    "not_a_member",
    "not_in_session",
    "schema_too_new",
    "store_unavailable",
    "unknown_handle",
    "usage",
]

ATTACHMENT_NOT_FOUND: Code = "attachment_not_found"
ATTACHMENT_MISSING: Code = "attachment_missing"
INVALID_CONFIG: Code = "invalid_config"
BELLHOP_FAILED: Code = "bellhop_failed"
DOCTOR_FAILED: Code = "doctor_failed"
HLS_UNAVAILABLE: Code = "hls_unavailable"
IDENTITY_AMBIGUOUS: Code = "identity_ambiguous"
IDENTITY_NOT_FOUND: Code = "identity_not_found"
CONVERSATION_NOT_FOUND: Code = "conversation_not_found"
GROUP_EXISTS: Code = "group_exists"
MESSAGE_NOT_FOUND: Code = "message_not_found"
NOT_A_MEMBER: Code = "not_a_member"
INTERNAL_ERROR: Code = "internal_error"
INTERRUPTED: Code = "interrupted"
INVALID_ENVIRONMENT: Code = "invalid_environment"
NOT_IN_SESSION: Code = "not_in_session"
SCHEMA_TOO_NEW: Code = "schema_too_new"
STORE_UNAVAILABLE: Code = "store_unavailable"
UNKNOWN_HANDLE: Code = "unknown_handle"
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
        ATTACHMENT_NOT_FOUND: NOT_FOUND_EXIT,
        ATTACHMENT_MISSING: FAILURE_EXIT,
        INVALID_CONFIG: USAGE_EXIT,
        BELLHOP_FAILED: FAILURE_EXIT,
        DOCTOR_FAILED: FAILURE_EXIT,
        HLS_UNAVAILABLE: HLS_UNAVAILABLE_EXIT,
        IDENTITY_AMBIGUOUS: NOT_FOUND_EXIT,
        IDENTITY_NOT_FOUND: NOT_FOUND_EXIT,
        CONVERSATION_NOT_FOUND: NOT_FOUND_EXIT,
        GROUP_EXISTS: FAILURE_EXIT,
        MESSAGE_NOT_FOUND: NOT_FOUND_EXIT,
        NOT_A_MEMBER: NOT_FOUND_EXIT,
        INTERNAL_ERROR: FAILURE_EXIT,
        INTERRUPTED: INTERRUPTED_EXIT,
        INVALID_ENVIRONMENT: FAILURE_EXIT,
        NOT_IN_SESSION: NOT_FOUND_EXIT,
        SCHEMA_TOO_NEW: FAILURE_EXIT,
        STORE_UNAVAILABLE: FAILURE_EXIT,
        UNKNOWN_HANDLE: NOT_FOUND_EXIT,
        USAGE: USAGE_EXIT,
    }
)


def exit_code_for(code: Code) -> int:
    return EXIT_CODES[code]
