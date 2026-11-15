FORMAT_CONTROLS = (*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x2028, 0x2029)
CONTROL_ESCAPES = (
    {code: f"\\x{code:02x}" for code in (*range(0x20), *range(0x7F, 0xA0))}
    | {code: f"\\u{code:04x}" for code in FORMAT_CONTROLS}
    | {ord("\n"): "\\n", ord("\r"): "\\r", ord("\t"): "\\t"}
)
KEPT = frozenset({ord("\n"), ord("\t")})
VISIBLE_ESCAPES = {code: escape for code, escape in CONTROL_ESCAPES.items() if code not in KEPT}


def one_line(text: str) -> str:
    return text.translate(CONTROL_ESCAPES)


def visible(text: str) -> str:
    return text.translate(VISIBLE_ESCAPES)


def shortened(text: str, limit: int) -> str:
    flat = one_line(text)
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
