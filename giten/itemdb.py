"""The item / equipment / gem database ``et/ET0001.BIN``.

Layout of the container body (``docs/format-notes.md`` section 6)::

    +0x0000  u16 count            = 745
    +0x0002  u16 offset[count]    byte offsets into the body, monotonic
             records              variable length, reached only through the table

A record is ``header || name \\0 || description \\0``.  The header length is
**not** constant: byte 4 of the record is a *type* tag, and the decoder
``0x00422D40`` switches on it through the jump table at ``0x00423180``, each
case consuming a different number of bytes before the common tail at
``0x00423112`` takes the pointer it is left with as the name.

:data:`HEADER_LEN` is that consumption, derived by walking each of the 19 cases
and counting the pointer advance (``inc``, plus the fixed consumption of the
field-copier helpers ``0x4231D0``/``0x423240``/``0x423270``/``0x423290`` and the
flag-driven ``0x423200``).  It was cross-checked against the data: for every
type, the derived length is in the set of lengths that make *every* record of
that type tile exactly as ``header + name\\0 + desc\\0`` with no control bytes
inside either string -- and it is the smallest such length in every case.

Records this module cannot split (type 0, and anything that fails to tile) are
carried verbatim as :attr:`Record.raw` with ``name is None``; they round-trip
byte-exactly but are not translatable.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

#: record type (byte 4) -> bytes from the record start to the name
HEADER_LEN = {
    1: 21, 2: 13, 3: 16, 4: 23, 5: 17, 6: 13, 7: 13, 8: 12, 9: 29, 10: 12,
    11: 32, 12: 23, 13: 14, 14: 18, 15: 18, 16: 18, 17: 18, 18: 18, 19: 16,
}

#: the engine resolves a record as ``base + (offset & 0xFFFF)`` (``0x0040B840``)
U16_CEILING = 0x10000


class ItemDbError(Exception):
    pass


@dataclass
class Record:
    """One database entry.  ``name is None`` means "opaque, carry verbatim"."""

    index: int
    raw: bytes                      # the original bytes, always kept
    type: int | None = None
    header: bytes | None = None
    name: bytes | None = None
    desc: bytes | None = None

    @property
    def translatable(self) -> bool:
        return self.name is not None

    def pack(self, name: bytes | None = None, desc: bytes | None = None) -> bytes:
        """The record's bytes, optionally with the strings replaced."""
        if not self.translatable:
            return self.raw
        n = self.name if name is None else name
        d = self.desc if desc is None else desc
        if b"\x00" in n or b"\x00" in d:
            raise ItemDbError("record %d: embedded NUL in a string" % self.index)
        return self.header + n + b"\x00" + d + b"\x00"


def parse(body: bytes) -> list[Record]:
    """``body`` (one decrypted container) -> the record list."""
    if len(body) < 2:
        raise ItemDbError("body too short")
    count = struct.unpack_from("<H", body, 0)[0]
    table_end = 2 + count * 2
    if table_end > len(body):
        raise ItemDbError("offset table runs past the body")
    offs = list(struct.unpack_from("<%dH" % count, body, 2))
    if offs and offs[0] != table_end:
        raise ItemDbError("first record does not start at the end of the table")
    if any(offs[i] > offs[i + 1] for i in range(len(offs) - 1)):
        raise ItemDbError("offset table is not monotonic")

    out: list[Record] = []
    for i in range(count):
        start = offs[i]
        end = offs[i + 1] if i + 1 < count else len(body)
        raw = body[start:end]
        rec = Record(index=i, raw=raw)
        if len(raw) >= 6:
            rec.type = raw[4]
            h = HEADER_LEN.get(rec.type)
            if h is not None and h < len(raw):
                p = raw.find(b"\x00", h)
                q = raw.find(b"\x00", p + 1) if p >= 0 else -1
                # it must tile exactly: nothing after the description's NUL
                if p >= 0 and q == len(raw) - 1:
                    rec.header, rec.name, rec.desc = raw[:h], raw[h:p], raw[p + 1:q]
        out.append(rec)
    return out


def build(records: list[Record], strings=None, *, wide: bool = False) -> bytes:
    """Rebuild the body.

    ``strings`` is an optional ``{index: (name, desc)}`` override.  With
    ``wide=False`` the original ``u16`` offset table is emitted, so
    ``build(parse(x)) == x``; with ``wide=True`` the table is ``u32``, which is
    what the patched loader reads (``docs/format-notes.md`` section 6.3).
    """
    strings = strings or {}
    count = len(records)
    stride = 4 if wide else 2
    fmt = "<I" if wide else "<H"
    table_end = 2 + count * stride

    blobs = []
    for rec in records:
        name, desc = strings.get(rec.index, (None, None))
        blobs.append(rec.pack(name, desc))

    offs, p = [], table_end
    for blob in blobs:
        offs.append(p)
        p += len(blob)
    if not wide and p > U16_CEILING:
        raise ItemDbError(
            "body is %d bytes; the u16 offset table caps it at %d. "
            "Rebuild with wide=True and the patched loader." % (p, U16_CEILING))

    out = bytearray(struct.pack("<H", count))
    for o in offs:
        out += struct.pack(fmt, o)
    for blob in blobs:
        out += blob
    return bytes(out)
