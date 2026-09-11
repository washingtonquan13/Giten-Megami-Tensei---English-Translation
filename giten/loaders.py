"""Which file ids the engine can actually open, and by which loader kind.

The router is `0x00401DD0(id, kind, flags)`: it stores the id in `ds:0x004716E0`,
bounds `kind` with `cmp eax,0xF; ja`, and jumps through the table at
`0x00402208`.  Entry 9 is the only one whose format string is `m\\ms%.4x.bin`
(`0x0046828C`), so **kind 9 is the only way any `m/MS*.BIN` is ever opened**, and
the question "is this file script" is exactly the question "does anything form
its id and pass it to kind 9".

Everything that forms such an id, exhaustively:

=====================================  ====================================
where                                  which ids
=====================================  ====================================
`0x0043B6C0`, immediates               `0x7F00`-`0x7F07` (the macro pools),
                                       `0x00DB`-`0x00DF`
`0x0040E948`, immediate                `0x6800`
`0x0040EBB6`, immediate                `0x6000` (the negotiation base)
`0x0040EBE1` / `0x0040EC09`,           `0x6000 + t`, `t` = `et/ET0007`
  `add $0x6000`                        columns 0 and 1
`0x0040EC31`, `add $0x6100`            `0x6100 + t`, `t` = column 2
the `0C`/`0D` opcodes and the `0E`/    a **u8**, i.e. `m/MS00xx`
  `0F` switch cases of kind 0
=====================================  ====================================

`0x0043AD20` is a generic loader taking the id in a register, so a *new* id
could in principle come from anywhere; the one caller whose id is not an
immediate is `0x0043458E` (`0x0043B7A0(stamp, id)`), and that function is a
dispatch on small scene ids (`cmp si,0x101`, `cmp si,0x106`, ...).  This is why
`DATA_FILES` is justified by a **conjunction**: no immediate, no table entry, no
formula, and no trace event ever standing in one of their records.

`m/MS6F00.BIN` and `m/MS6F1F.BIN` are the only two `m/MS*` files no path
reaches.  Their ids appear nowhere in `.text` as an immediate (checked by
:func:`immediate_sites`), the merge table cannot form them (its widest reach is
`0x6100 + 0xFF = 0x61FF`), and the two files are byte-identical for the records
in question.  So their bytes are never handed to `exec_token`, they are not
code, and the tokenizer's opinion of them is not a defect in the tokenizer.
"""
from __future__ import annotations

import os
import struct

from . import files, paths

#: `0x00401DD0`'s jump table
ROUTER_TABLE = 0x00402208
#: kinds 0..15; anything above falls through `cmp eax,0xF; ja 0x00402101`
ROUTER_KINDS = 16
#: the entry whose format string is `m\ms%.4x.bin` -- every script file
SCRIPT_KIND = 9
SCRIPT_KIND_HANDLER = 0x0040203C
SCRIPT_FORMAT_VA = 0x0046828C

#: the highest id the negotiation merge can form (`0x6100 + 0xFF`)
MERGE_MAX = 0x61FF

#: Files in `m/` that no code path can name.  Not "we have not found the
#: loader": there is no loader, and the evidence is the module docstring plus
#: `tests/test_data_files.py`.  Records here are censused as `data`.
DATA_FILES = frozenset({
    "m/MS6F00.BIN",
    "m/MS6F1F.BIN",
})


def _image():
    from .exe import patch
    from .exe.pe import PE
    img = patch.apply(open(patch.ORG, "rb").read(), "release")
    return img, PE(img, "dds_release")


def router_kinds() -> "dict[int, int]":
    """``{kind: handler VA}`` straight out of the table at 0x00402208."""
    img, pe = _image()
    out = {}
    for i in range(ROUTER_KINDS):
        off = pe.va2off(ROUTER_TABLE + i * 4)
        out[i] = struct.unpack_from("<I", img, off)[0]
    return out


def immediate_sites(value: int) -> "list[int]":
    """Every ``.text`` offset where ``value`` occurs as a little-endian u16.

    A crude but complete test for "is this id written down in the code": an
    immediate operand, a table entry and a relocation all contain the bytes.
    Callers still have to read what they find -- two of the four hits for
    ``0x6F00`` are the middle of unrelated instructions -- which is why this
    returns sites rather than a verdict.
    """
    img, pe = _image()
    text = [s for s in pe.sections if s["name"] == ".text"][0]
    lo, hi = text["rawptr"], text["rawptr"] + text["rawsize"]
    want = struct.pack("<H", value)
    out, i = [], img.find(want, lo, hi)
    while i >= 0:
        out.append(pe.off2va(i))
        i = img.find(want, i + 1, hi)
    return out


def instruction_immediates(*values: int) -> "list[str]":
    """Every disassembled ``.text`` line carrying one of ``values`` as a literal.

    ``immediate_sites`` finds the *bytes*; this finds the *instructions*, which
    is the question that matters -- three of the four byte hits for ``0x6F00``
    straddle two entries of a jump table and one is a jump table's own base
    address.  Linear disassembly can desync, but it desyncs into *more* apparent
    instructions, not fewer, so an empty result here is the strong direction.
    """
    import subprocess
    import tempfile

    img, pe = _image()
    tmp = tempfile.mkdtemp(prefix="giten-imm-")
    try:
        p = os.path.join(tmp, "img.exe")
        with open(p, "wb") as fh:
            fh.write(img)
        out = subprocess.run(["objdump", "-d", "-M", "intel", p],
                             check=True, capture_output=True, text=True).stdout
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    want = tuple("0x%x" % v for v in values)
    return [ln for ln in out.splitlines()
            if "\t" in ln and any(w in ln.split("\t")[-1] for w in want)]


def file_id(rel: str) -> "int | None":
    """``m/MS6F00.BIN`` -> ``0x6F00``; ``None`` for anything not in that family."""
    name = os.path.basename(rel).upper()
    if not (rel.startswith("m/") and name.startswith("MS") and name.endswith(".BIN")):
        return None
    try:
        return int(name[2:-4], 16)
    except ValueError:
        return None
