"""Read ``ddswin/textout.bin``, the dev build's log of every string GDI drew.

``giten/exe/textlog.S`` records one entry per ``TextOutA`` call -- the only
text-drawing API the exe imports, reached from the only instruction that calls
it.  Written by the hook as::

    header      "GTXT" u16 version=1 u16 0
    per call    u16 n, i16 x, i16 y, then n bytes of cp932

What this is for: deciding whether a hook on that one call site could replace
the 117 pointer rewrites ``names.py`` and ``menus.py`` make, and the parser
hook in ``mapnames.py``.  Three questions, and :func:`report` answers each
directly against a play session rather than by reasoning about the binary:

* **Does everything we patch reach it?**  Any string we currently re-point that
  never appears here needs some other mechanism, so it has to be found now
  rather than after the pointer rewrites are gone.
* **In what form?**  A ``printf`` template is expanded before it is drawn, so
  the hook sees ``Total      1234`` and not ``合計 %10ld``.  Those cannot be
  matched by equality and are counted separately.
* **What did we never find?**  Japanese that shows up here and is in none of
  our tables is untranslated text nobody has spotted yet.
"""
from __future__ import annotations

import io
import os
import struct
from dataclasses import dataclass

MAGIC = b"GTXT"
HEADER = 8
REC = 6


@dataclass
class Draw:
    x: int
    y: int
    raw: bytes

    @property
    def text(self) -> str:
        try:
            return self.raw.decode("cp932")
        except UnicodeDecodeError:
            return self.raw.decode("cp932", "replace")

    @property
    def japanese(self) -> bool:
        return any(0x3040 <= ord(c) <= 0x30FF or 0x4E00 <= ord(c) <= 0x9FFF
                   or 0xFF01 <= ord(c) <= 0xFF60 or ord(c) == 0x3000
                   for c in self.text)


def read(path: str) -> "list[Draw]":
    with open(path, "rb") as fh:
        blob = fh.read()
    if not blob.startswith(MAGIC):
        raise ValueError("%s is not a GTXT log" % path)
    out, at = [], HEADER
    while at + REC <= len(blob):
        n, x, y = struct.unpack_from("<Hhh", blob, at)
        at += REC
        if at + n > len(blob):
            break                       # torn tail: the last call never finished
        out.append(Draw(x, y, blob[at:at + n]))
        at += n
    return out


def _known_strings(repo_root: str) -> "dict[str, str]":
    """Every Japanese string we already translate somewhere, -> where."""
    from . import etdb, tables
    from .exe import menus, names
    out = {}
    for va, en in menus.STRINGS.items():
        out.setdefault(en, "menus.py")          # keyed by the English we install
    for jp, en in menus.EFFECTS:
        out.setdefault(jp, "menus.py EFFECTS")
        out.setdefault(en, "menus.py EFFECTS")
    for jp, en in names.NAMES.items():
        out.setdefault(jp, "names.py")
        out.setdefault(en, "names.py")
    for spec in etdb.SPECS.values():
        for r in etdb.parse(spec, etdb.source(spec)):
            for i in range(spec.fields):
                if r.text(i):
                    out.setdefault(r.text(i), os.path.basename(spec.rel))
    itemtbl = os.path.join(repo_root, "tables", "itemdb.tsv")
    if os.path.exists(itemtbl):
        for line in io.open(itemtbl, encoding="utf-8"):
            if line.startswith("#"):
                continue
            c = line.rstrip("\n").split("\t")
            if len(c) > 4 and c[2].strip():
                out.setdefault(c[2].strip(), "itemdb")
    maptbl = os.path.join(repo_root, "tables", "mapnames.tsv")
    if os.path.exists(maptbl):
        for line in io.open(maptbl, encoding="utf-8"):
            if line.startswith("#"):
                continue
            c = line.rstrip("\n").split("\t")
            if len(c) > 2 and c[1].strip():
                out.setdefault(c[1].strip(), "mapnames")
    return out


def report(path: str, repo_root: str, limit: int = 40) -> int:
    draws = read(path)
    uniq: "dict[bytes, int]" = {}
    for d in draws:
        uniq[d.raw] = uniq.get(d.raw, 0) + 1
    known = _known_strings(repo_root)

    jp = [d for d in {d.raw: d for d in draws}.values() if d.japanese]
    print("%d TextOutA calls, %d distinct strings" % (len(draws), len(uniq)))
    print("%d distinct strings still contain Japanese\n" % len(jp))

    hit = [d for d in jp if d.text.strip() in known]
    miss = [d for d in jp if d.text.strip() not in known]
    print("  of those, %d are text we already have a table for, %d are not"
          % (len(hit), len(miss)))
    print("  (a miss is either a formatted template -- the hook sees the "
          "expanded\n   string, not the %-spec -- or text nobody has found yet)\n")

    if miss:
        print("Japanese drawn on screen that matches nothing we translate:")
        for d in sorted(miss, key=lambda d: -uniq[d.raw])[:limit]:
            print("   x=%-4d y=%-4d  x%-4d  %s" % (d.x, d.y, uniq[d.raw], d.text))
    return 0
