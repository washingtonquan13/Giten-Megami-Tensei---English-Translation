"""Build a dev exe carrying the 16-bit warp cave (``warp16.S``).

The cave is the *only* way to make the engine execute a record of a file whose
id needs sixteen bits.  See the module header of ``warp16.S`` for why the engine
can do it at all and why no new loader code is needed; this file is just the
build: assemble, append a ``.wrp`` section, and repoint one call.

The exe it produces is a Japanese tracer build (``dds_dev_jp.exe``'s image) plus
that section, so a warp session's trace is directly comparable with the
tokenizer's output on the original bytes.
"""
from __future__ import annotations

import os
import struct

from .. import paths
from . import tracer
from .pe import PE

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "warp16.S")

#: ``0x00433D70(u16 file, u16 record)`` -- goto-record, the engine's own
GOTO_RECORD = 0x00433D70
#: ``0x00433C40(u16 pc)`` -- ``mov [ctx+0x0E], ax``, the engine's own set_pc
SET_PC = 0x00433C40
#: **Every** ``call 0x00433D70`` in the image, found by scanning the whole
#: ``.text`` for calls landing there (the same method ``tracer`` used for
#: ``exec_token``):
#:
#: =============  =========================================================
#: ``0x0043279D``  the ``0E``/``0F`` switch case of kind 0
#: ``0x00433E5A``  inside ``0x00433E40``, call-record (``0D``)
#: ``0x00433E97``  inside ``0x00433E70``, goto-record (``0C``)
#: ``0x00433FEF``  inside ``0x00433FE0``
#: ``0x00438D87``  inside ``0x00438D70(file, rec, ctx)``, the exe's own entry
#: =============  =========================================================
#:
#: All five are redirected.  One would do for a script-initiated jump, but the
#: negotiation is started by the engine, not by a script, and that path comes
#: through ``0x00438D87``.
CALL_SITES = (0x0043279D, 0x00433E5A, 0x00433E97, 0x00433FEF, 0x00438D87)
#: kept as a name because the tests talk about the `0C` arm specifically
CALL_SITE = 0x00433E97

#: a ``0C``/``0D`` file operand that occurs nowhere in the corpus
SENTINEL = 0xD9
#: ``WARP_MATCH_REC`` value meaning "whatever record that file was jumped to"
ANY_REC = 0xFFFF

#: IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE
WRP_CHARACTERISTICS = 0xE0000060


def assemble(file_id: int, rec_id: int, entry: int = 0,
             sentinel: int = SENTINEL, match_rec: int = ANY_REC) -> bytes:
    """``warp16.S`` with its target assembled in, as raw ``.text`` bytes."""
    if not 0 <= file_id <= 0xFFFF or not 0 <= rec_id <= 0xFF:
        raise ValueError("bad warp target 0x%X r%X" % (file_id, rec_id))
    if not 0 <= entry <= 0xFFFF:
        raise ValueError("bad entry offset 0x%X" % entry)
    syms = {
        "GOTO_RECORD": GOTO_RECORD,
        "SET_PC": SET_PC,
        "CTX": tracer.SYMBOLS["CTX"],
        "WARP_SENTINEL": sentinel,
        "WARP_MATCH_REC": match_rec,
        "WARP_FILE": file_id,
        "WARP_REC": rec_id,
        "WARP_ENTRY": entry,
    }
    old = dict(tracer.SYMBOLS)
    try:
        tracer.SYMBOLS = syms
        return tracer.assemble(SOURCE)
    finally:
        tracer.SYMBOLS = old


def install(image: bytes, file_id: int, rec_id: int, entry: int = 0,
            sentinel: int = SENTINEL, match_rec: int = ANY_REC) -> bytes:
    """Append the cave to ``image`` and point every goto-record call at it."""
    pe = PE(image, "dds_warp")
    va = pe.imagebase + pe.sizeimage
    blob = assemble(file_id, rec_id, entry, sentinel, match_rec)
    out = bytearray(pe.append_section(".wrp", blob, WRP_CHARACTERISTICS))
    pe = PE(bytes(out), "dds_warp")
    for site in CALL_SITES:
        off = pe.va2off(site)
        if out[off] != 0xE8:
            raise RuntimeError("no call at 0x%X" % site)
        old = struct.unpack_from("<i", out, off + 1)[0]
        if (site + 5 + old) & 0xFFFFFFFF != GOTO_RECORD:
            raise RuntimeError("the call at 0x%X does not target goto-record" % site)
        struct.pack_into("<i", out, off + 1, va - (site + 5))
    return bytes(out)


def build(file_id: int, rec_id: int, entry: int = 0,
          out_dir: "str | None" = None, sentinel: int = SENTINEL,
          match_rec: int = ANY_REC, name: "str | None" = None) -> str:
    """``dds_dev_warp*.exe``: the Japanese tracer build plus the cave."""
    out_dir = out_dir or os.path.join(paths.BUILD_DIR, "exe")
    os.makedirs(out_dir, exist_ok=True)
    image = install(tracer.build_image(True, english=False), file_id, rec_id,
                    entry, sentinel, match_rec)
    dst = os.path.join(out_dir, name or "dds_dev_warp_%04X_%02X.exe" % (file_id, rec_id))
    with open(dst, "wb") as fh:
        fh.write(image)
    return dst
