"""Lift the 64 KB ceiling off the item database.

``et/ET0001.BIN`` is capped at 65,535 bytes three separate ways
(``docs/format-notes.md`` section 6.3), and the English needs more.  Each limit
gets one small patch, and all three land only in the English exe:

===============================  ==============================================
``0x004232C2`` (39 bytes)        the stock open/read/store/close run is replaced
                                 by ``call load``, which opens **et0102.bin**
                                 -- a file we add -- and walks its whole
                                 container chain instead of reading one
                                 container
``0x00422D2B`` (5 bytes)         ``mov dx, word [eax+ecx*2+2]`` becomes
                                 ``mov edx, dword [eax+ecx*4+2]`` + ``nop``:
                                 the offset table is now ``u32``
``0x00422D32`` (rel32)           the ``call`` to the shared resolver
                                 ``0x0040B840`` (which masks the offset to 16
                                 bits, and has 17 other callers) is pointed at
                                 our private unmasked copy
===============================  ==============================================

``et/ET0001.BIN`` itself is never modified, so an unpatched exe still reads the
original and the ``u16`` and ``u32`` formats can never be applied to each other.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile

from .pe import PE

SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.S")

#: file id of the English database, ``et\\et0102.bin``.  The router formats the
#: id with ``%.4x`` after ``movsx ecx, bx``, so it must be positive; the stock
#: ``et`` ids run 0x0000-0x0101 and then jump to the 0x10xx block, making 0x0102
#: the next free slot.  :func:`check_free` asserts the original does not use it.
ET_ID = 0x0102

#: how much the loader allocates for the concatenated chain
BUF_SIZE = 0x20000

SYMBOLS = {
    "ET_ID": ET_ID,
    "BUF_SIZE": BUF_SIZE,
    "ROUTER": 0x00401DD0,        # (id, kind, flags) -> FILE *
    "ALLOC": 0x004044C0,         # (size, 1) -> handle
    "HANDLE2PTR": 0x00404670,    # handle -> buffer base
    "FREAD": 0x0045A9F0,         # CRT fread(ptr, size, count, FILE *)
    "SETSEED": 0x00401B20,       # (header word) -> seeds the container cipher
    "READBODY": 0x00401BA0,      # (FILE *, len, dest) -> read + decrypt
    "FCLOSE": 0x00402250,        # (FILE *)
    "DEST": 0x004800E8,          # ds slot holding the database handle
}

#: the run that opens et0001.bin, reads one container, stores it and closes
INIT_SITE = 0x004232C2
INIT_OLD = bytes.fromhex(
    "6a006a0b6a01"          # push 0 ; push 0xb ; push 1
    "e803ebfdff"            # call 0x401dd0
    "83c40c"                # add esp, 0xc
    "8bf0"                  # mov esi, eax
    "56"                    # push esi
    "e858e9fdff"            # call 0x401c30
    "83c404"                # add esp, 4
    "a3e8004800"            # mov [0x4800e8], eax
    "56"                    # push esi
    "e86aeffdff"            # call 0x402250
    "83c404")               # add esp, 4

#: ``mov dx, word ptr [eax + ecx*2 + 2]`` -> ``mov edx, dword ptr [eax+ecx*4+2]``
OFFSET_SITE = 0x00422D2B
OFFSET_OLD = bytes.fromhex("668b544802")
OFFSET_NEW = bytes.fromhex("8b54880290")

#: the ``call 0x0040B840`` that masks the offset to 16 bits
RESOLVE_SITE = 0x00422D32
RESOLVE_OLD_TARGET = 0x0040B840

DB_CHARACTERISTICS = 0xE0000060      # CODE | INITIALIZED_DATA | EXEC | READ | WRITE


def assemble(cave_va: int):
    """``database.S`` -> ``(blob, {symbol: va})``."""
    for tool in ("as", "objcopy", "nm"):
        if shutil.which(tool) is None:
            raise RuntimeError("%s not found (GNU binutils are required)" % tool)
    tmp = tempfile.mkdtemp(prefix="giten-db-")
    try:
        obj = os.path.join(tmp, "db.o")
        binp = os.path.join(tmp, "db.bin")
        defs = []
        for k, v in SYMBOLS.items():
            defs += ["--defsym", "%s=0x%X" % (k, v)]
        subprocess.run(["as", "--32", *defs, "-o", obj, SOURCE], check=True)
        listing = subprocess.run(["nm", obj], check=True, capture_output=True, text=True).stdout
        syms = {}
        for line in listing.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[1] in "tT":
                syms[parts[2]] = cave_va + int(parts[0], 16)
        subprocess.run(["objcopy", "-O", "binary", "-j", ".text", obj, binp], check=True)
        with open(binp, "rb") as fh:
            blob = fh.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for need in ("load", "resolve"):
        if need not in syms:
            raise RuntimeError("database.S did not export %r" % need)
    if not blob or len(blob) > 0x400:
        raise RuntimeError("unexpected loader size %d" % len(blob))
    return blob, syms


def _write_call(image: bytearray, pe: PE, site: int, target: int, old: bytes | None = None) -> None:
    off = pe.va2off(site)
    if old is not None and bytes(image[off:off + len(old)]) != old:
        raise RuntimeError("database: 0x%08X does not hold the expected bytes" % site)
    image[off] = 0xE8
    struct.pack_into("<i", image, off + 1, target - (site + 5))


def apply(image: bytes) -> bytes:
    """Append ``.idb`` and land the three patches."""
    pe = PE(image, "database")
    cave_va = pe.imagebase + pe.sizeimage
    blob, syms = assemble(cave_va)
    out = bytearray(pe.append_section(".idb", blob, DB_CHARACTERISTICS))
    pe = PE(bytes(out), "database2")

    # 1. the loader replaces the whole open/read/store/close run
    off = pe.va2off(INIT_SITE)
    if bytes(out[off:off + len(INIT_OLD)]) != INIT_OLD:
        raise RuntimeError("database: the init run at 0x%08X is not what we expect" % INIT_SITE)
    out[off:off + len(INIT_OLD)] = b"\x90" * len(INIT_OLD)
    _write_call(out, pe, INIT_SITE, syms["load"])

    # 2. the offset table is now u32
    off = pe.va2off(OFFSET_SITE)
    if bytes(out[off:off + len(OFFSET_OLD)]) != OFFSET_OLD:
        raise RuntimeError("database: the offset load at 0x%08X moved" % OFFSET_SITE)
    out[off:off + len(OFFSET_NEW)] = OFFSET_NEW

    # 3. the record locator gets an unmasked resolver of its own
    off = pe.va2off(RESOLVE_SITE)
    if out[off] != 0xE8:
        raise RuntimeError("database: 0x%08X is not a call" % RESOLVE_SITE)
    rel = struct.unpack_from("<i", out, off + 1)[0]
    if (RESOLVE_SITE + 5 + rel) & 0xFFFFFFFF != RESOLVE_OLD_TARGET:
        raise RuntimeError("database: 0x%08X does not call the shared resolver" % RESOLVE_SITE)
    _write_call(out, pe, RESOLVE_SITE, syms["resolve"])
    return bytes(out)


def check_free(original_et_dir: str) -> None:
    """The id we claim must not already be a shipped file."""
    name = "et%04x.bin" % ET_ID
    have = {n.lower() for n in os.listdir(original_et_dir)}
    if name in have:
        raise RuntimeError("database: the original already ships %s" % name)
