"""Look up a demon's stats, skills and resistances.

    python tools/demon.py dantalion          # match on our English name
    python tools/demon.py バエル              # or the Japanese
    python tools/demon.py P219D              # or the record id
    python tools/demon.py --weak-to 2        # everything weak to element 2
    python tools/demon.py --weapon kusanagi  # a weapon's requirements, by name
    python tools/demon.py --party            # the human party's base stats

Reads `p/P####.BIN` and `et/ET0004.BIN` through the layout in
`docs/format-notes.md` §7.  Written after the third "what are X's stats?"
question in a row; every answer here had previously been produced by hand.

**The affinity row is the part worth reading.**  A skill's element index
(`ET0004 +0x0C`, 0..9) indexes the demon's ten-byte table at `+0x59`, so
`affinity = row[element]`, and 50 is neutral.  That one join answers "why did
that do nothing" faster than any amount of play-testing -- it is how Dantalion
II's immunity to Rakunda was found, and why guns beat spells against him.

**The base stats** are record `+0x4C`..`+0x56`, eleven bytes in the order the
status screen draws them (`docs/format-notes.md` §9.1).  They are the *base*
value only: the engine sums base + equipment/gem bonuses and clamps to 1..100
before anything reads them, so a printed 15 can be an effective 18 in play.

``--weapon`` names the two equip-requirement bytes: requirement A is
**Vitality** and requirement B is **Dexterity** (§9).

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

from giten import container, itemdb, paths  # noqa: E402

#: the eleven base stats, in the order the status screen draws them
#: (`0x00442450` walks `unit+0xE0` on a 2-byte stride against the label
#: pointer array at `0x0046A118` on a 4-byte stride).  The status screen shows
#: the first ten; `Fate` exists in the array and in every record but is not
#: drawn.  English wording follows `giten/exe/menus.py`.
STATS = ("Intuition", "Willpower", "Magic", "Intelligence", "Blessing",
         "Strength", "Vitality", "Agility", "Dexterity", "Charisma", "Fate")
STATS_JP = ("直感", "精神力", "魔力", "知力", "加護",
            "強さ", "体力", "敏捷性", "器用さ", "魅力", "命運")
ABBR = ("IN", "WI", "MA", "IT", "BL", "ST", "VI", "AG", "DX", "CH", "FA")

#: the two item-record bytes the equip check at `0x0041BA4F` compares, and the
#: stat index each is compared against (`unit+0xEC` = 6 = Vitality,
#: `unit+0xF0` = 8 = Dexterity)
REQ_A, REQ_B = 17, 18
REQ_A_STAT, REQ_B_STAT = 6, 8

#: what each affinity slot means; 3 and 6 are not individually pinned
#: Index 0 is "untyped": basic melee lands there, and so do heals and buffs,
#: which are ally-targeted and never consult the target's row at all.  Reading a
#: heal's "element 0" as physical is the one easy mistake this table invites.
ELEMENTS = ("untyped/melee", "gun", "fire", "(unpinned)", "wind",
            "electric", "(unpinned)", "ailment", "debuff", "death/mind")

HP, MP, LEVEL, NAME, SKILLS, AFFINITY = 0x0C, 0x0E, 0x47, 0x36, 0x10, 0x59
BASE_STATS, SPECIES = 0x4C, 0x34


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


def base_stats(rec: bytes):
    """The eleven base stats of one `p/` record, in status-screen order."""
    return [rec[BASE_STATS + k] for k in range(len(STATS))]


def stat_line(rec: bytes) -> str:
    """One compact `IN=6 WI=7 ...` line."""
    return "  ".join("%s=%-3d" % (ABBR[k], v) for k, v in enumerate(base_stats(rec)))


def weapons_db():
    """Every equippable `et/ET0001.BIN` record (types 11 and 12)."""
    body = itemdb.source_body(paths.ORIGINAL_DDSWIN)
    return [r for r in itemdb.parse(body)
            if r.type in (11, 12) and r.name is not None]


def requirements(rec) -> tuple[int, int]:
    """``(Vitality, Dexterity)`` a unit needs to equip this item."""
    return rec.raw[REQ_A], rec.raw[REQ_B]


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

    st = base_stats(jp)
    out.write("   base stats (record +0x%02X; equipment and gems add on top,"
              " total clamped 1..100):\n" % BASE_STATS)
    for k, nm in enumerate(STATS):
        note = ""
        if k == REQ_A_STAT:
            note = "   <- weapon requirement A"
        elif k == REQ_B_STAT:
            note = "   <- weapon requirement B"
        elif k == 10:
            note = "   (not drawn on the status screen)"
        out.write("      %-13s %-5s %3d%s\n" % (nm, STATS_JP[k], st[k], note))

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


def describe_weapon(rec, rows, out):
    """One `et/ET0001.BIN` weapon: its two requirements, named, and who meets
    them on base stats alone."""
    a, b = requirements(rec)
    nm = rec.name.decode("cp932", "replace")
    kind = "melee (type 11)" if rec.type == 11 else "firearm (type 12)"
    out.write("%4d  %s   [%s]\n" % (rec.index, nm, kind))
    out.write("      requires  %-13s (%s) >= %-4d\n"
              % (STATS[REQ_A_STAT], STATS_JP[REQ_A_STAT], a))
    out.write("                %-13s (%s) >= %-4d\n"
              % (STATS[REQ_B_STAT], STATS_JP[REQ_B_STAT], b))
    if rec.type == 12:
        out.write("      firearm rule: the check first adds unit+0x132 to BOTH"
                  " stats when it is > 0\n"
                  "                    (0x0041BA1A), which is why gun"
                  " requirements run past 100.\n")
    ok = [(rid, jp) for rid, jp, _ in rows
          if struct.unpack_from("<H", jp, SPECIES)[0] < 0x20
          and base_stats(jp)[REQ_A_STAT] >= a and base_stats(jp)[REQ_B_STAT] >= b]
    out.write("      human party members who already qualify on base stats: %s\n"
              % (", ".join("%s (%s)" % (name_of(jp), rid) for rid, jp in ok) or "none"))
    out.write("\n")


def main(argv):
    if not argv:
        raise SystemExit("usage: demon.py <name | record id> | --weak-to <element>"
                         " | --weapon <name | index> | --party")
    sk = skills_db()
    rows = load_all()
    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    if argv[0] == "--party":
        out.write("human party members (species id < 0x20), base stats:\n")
        out.write("   %-8s %-4s %-16s %s\n"
                  % ("record", "Lv", "name", " ".join("%3s" % a for a in ABBR)))
        for rid, jp, _ in rows:
            if struct.unpack_from("<H", jp, SPECIES)[0] >= 0x20:
                continue
            nm = name_of(jp)
            pad = 16 - sum(2 if ord(c) > 0x7F else 1 for c in nm)
            out.write("   %-8s %-4d %s%s%s\n"
                      % (rid, jp[LEVEL], nm, " " * max(pad, 1),
                         " ".join("%3d" % v for v in base_stats(jp))))
        out.write("\n   %s = weapon requirement A, %s = weapon requirement B\n"
                  % (ABBR[REQ_A_STAT], ABBR[REQ_B_STAT]))
        out.flush()
        return

    if argv[0] == "--weapon":
        q = " ".join(argv[1:])
        hits = []
        for rec in weapons_db():
            nm = rec.name.decode("cp932", "replace")
            if q == str(rec.index) or (q and q in nm) or (q and q.lower() in nm.lower()):
                hits.append(rec)
        if not hits and q:
            # fall back to the installed English build's names, if there is one
            en = os.path.join(os.path.dirname(paths.REPO_ROOT), "play", "en",
                              "ddswin", "et", "ET0001.BIN")
            if os.path.exists(en):
                recs = itemdb.parse(_body(en))
                for rec in recs:
                    if rec.type in (11, 12) and rec.name is not None and \
                            q.lower() in rec.name.decode("cp932", "replace").lower():
                        hits.append(rec)
        if not hits:
            out.write("no weapon matches %r\n" % q)
        for rec in hits:
            describe_weapon(rec, rows, out)
        out.flush()
        return

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
