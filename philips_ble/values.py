"""Value displays for characteristics whose layout is only partly known."""

from __future__ import annotations


def interpret(kind: str, data: bytes) -> dict:
    shown = data.hex(" ")
    if kind == "utf8":
        text = data.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        return {"text": text, "hex": shown}
    if kind == "battery":
        body = {"hex": shown}
        if len(data) == 1:
            body["level"] = data[0]
            body["note"] = "One octet, the Bluetooth SIG Battery Level format."
        else:
            body["note"] = (
                "The Sonicare handler parses the battery bytes to an integer. "
                "The width of that integer is unresolved."
            )
            _add_le(body, data)
        return body
    if kind == "int":
        body = {
            "hex": shown,
            "note": "The app parses an integer here. Endianness is not in the manual.",
        }
        _add_le(body, data)
        return body
    return {"hex": shown}


def _add_le(body: dict, data: bytes) -> None:
    if len(data) in (1, 2, 4):
        body["unsigned_little_endian"] = int.from_bytes(data, "little")
        body["endian_note"] = "Little-endian display of these bytes. The manual does not record the endianness."
