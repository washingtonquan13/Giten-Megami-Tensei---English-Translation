"""Look up a demon's stats, skills and resistances.

    python tools/demon.py dantalion          # match on our English name
    python tools/demon.py バエル              # or the Japanese
    python tools/demon.py P219D              # or the record id
    python tools/demon.py --weak-to 2        # everything weak to element 2

Reads `p/P####.BIN` and `et/ET0004.BIN` through the layout in
`docs/format-notes.md` §7.  Written after the third "what are X's stats?"
question in a row; every answer here had previously been produced by hand.

**The affinity row is the part worth reading.**  A skill's element index
(`ET0004 +0x0C`, 0..9) indexes the demon's ten-byte table at `+0x59`, so
`affinity = row[element]`, and 50 is neutral.  That one join answers "why did
that do nothing" faster than any amount of play-testing -- it is how Dantalion
II's immunity to Rakunda was found, and why guns beat spells against him.

Japanese names come from `original/ddswin`; English ones from the installed
build if there is one, so a name shown here is the name the player sees.
"""
from __future__ import annotations

import glob
import io
import os
import struct
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)

from giten import container, paths  # noqa: E402

#: what each affinity slot means; 3 and 6 are not individually pinned
#: Index 0 is "untyped": basic melee lands there, and so do heals and buffs,
#: which are ally-targeted and never consult the target's row at all.  Reading a
#: heal's "element 0" as physical is the one easy mistake this table invites.
ELEMENTS = ("untyped/melee", "gun", "fire", "(unpinned)", "wind",
            "electric", "(unpinned)", "ailment", "debuff", "death/mind")

HP, MP, LEVEL, NAME, SKILLS, AFFINITY = 0x0C, 0x0E, 0x47, 0x36, 0x10, 0x59


def _body(path):
    return container.split(open(path, "rb").read())[0][0].body


def skills_db():
    """``[record]`` for ET0004, indexed by skill id."""
    b = _body(os.path.join(paths.ORIGINAL_DDSWIN, "et", "ET0004.BIN"))
    n = struct.unpack_from("<H", b, 0)[0]
    offs = [struct.unpack_from("<H", b, 2 + 2 * i)[0] for i in range(n)]
    return [b[o:e] for o, e in zip(offs, offs[1:] + [len(b)])]


def name_of(rec: bytes) -> str:
    return rec[NAME:NAME + 26].split(b"\0")[0].decode("cp932", "replace")


def load_all():
    """``[(id, jp record, en record or None)]`` for every demon."""
    en_root = os.path.join(os.path.dirname(paths.REPO_ROOT), "play", "en", "ddswin")
    out = []
    for p in sorted(glob.glob(os.path.join(paths.ORIGINAL_DDSWIN, "p", "*.BIN"))):
        jp = _body(p)
        if len(jp) < 0x7A:
            continue
        q = os.path.join(en_root, "p", os.path.basename(p))
        en = _body(q) if os.path.exists(q) else None
        out.append((os.path.basename(p)[:-4], jp, en))
    return out


def describe(rid, jp, en, sk, out):
    hp, mp = struct.unpack_from("<HH", jp, HP)
    cash, mag = struct.unpack_from("<I", jp, 4)[0], struct.unpack_from("<I", jp, 8)[0]
    label = name_of(jp)
    if en is not None and name_of(en) != label:
        label = "%s  (%s)" % (name_of(en), label)
    out.write("%s  %s\n" % (rid, label))
    out.write("   Lv %-4d HP %-6d MP %-6d   cash %d, Magnetite %d\n"
              % (jp[LEVEL], hp, mp, cash, mag))

    ids = [struct.unpack_from("<H", jp, SKILLS + 2 * k)[0] for k in range(8)]
    if any(ids):
        out.write("   skills:\n")
        for i in ids:
            if not i or i >= len(sk):
                continue
            r = sk[i]
            nm = r[20:].split(b"\0")[0].decode("cp932", "replace")
            elem = r[0x0C]
            aff = jp[AFFINITY + elem] if elem < 10 else -1
            out.write("      %-16s id %-4d MP %-4d power %-4d element %d (%s)\n"
                      % (nm, i, r[0x03], r[0x0A], elem, ELEMENTS[elem] if elem < 10 else "?"))

    out.write("   affinities (50 = neutral):\n")
    for k in range(10):
        v = jp[AFFINITY + k]
        if v == 0:
            verdict = "IMMUNE"
        elif v in (253, 254, 255):
            verdict = "special (null / drain / repel)"
        elif v > 50:
            verdict = "WEAK -- %d%% damage" % (v * 2)
        elif v < 50:
            verdict = "resists -- %d%% damage" % (v * 2)
        else:
            verdict = "normal"
        out.write("      %d %-13s %3d   %s\n" % (k, ELEMENTS[k], v, verdict))
    out.write("\n")


def main(argv):
    if not argv:
        raise SystemExit("usage: demon.py <name | record id> | --weak-to <element>")
    sk = skills_db()
    rows = load_all()
    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    if argv[0] == "--weak-to":
        e = int(argv[1])
        hits = [(rid, jp) for rid, jp, _ in rows if jp[AFFINITY + e] > 50]
        out.write("%d demons weak to element %d (%s):\n" % (len(hits), e, ELEMENTS[e]))
        for rid, jp in sorted(hits, key=lambda r: r[1][LEVEL]):
            out.write("   %-7s Lv %-4d %-16s %d\n"
                      % (rid, jp[LEVEL], name_of(jp), jp[AFFINITY + e]))
        out.flush()
        return

    q = argv[0].lower()
    found = 0
    for rid, jp, en in rows:
        names = [rid.lower(), name_of(jp).lower()]
        if en is not None:
            names.append(name_of(en).lower())
        if any(q in n for n in names):
            describe(rid, jp, en, sk, out)
            found += 1
    if not found:
        out.write("no demon matches %r\n" % argv[0])
    out.flush()


if __name__ == "__main__":
    main(sys.argv[1:])
