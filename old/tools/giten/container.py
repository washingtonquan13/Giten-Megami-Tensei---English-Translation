"""The ``.BIN`` container layer.

Verified model (``docs/format-notes.md`` §0, from ``dds_en.exe`` 0x401B20 /
0x401B40 / 0x43AA90)::

    container := u16 hdr (plaintext, little endian) , hdr bytes of ciphertext
    file      := container+

Decryption is a chained XOR whose **seed is derived from the header word**::

    prev = (hdr >> 8) ^ (hdr & 0xFF)
    for each ciphertext byte c:   plain = c ^ prev ;   prev = c

The engine never validates ``hdr`` as a length, count or checksum -- its *only*
functional role is to seed the cipher.  By convention it equals the length of the
container body, and every shipped container satisfies that, so a rebuilt
container writes ``hdr = len(new_body)`` and encrypts with ``seed_of(hdr)``.
Header and cipher must agree: change the length and you change the seed.

The chain lands exactly on EOF for 842 of the 844 encoded files (all but
``et/A0000.BIN`` and ``et/A0001.BIN``); those two are handled as opaque blobs.

Legacy single-container API
---------------------------
:func:`unpack`, :func:`pack` and :func:`recompute_header` implement the *old*
model (one container per file, seed 0, unknown header word preserved).  They
differ from the engine in exactly one byte -- ``body[0]``, which the seed XORs --
and they cannot express a length change.  They are kept because the v1 pipeline
(``text/``, still being edited by translators) is built on them and its identity
build is byte-exact; new code must use :func:`split` / :func:`join`.
"""
from __future__ import annotations

from dataclasses import dataclass


# --- the engine's rule ------------------------------------------------------
def seed_of(hdr: int) -> int:
    """Cipher seed for a container header word (0x401B20)."""
    return ((hdr >> 8) ^ (hdr & 0xFF)) & 0xFF


def unxor(data: bytes, seed: int = 0) -> bytes:
    """Decode a chain-XOR encoded body.  ``seed`` defaults to the legacy 0."""
    out = bytearray(len(data))
    prev = seed
    for i, b in enumerate(data):
        out[i] = b ^ prev
        prev = b
    return bytes(out)


def enxor(data: bytes, seed: int = 0) -> bytes:
    """Encode a plain body with the chain XOR.  Inverse of :func:`unxor`."""
    out = bytearray(len(data))
    prev = seed
    for i, b in enumerate(data):
        prev = b ^ prev
        out[i] = prev
    return bytes(out)


@dataclass
class Container:
    """One ``[u16 hdr][hdr bytes]`` unit of a ``.BIN`` file."""

    index: int
    off: int                 # byte offset of the header word in the raw file
    hdr: int
    body: bytes              # decrypted, ``hdr`` bytes long unless ``short``
    short: bool = False      # the file ended before ``hdr`` bytes were available


class ContainerError(ValueError):
    pass


def split(raw: bytes) -> "tuple[list[Container], int]":
    """``raw`` -> ``(containers, end_offset)``.

    Walks the chain the way the engine does: read a header word, consume that
    many ciphertext bytes, repeat.  ``end_offset == len(raw)`` means the chain
    landed exactly on EOF, which is the test for "this file is a container
    chain".  A zero header word stops the walk (the engine's ``fread`` would
    read a zero-length record set and make no progress).
    """
    out: "list[Container]" = []
    p = 0
    n = len(raw)
    while p + 2 <= n:
        hdr = int.from_bytes(raw[p:p + 2], "little")
        if hdr == 0:
            break
        enc = raw[p + 2:p + 2 + hdr]
        short = len(enc) < hdr
        out.append(Container(len(out), p, hdr, unxor(enc, seed_of(hdr)), short))
        if short:
            p = n
            break
        p += 2 + hdr
    return out, p


def is_container_chain(raw: bytes) -> bool:
    conts, end = split(raw)
    return bool(conts) and end == len(raw) and not any(c.short for c in conts)


def pack_one(body: bytes) -> bytes:
    """One plain body -> ``[u16 len][ciphertext]`` under the engine's rule."""
    hdr = len(body)
    if hdr > 0xFFFF:
        raise ContainerError("container body of %d bytes does not fit a u16 header"
                             % hdr)
    return hdr.to_bytes(2, "little") + enxor(body, seed_of(hdr))


def join(bodies: "list[bytes]") -> bytes:
    """Plain bodies -> a rebuilt ``.BIN`` file."""
    return b"".join(pack_one(b) for b in bodies)


# --- legacy single-container API (v1 pipeline; see the module docstring) -----
def unpack(raw: bytes) -> "tuple[int, bytes]":
    """LEGACY: ``raw`` -> ``(header_word, body decoded with seed 0)``."""
    if len(raw) < 2:
        raise ValueError("container shorter than its 2-byte header")
    return int.from_bytes(raw[:2], "little"), unxor(raw[2:])


def pack(body: bytes, hdr: "int | None" = None) -> bytes:
    """LEGACY: inverse of :func:`unpack`.  ``hdr`` defaults to ``len(body)``."""
    if hdr is None:
        hdr = len(body)
    return (hdr & 0xFFFF).to_bytes(2, "little") + enxor(body)


def recompute_header(rel: str, src_hdr: int, src_body: bytes, new_body: bytes) -> int:
    """LEGACY header policy for the v1 builder.

    Keeps ``hdr == len(body)`` where the source had it and preserves the word
    otherwise, which is what makes the v1 identity build byte-exact on the
    multi-container files it mis-reads as one container.  The v2 builder does
    not use this: it writes ``len(body)`` per container and re-seeds.
    """
    if src_hdr == len(src_body):
        return len(new_body) & 0xFFFF
    return src_hdr
