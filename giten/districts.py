"""The district-name table in ``et/ET000D.BIN``.

The name in the location strip -- 新宿, 高田馬場, 代々木公園 -- comes from here,
and until 2026-09-10 nothing in the pipeline read this file at all.  It is the
largest single visible defect in the patch: measured against two recorded play
sessions it accounted for **60% and 92%** of every Japanese character that
reached the screen (``docs/screen-audit.md``).

**The loader**, ``0x00412020``, opens file id ``0x0D`` of the ``et`` family and
calls ``0x00401C30`` exactly **twice**, storing the two handles::

    container 0   2829 bytes   binary: a map -> district index lookup
    container 1   1861 bytes   221 district names

so the container count is fixed at two, and container 0 is copied through
untouched.  Container 1 is the ordinary ``et`` string-table shape, identical to
the race tables in :mod:`giten.racenames`::

    u16 count = 221; u16 offset[count]; count NUL-terminated Shift-JIS strings

**The accessor**, ``0x00412140``, takes a district index, resolves it through
``0x00404680`` and ``0x0040B840`` the same way the race accessors do, then
**strcpy's the result into a fixed buffer at ``ds:0x00491340``** and returns
that pointer.  Its one caller, ``0x00412133``, gets the index out of container
0 by map.

Two consequences, and the second is why this module is careful:

* Because ``0x00401C30`` sizes its allocation from the container's own ``u16``
  header, container 1 is self-sizing.  The only structural ceiling is the u16
  offset mask in ``0x0040B840`` -- 65,535 bytes against a current 1,861.  No exe
  patch is needed.
* **The copy at ``0x00412140`` has no length limit.**  ``0x00491340`` is not a
  dedicated buffer -- 264 instructions reference it, and it is general string
  scratch.  Its size is nonetheless pinned: ``0x00403A0C`` hands the same
  address to ``0x00449710``, which passes it to a Win32 import together with
  ``0x100`` as the buffer length.  **So the buffer is 256 bytes**, and a
  district name cannot overrun it at any plausible length.

The remaining constraint is therefore purely visual -- how wide the strip is on
screen -- and that is *not* established.  The widest thing the game draws there
itself is 代々木公園, ten half-width cells.  :data:`BUDGET` is set slightly above
that, at twelve, which is what keeps ordinary romanisations intact
(Takadanobaba, Kasumigaseki, Shirokanedai) instead of truncating them to
nonsense.  If the strip turns out to clip, lower this one constant; nothing
else changes, and the failure mode is cosmetic and immediately visible.
"""
from __future__ import annotations

import os
import struct

from . import container, paths

TABLE = os.path.join(paths.REPO_ROOT, "tables", "districts.tsv")

REL = "et/ET000D.BIN"

#: the loader calls 0x00401C30 exactly twice
CONTAINERS = 2

#: the string table; container 0 is binary and is carried through verbatim
STRINGS = 1

#: half-width cells.  Two above the widest name the game draws itself; the
#: 256-byte buffer is not the limit, the strip's on-screen width is, and that
#: has not been measured.  See the module docstring.
BUDGET = 12

#: 0x0040B840 masks the offset to 16 bits
CONTAINER_MAX = 0xFFFF

TABLE_HEADER = ("index", "jp", "en", "status", "note")


class DistrictError(RuntimeError):
    pass


def cells(s: str) -> int:
    """Display width in half-width cells."""
    return sum(1 if (ord(c) < 0x80 or 0xFF61 <= ord(c) <= 0xFF9F) else 2 for c in s)


def source(ddswin: str = None) -> bytes:
    root = ddswin or paths.ORIGINAL_DDSWIN
    return open(os.path.join(root, *REL.split("/")), "rb").read()


def split_table(body: bytes) -> "list[str]":
    n = struct.unpack_from("<H", body, 0)[0]
    offs = struct.unpack_from("<%dH" % n, body, 2)
    if offs[0] != 2 + 2 * n:
        raise DistrictError("offset[0] is %d, expected %d" % (offs[0], 2 + 2 * n))
    out = []
    for o in offs:
        e = body.find(b"\x00", o)
        if e < 0:
            raise DistrictError("unterminated string at %d" % o)
        out.append(body[o:e].decode("cp932"))
    return out


def join_table(strings: "list[str]") -> bytes:
    n = len(strings)
    body = bytearray(struct.pack("<H", n) + b"\x00" * (2 * n))
    for i, s in enumerate(strings):
        if len(body) > CONTAINER_MAX:
            raise DistrictError("string %d starts at %d; the u16 offsets stop at %d"
                                % (i, len(body), CONTAINER_MAX))
        struct.pack_into("<H", body, 2 + 2 * i, len(body))
        body += s.encode("cp932") + b"\x00"
    if len(body) > CONTAINER_MAX:
        raise DistrictError("container is %d bytes, the u16 offsets stop at %d"
                            % (len(body), CONTAINER_MAX))
    return bytes(body)


def parse(raw: bytes) -> "list[str]":
    cs = container.split(raw)[0]
    if len(cs) != CONTAINERS:
        raise DistrictError("%s has %d containers, the loader reads %d"
                            % (REL, len(cs), CONTAINERS))
    return split_table(cs[STRINGS].body)


def read_table(path: str = TABLE) -> "dict[int, str]":
    out = {}
    if not os.path.exists(path):
        return out
    for ln in open(path, encoding="utf-8"):
        if ln.startswith("#") or not ln.strip():
            continue
        f = ln.rstrip("\n").split("\t")
        if len(f) < 3 or f[0] == "index":
            continue
        if f[2].strip():
            out[int(f[0])] = f[2]
    return out


def write_table(raw: bytes, path: str = TABLE) -> int:
    """Refresh the TSV from the original, keeping any English already in it."""
    have = read_table(path)
    names = parse(raw)
    lines = ["# Giten district names (et/ET000D.BIN container 1) -- the location strip",
             "# Edit the 'en' column.  Leave it empty to keep the Japanese.",
             "# Budget %d half-width cells; see giten/districts.py for why that is"
             " conservative." % BUDGET,
             "\t".join(TABLE_HEADER)]
    for i, jp in enumerate(names):
        lines.append("\t".join([str(i), jp, have.get(i, ""), "", ""]))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return len(names)


def plan(raw: bytes, english: "dict[int, str]"):
    """``(replacement strings, findings)`` after the width and codec checks."""
    names = list(parse(raw))
    findings = []
    for i, en in sorted(english.items()):
        if not (0 <= i < len(names)):
            findings.append((i, "no such district; the table has %d" % len(names)))
            continue
        if not en:
            continue
        if cells(en) > BUDGET:
            findings.append((i, "%d cells, budget is %d: %r" % (cells(en), BUDGET, en)))
            continue
        try:
            en.encode("cp932")
        except UnicodeEncodeError:
            findings.append((i, "not cp932-encodable: %r" % en))
            continue
        names[i] = en
    return names, findings


def build(raw: bytes, english: "dict[int, str]" = None) -> bytes:
    """The original file with container 1 rebuilt in English.

    Container 0 is copied byte-for-byte and the container count is unchanged,
    because the loader hard-codes two reads.
    """
    english = read_table() if english is None else english
    names, findings = plan(raw, english)
    if findings:
        raise DistrictError("districts: %s" % findings[:3])
    cs = container.split(raw)[0]
    bodies = [c.body for c in cs]
    bodies[STRINGS] = join_table(names)
    return container.join(bodies)
