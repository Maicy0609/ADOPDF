"""Minimal PDF writer for the S1/S2 spikes.

Only what the spikes need: objects, streams, xref, no external deps.
The production generator will grow its own writer; this one stays small
and is also used by the unit tests.
"""

from __future__ import annotations

import zlib


def esc(s: str) -> str:
    """Escape a PDF literal string (no newlines expected)."""
    return (s.replace("\\", "\\\\")
             .replace("(", "\\(")
             .replace(")", "\\)")
             .replace("\r", "\\r")
             .replace("\n", "\\n"))


def num(x: float) -> str:
    """Format a number for PDF operators; 3 decimals is enough for spikes."""
    if isinstance(x, int):
        return str(x)
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


class PDF:
    def __init__(self) -> None:
        self._objs: list[bytes | None] = [None]  # 1-based

    def reserve(self) -> int:
        self._objs.append(None)
        return len(self._objs) - 1

    def set(self, ref: int, body: bytes) -> None:
        if ref <= 0 or ref >= len(self._objs):
            raise ValueError(f"bad object ref {ref}")
        if self._objs[ref] is not None:
            raise ValueError(f"object {ref} already set")
        self._objs[ref] = body

    def add(self, body: bytes) -> int:
        ref = self.reserve()
        self.set(ref, body)
        return ref

    def add_stream(self, data: bytes, extra: str = "", compress: bool = False) -> int:
        if compress:
            data = zlib.compress(data, 9)
            extra += " /Filter /FlateDecode"
        body = f"<< /Length {len(data)}{extra} >>\nstream\n".encode() + data + b"\nendstream"
        return self.add(body)

    def build(self, root: int) -> bytes:
        out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0] * len(self._objs)
        for i in range(1, len(self._objs)):
            body = self._objs[i]
            if body is None:
                raise ValueError(f"object {i} was never set")
            offsets[i] = len(out)
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(self._objs)}\n".encode()
        out += b"0000000000 65535 f \n"
        for i in range(1, len(self._objs)):
            out += f"{offsets[i]:010d} 00000 n \n".encode()
        out += (f"trailer\n<< /Size {len(self._objs)} /Root {root} 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n").encode()
        return bytes(out)
