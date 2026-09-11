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
#: the single ``call 0x00433D70`` in the mode-0 arm of the ``0C``/``0D``
#: trampoline ``0x00433E70``; redirecting it is the whole hook
CALL_SITE = 0x00433E97

#: a ``0C``/``0D`` file operand that occurs nowhere in the corpus
SENTINEL = 0xD9

#: IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE
WRP_CHARACTERISTICS = 0xE0000060


def assemble(file_id: int, rec_id: int, entry: int = 0,
             sentinel: int = SENTINEL) -> bytes:
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
            sentinel: int = SENTINEL) -> bytes:
    """Append the cave to ``image`` and point ``CALL_SITE`` at it."""
    pe = PE(image, "dds_warp")
    va = pe.imagebase + pe.sizeimage
    blob = assemble(file_id, rec_id, entry, sentinel)
    out = bytearray(pe.append_section(".wrp", blob, WRP_CHARACTERISTICS))
    pe = PE(bytes(out), "dds_warp")
    off = pe.va2off(CALL_SITE)
    if out[off] != 0xE8:
        raise RuntimeError("no call at 0x%X" % CALL_SITE)
    old = struct.unpack_from("<i", out, off + 1)[0]
    if (CALL_SITE + 5 + old) & 0xFFFFFFFF != GOTO_RECORD:
        raise RuntimeError("the call at 0x%X does not target goto-record" % CALL_SITE)
    struct.pack_into("<i", out, off + 1, va - (CALL_SITE + 5))
    return bytes(out)


def build(file_id: int, rec_id: int, entry: int = 0,
          out_dir: "str | None" = None) -> str:
    """``dds_dev_warp.exe``: the Japanese tracer build plus the cave."""
    out_dir = out_dir or os.path.join(paths.BUILD_DIR, "exe")
    os.makedirs(out_dir, exist_ok=True)
    image = install(tracer.build_image(True, english=False), file_id, rec_id, entry)
    dst = os.path.join(out_dir, "dds_dev_warp.exe")
    with open(dst, "wb") as fh:
        fh.write(image)
    return dst
