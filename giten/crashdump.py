"""Read a Windows crash dump and say where the game died, in our terms.

The exe is a 1999 binary with six sections appended to it, so a raw fault
address means nothing on its own.  This maps it back to something actionable::

    EIP 0x01040074  ->  .trc + 0x74      (our tracer)
    EIP 0x00451094  ->  .text VA 0x451094 (the original game)

which is the difference between "our injected code has a bug" and "the game has
a bug", and that distinction cost a lot of guessing before this existed.

Windows writes these to ``%LOCALAPPDATA%\\CrashDumps`` when
``HKCU\\Software\\Microsoft\\Windows\\Windows Error Reporting\\LocalDumps`` is
configured; :func:`find_dumps` also reads the WER report archives.  Nothing here
runs the game or the dump -- it is a pure file parse.
"""
from __future__ import annotations

import glob
import os
import struct

from .exe.pe import PE

#: MINIDUMP_STREAM_TYPE
THREAD_LIST, MODULE_LIST, EXCEPTION_STREAM, SYSTEM_INFO = 3, 4, 6, 7

#: x86 CONTEXT field offsets (after ContextFlags, Dr*, FloatSave, segments)
_X86_REGS = (("Edi", 0x9C), ("Esi", 0xA0), ("Ebx", 0xA4), ("Edx", 0xA8),
             ("Ecx", 0xAC), ("Eax", 0xB0), ("Ebp", 0xB4), ("Eip", 0xB8),
             ("Esp", 0xC4))

EXCEPTION_NAMES = {
    0xC0000005: "ACCESS_VIOLATION",
    0xC000001D: "ILLEGAL_INSTRUCTION",
    0xC0000094: "INTEGER_DIVIDE_BY_ZERO",
    0xC00000FD: "STACK_OVERFLOW",
    0x80000003: "BREAKPOINT",
}


class DumpError(RuntimeError):
    pass


def find_dumps(pattern: str = "dds*.exe*.dmp") -> "list[str]":
    """Newest first."""
    roots = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "CrashDumps")]
    out = []
    for root in roots:
        if root and os.path.isdir(root):
            out += glob.glob(os.path.join(root, pattern))
    return sorted(out, key=os.path.getmtime, reverse=True)


def _streams(data: bytes) -> "dict[int, tuple[int, int]]":
    sig, _ver, n, dirrva = struct.unpack_from("<4sIII", data, 0)
    if sig != b"MDMP":
        raise DumpError("not a minidump (%r)" % sig)
    out = {}
    for i in range(n):
        stype, size, rva = struct.unpack_from("<III", data, dirrva + i * 12)
        out[stype] = (size, rva)
    return out


def read(path: str) -> dict:
    """Parse the exception record, register context and module list."""
    data = open(path, "rb").read()
    st = _streams(data)
    if EXCEPTION_STREAM not in st:
        raise DumpError("dump has no exception stream")
    _size, rva = st[EXCEPTION_STREAM]
    tid = struct.unpack_from("<I", data, rva)[0]
    off = rva + 8
    code, _flags, _nested, addr, nparams, _u = struct.unpack_from("<IIQQII", data, off)
    params = struct.unpack_from("<15Q", data, off + 32)[:nparams]
    ctx_size, ctx_rva = struct.unpack_from("<II", data, off + 32 + 15 * 8)

    regs = {}
    if ctx_size >= 0xCC:
        for name, o in _X86_REGS:
            regs[name] = struct.unpack_from("<I", data, ctx_rva + o)[0]

    modules = []
    if MODULE_LIST in st:
        _s, mrva = st[MODULE_LIST]
        count = struct.unpack_from("<I", data, mrva)[0]
        for i in range(count):
            m = mrva + 4 + i * 108
            base, size, _cs, _ts, name_rva = struct.unpack_from("<QIIII", data, m)[:5]
            ln = struct.unpack_from("<I", data, name_rva)[0]
            nm = data[name_rva + 4:name_rva + 4 + ln].decode("utf-16-le", "replace")
            modules.append({"name": nm, "base": base, "size": size})

    return {"path": path, "thread": tid, "code": code, "address": addr,
            "params": list(params), "regs": regs, "modules": modules}


def locate(va: int, exe_path: str) -> str:
    """``0x01040074`` -> ``.trc + 0x74``, using the exe's own section table."""
    img = open(exe_path, "rb").read()
    pe = PE(img, "crash")
    rva = va - pe.imagebase
    sec = pe.sec_for_rva(rva)
    if sec is None:
        return "0x%08X  (not inside any section of %s)" % (va, os.path.basename(exe_path))
    return "0x%08X  %s + 0x%X" % (va, sec["name"], rva - sec["vaddr"])


#: sections we append; a fault in one of these is OUR bug, not the game's
OURS = (".ovl", ".nam", ".men", ".idb", ".mnm", ".trc")


def explain(dump_path: str, exe_path: "str | None" = None) -> str:
    d = read(dump_path)
    exe = exe_path
    if exe is None:
        for m in d["modules"]:
            if m["name"].lower().endswith(".exe"):
                exe = m["name"]
                break
    lines = ["%s" % os.path.basename(dump_path),
             "  exception : 0x%08X  %s" % (d["code"],
                                           EXCEPTION_NAMES.get(d["code"], "?"))]
    if d["code"] == 0xC0000005 and len(d["params"]) >= 2:
        kind = {0: "read", 1: "write", 8: "execute"}.get(d["params"][0], d["params"][0])
        lines.append("  fault     : %s of 0x%08X" % (kind, d["params"][1]))
        if d["params"][1] < 0x1000:
            lines.append("              (a null pointer plus a small offset)")
    eip = d["regs"].get("Eip", d["address"])
    if exe and os.path.exists(exe):
        where = locate(eip, exe)
        lines.append("  eip       : %s" % where)
        for s in OURS:
            if (" %s +" % s) in where:
                lines.append("              ^ this is OUR injected code, not the game")
                break
        else:
            lines.append("              ^ original game code")
    else:
        lines.append("  eip       : 0x%08X  (exe not found, cannot map)" % eip)
    if d["regs"]:
        lines.append("  registers : " + "  ".join(
            "%s=0x%08X" % (k, v) for k, v in sorted(d["regs"].items())))
    return "\n".join(lines)
