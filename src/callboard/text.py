CONTROL_ESCAPES = {code: f"\\x{code:02x}" for code in (*range(0x20), *range(0x7F, 0xA0))} | {
    ord("\n"): "\\n",
    ord("\r"): "\\r",
    ord("\t"): "\\t",
}


def one_line(text: str) -> str:
    return text.translate(CONTROL_ESCAPES)


def shortened(text: str, limit: int) -> str:
    flat = one_line(text)
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
