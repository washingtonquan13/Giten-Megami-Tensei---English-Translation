"""English location names -- the string in the bar at the top of the screen.

Every ``m/M####.BIN`` carries its own name at the offset in its second header
word, and the map parser at ``0x00421470`` turns that into a pointer in exactly
one place.  Hooking that one place covers all 109 map files without editing any
of them, which is why this is an exe patch and not a data edit.

The section is laid out table-first so the code can be assembled before the
table is known::

    +0x0000  u32 name[256]     indexed by map id; 0 = keep the Japanese
    +0x0400  lookup()          the routine, assembled with MAPTABLE = base
             strings           cp932, NUL-terminated

See ``mapnames.S`` for the hook itself.
"""
from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import tempfile

from .. import container, paths
from .pe import PE

SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mapnames.S")
TABLE = os.path.join(paths.REPO_ROOT, "tables", "mapnames.tsv")

#: map ids run 0x00..0xFF
MAPSLOTS = 0x100
TABLE_BYTES = MAPSLOTS * 4

#: the widest Japanese name is 18 bytes -- 9 full-width glyphs, 18 cells
NAME_CELLS = 18

#: ``mov ax,[edx+2]`` / ``push ebp`` / ``add eax,edx``
HOOK_SITE = 0x0042147C
HOOK_OLD = bytes.fromhex("668b42025503c2")

SYMBOLS = {
    "MAPID": 0x004716E0,        # u16: id of the file the router last opened
    "MAPSLOTS": MAPSLOTS,
}

MAP_CHARACTERISTICS = 0xE0000060     # CODE | INITIALIZED_DATA | EXEC | READ | WRITE

_MAPFILE = re.compile(r"M([0-9A-Fa-f]{4})\.BIN", re.I)


def cells(s: str) -> int:
    return sum(1 if (ord(c) < 0x80 or 0xFF61 <= ord(c) <= 0xFF9F) else 2 for c in s)


def japanese_names(ddswin: str) -> "dict[int, str]":
    """``{map id: name}`` read out of every ``m/M####.BIN``."""
    out = {}
    d = os.path.join(ddswin, "m")
    for n in sorted(os.listdir(d)):
        m = _MAPFILE.fullmatch(n)
        if not m:
            continue
        body = container.split(open(os.path.join(d, n), "rb").read())[0][0].body
        off = struct.unpack_from("<H", body, 2)[0]
        end = body.find(b"\x00", off)
        out[int(m.group(1), 16)] = body[off:end].decode("cp932")
    return out


def read_table(path: str = TABLE) -> "dict[int, str]":
    out = {}
    if not os.path.exists(path):
        return out
    for ln in open(path, encoding="utf-8"):
        if ln.startswith("#") or not ln.strip():
            continue
        f = ln.rstrip("\n").split("\t")
        if len(f) >= 3 and f[2]:
            out[int(f[0], 16)] = f[2]
    return out


def write_table(ddswin: str, path: str = TABLE) -> int:
    jp = japanese_names(ddswin)
    have = read_table(path)
    lines = ["# Giten location names (the bar at the top of the screen)",
             "# Edit the english column.  Leave it empty to keep the Japanese.",
             "# id\tjapanese\tenglish"]
    for mid in sorted(jp):
        lines.append("%04X\t%s\t%s" % (mid, jp[mid], have.get(mid, "")))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return len(jp)


def assemble(cave_va: int):
    """``mapnames.S`` -> ``(code, {symbol: offset within the code})``."""
    for tool in ("as", "objcopy", "nm"):
        if shutil.which(tool) is None:
            raise RuntimeError("%s not found (GNU binutils are required)" % tool)
    tmp = tempfile.mkdtemp(prefix="giten-map-")
    try:
        obj, binp = os.path.join(tmp, "m.o"), os.path.join(tmp, "m.bin")
        defs = []
        for k, v in dict(SYMBOLS, MAPTABLE=cave_va).items():
            defs += ["--defsym", "%s=0x%X" % (k, v)]
        subprocess.run(["as", "--32", *defs, "-o", obj, SOURCE], check=True)
        undef = subprocess.run(["nm", "-u", obj], check=True,
                               capture_output=True, text=True).stdout.split()
        if undef:
            raise RuntimeError("mapnames.S references undefined symbols %s"
                               % sorted(set(undef)))
        listing = subprocess.run(["nm", obj], check=True, capture_output=True, text=True).stdout
        syms = {p[2]: int(p[0], 16) for p in (l.split() for l in listing.splitlines())
                if len(p) == 3 and p[1] in "tT"}
        subprocess.run(["objcopy", "-O", "binary", "-j", ".text", obj, binp], check=True)
        code = open(binp, "rb").read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if "lookup" not in syms:
        raise RuntimeError("mapnames.S did not export lookup")
    return code, syms


def plan(names: "dict[int, str]"):
    """``(names to emit, findings)`` after the width and encoding checks."""
    keep, findings = {}, []
    for mid, en in sorted(names.items()):
        if not en:
            continue
        if mid >= MAPSLOTS:
            findings.append((mid, "map id is outside the %d-slot table" % MAPSLOTS))
            continue
        if cells(en) > NAME_CELLS:
            findings.append((mid, "%d cells, the bar fits %d: %r" % (cells(en), NAME_CELLS, en)))
            continue
        try:
            en.encode("cp932")
        except UnicodeEncodeError:
            findings.append((mid, "not cp932-encodable: %r" % en))
            continue
        keep[mid] = en
    return keep, findings


def apply(image: bytes, names: "dict[int, str] | None" = None) -> bytes:
    """Append ``.mnm`` and point the map parser's one name computation at it."""
    names = read_table() if names is None else names
    keep, findings = plan(names)
    if findings:
        raise RuntimeError("mapnames: %s" % findings[:3])

    pe = PE(image, "mapnames")
    cave_va = pe.imagebase + pe.sizeimage
    code, syms = assemble(cave_va)

    blob = bytearray(TABLE_BYTES) + code
    at = {}
    for mid, en in sorted(keep.items()):
        at[mid] = len(blob)
        blob += en.encode("cp932") + b"\x00"
    for mid, off in at.items():
        struct.pack_into("<I", blob, mid * 4, cave_va + off)

    out = bytearray(pe.append_section(".mnm", bytes(blob), MAP_CHARACTERISTICS))
    pe = PE(bytes(out), "mapnames2")
    off = pe.va2off(HOOK_SITE)
    if bytes(out[off:off + len(HOOK_OLD)]) != HOOK_OLD:
        raise RuntimeError("mapnames: the parser's name computation at 0x%08X moved" % HOOK_SITE)
    target = cave_va + TABLE_BYTES + syms["lookup"]
    out[off] = 0x55                                   # push ebp
    out[off + 1] = 0xE8                               # call lookup
    struct.pack_into("<i", out, off + 2, target - (HOOK_SITE + 6))
    out[off + 6] = 0x90                               # nop
    return bytes(out)
