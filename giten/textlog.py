"""Read ``ddswin/textout.bin``, the dev build's log of every glyph drawn.

The exe never calls ``TextOutA``.  It blits each character itself
(``giten/exe/textlog.S``): ``0x451230`` draws one glyph, reading a built-in
half-width font at ``0x0046C230`` and falling back to ``GetGlyphOutlineA`` for
everything else, and six draw-string variants walk a ``char*`` calling it per
character.  The dev build redirects those six ``call`` sites here.

    header      "GTXT" u16 version=2 u16 record_size=20
    per glyph   u32 arg1..arg5, exactly as the caller pushed them

``arg1`` is the character code.  The rest are logged raw because ``0x451230``
only reads arg1 and arg3, and naming the others would be a guess -- :func:`report`
prints their distinct values so the next pass can name them from evidence.

What this is for: deciding whether a hook on those six string functions could
replace the 117 pointer rewrites ``names.py`` and ``menus.py`` make.  Each takes
the string as an argument, so the mechanism would be to swap the pointer.  The
question this answers is whether everything we currently patch actually flows
through them, and what Japanese reaches the screen that we have no table for.
"""
from __future__ import annotations

import io
import os
import struct
from dataclasses import dataclass

MAGIC = b"GTXT"
HEADER = 8
REC = 20

#: half-width codes below this are ASCII; the engine's own font table covers
#: 0x20..0xDF, and anything else came back from GetGlyphOutlineA
HALFWIDTH_HI = 0xDF


@dataclass
class Glyph:
    args: tuple

    @property
    def ch(self) -> int:
        return self.args[0] & 0xFFFF

    @property
    def raw(self) -> bytes:
        c = self.ch
        return bytes([c]) if c <= 0xFF else bytes([c >> 8, c & 0xFF])


def read(path: str) -> "list[Glyph]":
    with open(path, "rb") as fh:
        blob = fh.read()
    if not blob.startswith(MAGIC):
        raise ValueError("%s is not a GTXT log" % path)
    ver, size = struct.unpack_from("<HH", blob, 4)
    if ver != 2 or size != REC:
        raise ValueError("%s is GTXT v%d/%d, this reads v2/%d" % (path, ver, size, REC))
    out, at = [], HEADER
    while at + REC <= len(blob):
        out.append(Glyph(struct.unpack_from("<5I", blob, at)))
        at += REC
    return out


def runs(glyphs: "list[Glyph]") -> "list[str]":
    """Rebuild on-screen strings from the character stream.

    A draw-string call emits its characters back to back, so a run ends when
    the arguments that are *not* the character stop agreeing -- a new call with
    a different destination or colour.  That is a heuristic, not a boundary the
    log records, so a run may merge two strings drawn identically in sequence.
    """
    out, cur, key = [], bytearray(), None
    for g in glyphs:
        k = g.args[1:]
        if key is not None and k != key and cur:
            out.append(bytes(cur))
            cur = bytearray()
        key = k
        cur += g.raw
    if cur:
        out.append(bytes(cur))
    dec = []
    for b in out:
        try:
            dec.append(b.decode("cp932"))
        except UnicodeDecodeError:
            dec.append(b.decode("cp932", "replace"))
    return dec


def japanese(s: str) -> bool:
    return any(0x3040 <= ord(c) <= 0x30FF or 0x4E00 <= ord(c) <= 0x9FFF
               or 0xFF01 <= ord(c) <= 0xFF60 or ord(c) == 0x3000 for c in s)


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
    glyphs = read(path)
    strings = runs(glyphs)
    uniq: "dict[str, int]" = {}
    for t in strings:
        uniq[t] = uniq.get(t, 0) + 1
    known = _known_strings(repo_root)

    jp = [t for t in uniq if japanese(t)]
    print("%d glyphs drawn, grouped into %d runs, %d distinct"
          % (len(glyphs), len(strings), len(uniq)))
    print("%d distinct runs still contain Japanese\n" % len(jp))

    hit = [t for t in jp if t.strip() in known]
    miss = [t for t in jp if t.strip() not in known]
    print("  of those, %d match something we already translate, %d do not"
          % (len(hit), len(miss)))
    print("  (a miss is a formatted template, a run the grouping merged, or "
          "text\n   nobody has found yet)\n")
    if miss:
        print("Japanese drawn on screen that matches nothing we translate:")
        for t in sorted(miss, key=lambda t: -uniq[t])[:limit]:
            print("   x%-4d  %s" % (uniq[t], t))
    print()
    seen = {}
    for i in range(1, 5):
        vals = {g.args[i] for g in glyphs}
        seen[i] = len(vals)
    print("distinct values per argument (arg1 is the character): %s"
          % ", ".join("arg%d=%d" % (i + 1, seen[i]) for i in range(1, 5)))
    return 0
