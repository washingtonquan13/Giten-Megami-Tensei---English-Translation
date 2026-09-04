"""Dev exe: the release image plus the interpreter trace hook.

``exec_token`` (VA ``0x439020``) has exactly three callers -- ``E8`` at VA
``0x4390C4``, ``0x439103`` and ``0x43913C`` (verified by scanning the whole
``.text`` for ``call`` instructions that land there).  Redirecting those three
rel32 operands to a wrapper in a new ``.trc`` section is the entire hook: three
4-byte diffs plus an appended section, all reversible.

The wrapper is ``trace.S``, assembled here with GNU ``as --32`` and extracted
with ``objcopy -O binary``.  It is position-independent, so it needs no linker
and no knowledge of where the section lands; the addresses it *does* need --
the real ``exec_token``, two IAT slots, four engine globals -- are passed as
``--defsym`` so this file is the only place they are written down.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile

from .. import paths
from . import patch
from .pe import PE

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "trace.S")

EXEC_TOKEN = 0x439020
#: VA of each ``E8`` that calls exec_token (the rel32 follows at +1)
CALL_SITES = (0x4390C4, 0x439103, 0x43913C)

SYMBOLS = {
    "EXEC_TOKEN": EXEC_TOKEN,
    "CREATEFILE_IAT": 0x464074,     # kernel32!CreateFileA
    "WRITEFILE_IAT": 0x4640AC,      # kernel32!WriteFile
    "CTX": 0x491160,                # -> script context; PC is a u16 at +0x0E
    "FILEID": 0x4911B0,             # current script file id (u16)
    "RECID": 0x4911B2,              # current record id (u16)
    "CAPFLAG": 0x481224,            # text-capture mode (u16, non-zero = on)
    "CAPBUF": 0x481120,             # the 256-byte capture buffer
}

#: IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE
TRC_CHARACTERISTICS = 0xE0000060

RECORD = struct.Struct("<HHHHhBB")     # file, rec, pc, ch, r, capflag, caplen
RECORD_SIZE = RECORD.size


def assemble(source: str = SOURCE) -> bytes:
    """``trace.S`` -> raw bytes of its ``.text``."""
    for tool in ("as", "objcopy"):
        if shutil.which(tool) is None:
            raise RuntimeError("%s not found (GNU binutils are required to build the "
                               "dev exe)" % tool)
    tmp = tempfile.mkdtemp(prefix="giten-trace-")
    try:
        obj = os.path.join(tmp, "trace.o")
        binp = os.path.join(tmp, "trace.bin")
        defs = []
        for k, v in SYMBOLS.items():
            defs += ["--defsym", "%s=0x%X" % (k, v)]
        subprocess.run(["as", "--32", *defs, "-o", obj, source], check=True)
        subprocess.run(["objcopy", "-O", "binary", "-j", ".text", obj, binp], check=True)
        with open(binp, "rb") as fh:
            blob = fh.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not blob or len(blob) > 0x1000:
        raise RuntimeError("unexpected cave size %d" % len(blob))
    return blob


def build_dev(out_dir: "str | None" = None) -> str:
    out_dir = out_dir or os.path.join(paths.BUILD_DIR, "exe")
    os.makedirs(out_dir, exist_ok=True)
    with open(patch.ORG, "rb") as fh:
        release = patch.apply(fh.read(), "release")

    pe = PE(release, "dds_release")
    cave_va = pe.imagebase + pe.sizeimage         # where append_section will put it
    image = bytearray(pe.append_section(".trc", assemble(), TRC_CHARACTERISTICS))

    pe2 = PE(bytes(image), "dds_dev")
    for site in CALL_SITES:
        off = pe2.va2off(site)
        if image[off] != 0xE8:
            raise RuntimeError("no call at 0x%X" % site)
        old = struct.unpack_from("<i", image, off + 1)[0]
        if (site + 5 + old) & 0xFFFFFFFF != EXEC_TOKEN:
            raise RuntimeError("call at 0x%X does not target exec_token" % site)
        struct.pack_into("<i", image, off + 1, cave_va - (site + 5))

    dst = os.path.join(out_dir, "dds_dev.exe")
    with open(dst, "wb") as fh:
        fh.write(bytes(image))
    return dst
