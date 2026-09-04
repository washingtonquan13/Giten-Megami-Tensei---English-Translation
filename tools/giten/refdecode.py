"""A deliberately dumb reference decoder, transcribed from the disassembly.

This module exists so the tests have something to check the real pipeline
*against* rather than against itself.  It is written as a literal transcription
of ``docs/format-notes.md`` §0 / §1 -- a byte-at-a-time reader that mirrors
``dds_en.exe`` 0x43AA90 (``load_script_file``) and 0x401B20/0x401B40 (the cipher)
-- and shares no code with :mod:`.container` or :mod:`.records`.  It is slow and
that is fine; nothing but the test suite calls it.

Engine transcription::

    fread(&hdr, 2, 1, f)                    # 0x43AA90: read the header in the clear
    if (result < 1) return                  # EOF -> done
    set_cipher_state((hdr >> 8) ^ (hdr & 0xFF))     # 0x401B20 -- the ONLY use of hdr
    count = read_u16_decrypted(f)           # the real record count
    remaining = hdr - 2                     # stored, decremented, never read
    for (i = 0; i < count; i++)
        remaining -= install_record(list, f)

    install_record:                         # 0x43AB10
        id  = read_u8()
        len = read_u16()
        if (len == 0xFFFF):                 # conditional record
            cond = read_u8(); param = read_u8(); len = read_u16()
        data = read(len)

Each ``read_*`` pulls bytes through the running cipher state, so the decoder is
a *stream*: it never assumes where a container's body ends, it just keeps
decrypting until the record loop says stop.  That is what makes it a real
check on :mod:`.container`, which computes the body up front from ``hdr``.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RefRecord:
    id: int
    length: int
    cond: "int | None"
    param: "int | None"
    data: bytes


@dataclass
class RefContainer:
    hdr: int
    count: int
    records: "list[RefRecord]" = field(default_factory=list)
    consumed: int = 0          # ciphertext bytes the record loop actually ate
    error: "str | None" = None


class _Stream:
    """A file cursor with the engine's one-byte cipher state (ds:0x4712D0)."""

    def __init__(self, raw: bytes, pos: int = 0):
        self.raw = raw
        self.pos = pos
        self.prev = 0

    def eof(self) -> bool:
        return self.pos >= len(self.raw)

    def raw_u16(self) -> "int | None":
        """A word read *in the clear* -- only the container header is."""
        if self.pos + 2 > len(self.raw):
            return None
        v = int.from_bytes(self.raw[self.pos:self.pos + 2], "little")
        self.pos += 2
        return v

    def seed(self, hdr: int) -> None:
        self.prev = ((hdr >> 8) ^ (hdr & 0xFF)) & 0xFF

    def u8(self) -> int:
        if self.pos >= len(self.raw):
            raise EOFError("read past end of file")
        c = self.raw[self.pos]
        self.pos += 1
        p = c ^ self.prev
        self.prev = c
        return p

    def u16(self) -> int:
        return self.u8() | (self.u8() << 8)

    def take(self, n: int) -> bytes:
        return bytes(self.u8() for _ in range(n))


def decode_file(raw: bytes) -> "list[RefContainer]":
    """Decode a whole ``.BIN`` the way the engine reads it, container by container."""
    out: "list[RefContainer]" = []
    st = _Stream(raw)
    while not st.eof():
        start = st.pos
        hdr = st.raw_u16()
        if hdr is None or hdr == 0:
            break
        st.seed(hdr)
        c = RefContainer(hdr=hdr, count=0)
        try:
            c.count = st.u16()
            for _ in range(c.count):
                rid = st.u8()
                ln = st.u16()
                cond = param = None
                if ln == 0xFFFF:
                    cond = st.u8()
                    param = st.u8()
                    ln = st.u16()
                c.records.append(RefRecord(rid, ln, cond, param, st.take(ln)))
        except EOFError as exc:
            c.error = str(exc)
        c.consumed = st.pos - start - 2
        out.append(c)
        if c.error:
            break
        # The engine's next fread lands wherever the record loop stopped.  For a
        # well-formed file that is exactly `hdr` bytes on, which is what makes a
        # rebuilt container's header have to equal its body length.
        if c.consumed != hdr:
            c.error = ("record loop consumed %d bytes, header says %d"
                       % (c.consumed, hdr))
            break
        st.pos = start + 2 + hdr
    return out


def decode_records(raw: bytes) -> "list[list[RefRecord]]":
    """Just the records, per container.  Raises on any decode error."""
    conts = decode_file(raw)
    for i, c in enumerate(conts):
        if c.error:
            raise ValueError("container %d: %s" % (i, c.error))
    return [c.records for c in conts]
