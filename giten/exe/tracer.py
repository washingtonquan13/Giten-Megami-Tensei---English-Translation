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
HOOK_SOURCE = os.path.join(HERE, "hook.c")
HOOK_LD = os.path.join(HERE, "hook.ld")

#: the interpreter's byte fetch (``giten/overlay.py``) and its five call sites
FETCH = 0x438E50
FETCH_SITES = (0x438E8D, 0x438E9B, 0x438F0D, 0x438F32, 0x438FAD)
CFLAGS = ["-m32", "-O2", "-ffreestanding", "-nostdlib", "-fno-builtin",
          "-fno-stack-protector", "-fno-asynchronous-unwind-tables", "-fno-ident",
          "-mno-stack-arg-probe", "-fno-pic", "-fcf-protection=none",
          "-mpreferred-stack-boundary=2", "-Wall", "-Werror"]

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
    "HANDLE_TABLE": 0x47605C,       # [HANDLE_TABLE + handle*8] = buffer base (0x4045F0)
}

#: IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE
TRC_CHARACTERISTICS = 0xE0000060

#: file, rec, pc, ch, r, capflag, caplen, idx_off, idx_len
RECORD = struct.Struct("<HHHHhBBHH")
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


def short_path(p: str) -> str:
    """8.3 form of a path: the mingw driver mis-splits its own lib paths on spaces."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024):
            return buf.value
    except Exception:
        pass
    return p


def compile_hook(cave_va: int) -> bytes:
    """``hook.c`` -> a flat blob linked at ``cave_va`` (``hook.ld``), hook first."""
    for tool in ("gcc", "ld", "objcopy", "nm"):
        if shutil.which(tool) is None:
            raise RuntimeError("%s not found (GNU binutils + gcc are required)" % tool)
    gcc = short_path(shutil.which("gcc"))
    tmp = tempfile.mkdtemp(prefix="giten-hook-")
    try:
        obj, pe_, binp = (os.path.join(tmp, n) for n in ("hook.o", "hook.pe", "hook.bin"))
        subprocess.run([gcc, *CFLAGS, "-DGAME", "-c", HOOK_SOURCE, "-o", obj], check=True)
        undef = subprocess.run(["nm", "-u", obj], check=True, capture_output=True, text=True).stdout.split()
        if undef:
            raise RuntimeError("hook.c needs symbols the game cannot supply: %s" % undef)
        subprocess.run(["ld", "-m", "i386pe", "-T", HOOK_LD, "--defsym", "CAVE_VA=0x%X" % cave_va,
                        "-o", pe_, obj], check=True)
        subprocess.run(["objcopy", "-O", "binary", "-j", ".text", pe_, binp], check=True)
        with open(binp, "rb") as fh:
            blob = fh.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not blob or len(blob) > 0x2000:
        raise RuntimeError("unexpected hook size %d" % len(blob))
    return blob


def _redirect(image: bytearray, sites, old_target: int, new_target: int) -> None:
    pe = PE(bytes(image), "image")
    for site in sites:
        off = pe.va2off(site)
        if image[off] != 0xE8:
            raise RuntimeError("no call at 0x%X" % site)
        old = struct.unpack_from("<i", image, off + 1)[0]
        if (site + 5 + old) & 0xFFFFFFFF != old_target:
            raise RuntimeError("call at 0x%X does not target 0x%X" % (site, old_target))
        struct.pack_into("<i", image, off + 1, new_target - (site + 5))


def build_image(trace: bool) -> bytes:
    """Release image (locale patches) + the overlay hook, + the tracer if ``trace``."""
    with open(patch.ORG, "rb") as fh:
        image = patch.apply(fh.read(), "release")
    pe = PE(image, "dds_release")
    ovl_va = pe.imagebase + pe.sizeimage             # where append_section will put it
    image = bytearray(pe.append_section(".ovl", compile_hook(ovl_va), TRC_CHARACTERISTICS))
    _redirect(image, FETCH_SITES, FETCH, ovl_va)
    if trace:
        pe = PE(bytes(image), "dds_ovl")
        trc_va = pe.imagebase + pe.sizeimage
        image = bytearray(pe.append_section(".trc", assemble(), TRC_CHARACTERISTICS))
        _redirect(image, CALL_SITES, EXEC_TOKEN, trc_va)
    return bytes(image)


def _write(out_dir, name, trace):
    out_dir = out_dir or os.path.join(paths.BUILD_DIR, "exe")
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, name)
    with open(dst, "wb") as fh:
        fh.write(build_image(trace))
    return dst


def build_release(out_dir: "str | None" = None) -> str:
    """``dds.exe``: locale fixes + the runtime overlay.  What players run."""
    return _write(out_dir, "dds.exe", False)


def build_dev(out_dir: "str | None" = None) -> str:
    """``dds_dev.exe``: the release plus the interpreter tracer."""
    return _write(out_dir, "dds_dev.exe", True)
