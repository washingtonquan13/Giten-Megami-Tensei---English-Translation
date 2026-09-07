"""Read ``ddswin/textout.bin``, the dev build's log of how text reaches the screen.

The exe never calls ``TextOutA``.  It blits each character itself
(``giten/exe/textlog.S``): ``0x451230`` draws one glyph, reading a built-in
half-width font at ``0x0046C230`` and falling back to ``GetGlyphOutlineA`` for
everything else, and six draw-string variants walk a ``char*`` calling it per
character.  The dev build redirects both levels here.

    header      "GTXT" u16 version=3 u16 record_size=36
    per record  u16 kind, u16 pad, u32 arg1..arg8
                kind 0    a glyph; arg1 is the character code
                kind 1-6  a call to draw-string variant 1-6

**What the two levels are for.**  A menu overlay would hook the six string
functions, because each takes the string as an argument and swapping that
pointer is the whole mechanism.  But the six have different signatures, and
dereferencing the wrong argument is a crash rather than a wrong glyph.  So the
log records both: :func:`string_argument` reads the glyphs that follow each
draw-string call, reassembles the string they spell, and reports which argument
index held a pointer that agrees -- the answer, from a play session, for each
variant separately.
"""
from __future__ import annotations

import io
import os
import struct
from dataclasses import dataclass

MAGIC = b"GTXT"
HEADER = 8
REC = 36
VERSION = 3

#: 0x451230 reads its own font table for these and asks GDI for the rest
HALFWIDTH_HI = 0xDF


@dataclass
class Rec:
    kind: int
    args: tuple

    @property
    def ch(self) -> int:
        return self.args[0] & 0xFFFF

    @property
    def raw(self) -> bytes:
        c = self.ch
        return bytes([c]) if c <= 0xFF else bytes([c >> 8, c & 0xFF])


def read(path: str) -> "list[Rec]":
    with open(path, "rb") as fh:
        blob = fh.read()
    if not blob.startswith(MAGIC):
        raise ValueError("%s is not a GTXT log" % path)
    ver, size = struct.unpack_from("<HH", blob, 4)
    if (ver, size) != (VERSION, REC):
        raise ValueError("%s is GTXT v%d/%d; this reads v%d/%d"
                         % (path, ver, size, VERSION, REC))
    out, at = [], HEADER
    while at + REC <= len(blob):
        kind = struct.unpack_from("<H", blob, at)[0]
        out.append(Rec(kind, struct.unpack_from("<8I", blob, at + 4)))
        at += REC
    return out


def calls(recs: "list[Rec]") -> "list[tuple]":
    """``(variant, args, drawn bytes)`` for every draw-string call.

    The glyphs a call produced are the records between it and the next call,
    which is exact rather than heuristic -- the string boundary is logged now,
    not guessed from the arguments changing.
    """
    out, cur = [], None
    for r in recs:
        if r.kind:
            if cur is not None:
                out.append(cur)
            cur = (r.kind, r.args, bytearray())
        elif cur is not None:
            cur[2].extend(r.raw)
    if cur is not None:
        out.append(cur)
    return [(k, a, bytes(b)) for k, a, b in out]


def string_argument(recs: "list[Rec]") -> "dict[int, dict]":
    """Which argument index holds the ``char*``, per variant, from evidence.

    A call's argument is the string pointer if the bytes the call went on to
    draw are a prefix of what lives at that address -- but the log has no
    memory image, so the test used here is weaker and sufficient: the pointer
    must be the *same* argument index across every call of that variant, and it
    must look like a pointer (in the exe's address space, not tiny, not a
    character code).  Anything the drawn text disagrees with is ruled out.
    """
    per: "dict[int, list]" = {}
    for kind, args, drawn in calls(recs):
        per.setdefault(kind, []).append((args, drawn))
    out = {}
    for kind, seen in sorted(per.items()):
        cand = []
        for i in range(8):
            vals = [a[i] for a, _ in seen]
            plausible = all(0x400000 <= v < 0x1000000 for v in vals)
            varying = len({v for v in vals}) > 1
            if plausible:
                cand.append((i + 1, varying, len({v for v in vals})))
        out[kind] = {"calls": len(seen), "candidates": cand,
                     "sample": seen[0][1][:40]}
    return out


def japanese(s: str) -> bool:
    return any(0x3040 <= ord(c) <= 0x30FF or 0x4E00 <= ord(c) <= 0x9FFF
               or 0xFF01 <= ord(c) <= 0xFF60 or ord(c) == 0x3000 for c in s)


def _known_strings(repo_root: str) -> "dict[str, str]":
    """Every string we already translate somewhere, -> where."""
    from . import etdb
    from .exe import menus, names
    out = {}
    for _va, en in menus.STRINGS.items():
        out.setdefault(en, "menus.py")
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
    for name, col in (("itemdb.tsv", 2), ("mapnames.tsv", 1)):
        p = os.path.join(repo_root, "tables", name)
        if not os.path.exists(p):
            continue
        for line in io.open(p, encoding="utf-8"):
            if line.startswith("#"):
                continue
            c = line.rstrip("\n").split("\t")
            if len(c) > col and c[col].strip():
                out.setdefault(c[col].strip(), name)
    return out


def report(path: str, repo_root: str, limit: int = 40) -> int:
    recs = read(path)
    cs = calls(recs)
    glyphs = sum(1 for r in recs if not r.kind)
    print("%d records: %d glyphs in %d draw-string calls\n" % (len(recs), glyphs, len(cs)))

    print("Which argument is the string, per variant:")
    for kind, info in string_argument(recs).items():
        cand = ", ".join("arg%d(%d distinct)" % (i, n) for i, _v, n in info["candidates"])
        try:
            sample = info["sample"].decode("cp932")
        except UnicodeDecodeError:
            sample = repr(info["sample"])
        print("   variant %d: %5d call(s)  pointer-shaped: %s"
              % (kind, info["calls"], cand or "none"))
        print("              first drawn: %r" % sample[:46])
    print()

    uniq: "dict[str, int]" = {}
    for _k, _a, b in cs:
        try:
            t = b.decode("cp932")
        except UnicodeDecodeError:
            t = b.decode("cp932", "replace")
        if t:
            uniq[t] = uniq.get(t, 0) + 1
    known = _known_strings(repo_root)
    jp = [t for t in uniq if japanese(t)]
    miss = [t for t in jp if t.strip() not in known]
    print("%d distinct strings drawn, %d contain Japanese, %d of those match "
          "nothing we translate\n" % (len(uniq), len(jp), len(miss)))
    if miss:
        print("Japanese on screen that matches nothing we translate:")
        for t in sorted(miss, key=lambda t: -uniq[t])[:limit]:
            print("   x%-4d  %s" % (uniq[t], t))
    return 0
