"""The .BIN container: a 16-bit header word followed by a chain-XOR body.

    raw  = [u16 LE header][encoded body]
    enc[i] = plain[0] ^ plain[1] ^ ... ^ plain[i]
    plain[i] = enc[i] ^ enc[i-1]          (enc[-1] = 0)

The transform is its own kind of running checksum -- trivially reversible, no
compression, no key.  Round-trip is byte-exact on all 844 encoded files
(m/ 309, p/ 432, et/ET* + et/ID* 103).

The header word equals ``len(body)`` for 783 of those files.  For 38 ``m/MS6xxx``
files, all 17 ``et/ID*`` files and a handful of ``et/ET*`` files it is something
else that is still being reverse engineered.  :func:`recompute_header` is the
single place that decides what to write, so when the meaning is pinned down only
that function changes.
"""
from __future__ import annotations


def unxor(data: bytes) -> bytes:
    """Decode a chain-XOR encoded body."""
    out = bytearray(len(data))
    prev = 0
    for i, b in enumerate(data):
        out[i] = b ^ prev
        prev = b
    return bytes(out)


def enxor(data: bytes) -> bytes:
    """Encode a plain body with the chain XOR."""
    out = bytearray(len(data))
    prev = 0
    for i, b in enumerate(data):
        prev = b ^ prev
        out[i] = prev
    return bytes(out)


def unpack(raw: bytes) -> "tuple[int, bytes]":
    """``raw`` -> ``(header_word, plain_body)``."""
    if len(raw) < 2:
        raise ValueError("container shorter than its 2-byte header")
    return int.from_bytes(raw[:2], "little"), unxor(raw[2:])


def pack(body: bytes, hdr: "int | None" = None) -> bytes:
    """``(plain_body, header_word)`` -> ``raw``.  ``hdr`` defaults to ``len(body)``."""
    if hdr is None:
        hdr = len(body)
    return (hdr & 0xFFFF).to_bytes(2, "little") + enxor(body)


def recompute_header(rel: str, src_hdr: int, src_body: bytes, new_body: bytes) -> int:
    """Decide the header word to write for a rebuilt file.

    Current policy, deliberately conservative:

    * if the source header was exactly ``len(source body)``, keep that
      relationship and emit ``len(new_body)``;
    * otherwise the word means something we do not understand yet, so it is
      preserved verbatim.

    Either way an unmodified rebuild is byte-identical to the source, which is
    what the ``check`` identity test asserts.  ``rel`` (``"m/MS6007.BIN"``) is
    passed in so a future family-specific rule has somewhere to hang.
    """
    if src_hdr == len(src_body):
        return len(new_body) & 0xFFFF
    return src_hdr
