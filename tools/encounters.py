"""Where does a demon spawn, what does it drop, and where do I farm it?

    python tools/encounters.py cassiel          # every place this demon spawns
    python tools/encounters.py P2065            # or the record id
    python tools/encounters.py --area roppongi  # the encounter list of one area
    python tools/encounters.py --area 22        # or the area (chunk) number
    python tools/encounters.py --drops topaz    # who drops it, and where to fight them
    python tools/encounters.py --drops 167      # or the et/ET0001.BIN item index
    python tools/encounters.py --areas          # every area, one line each

Reads the tables `docs/encounters.md` documents.  Three files answer the whole
question and they are addressed the same way -- by the player's world position:

* `et/ET1<aa>.BIN`  one 288x200 **area** of the world, 45 cells of 13 bytes,
                    each cell naming an encounter group and a chance byte
* `et/ET0021.BIN`   53 encounter groups of six demons, plus 8 weight profiles
* `et/ET000D.BIN` container 0
                    the same 45-cell grid, holding the district index the
                    location strip draws -- so the encounter table and the name
                    the player reads come out of one lookup

**Two warnings the data itself will not give you.**  The `p/P####.BIN` drop
field is `+0x32` (one item) with the rate at `+0x67`; `+0x34` is the demon's
*species* id, not an item, and it collides numerically with real item indices --
reading `+0x22`..`+0x34` as a drop list makes Jinn "drop" Topaz (its species id
is 167) and Vile "drop" Diamond (species 172).  And a demon can carry an item
and never be fightable, in two different ways: seven of the ten Topaz/Diamond
carriers are in no encounter group at all, and two more are in groups that no
area's cells name (`docs/encounters.md` section 4.1).  `--drops` separates the
three cases rather than lumping them as "boss".

Both corrections are checked against the engine in `docs/encounters.md` sections
5 and 6.  Japanese names come from `original/ddswin`; English ones from
`tables/` (districts) and from the installed play build (demons, items), so a
name printed here is a name on screen.
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

#: world geometry: an area is 288 x 200, its cells 32 x 40, 9 across and 5 down
AREA_W, AREA_H, CELL_W, CELL_H, GRID_W, GRID_H = 288, 200, 32, 40, 9, 5
CELLS = GRID_W * GRID_H
STRIDE = 13                              # bytes per cell in et/ET1<aa>.BIN

NAME, LEVEL, DROP_ITEM, DROP_RATE, SPECIES = 0x36, 0x47, 0x32, 0x67, 0x34


# --- loading ----------------------------------------------------------------
def _plain(path):
    """One container body, **not** decrypted.

    `0x00401D40` -- the reader every table in this module goes through -- reads
    the header word and `fread`s the body straight into the buffer, with no call
    to the cipher (`0x00401B20`/`0x00401BA0`, which `0x00401C30` does make).  So
    these files are stored in the clear and `giten.container.split` mis-reads
    them; that is a property of the loader, not of the file family.
    """
    raw = open(path, "rb").read()
    out, p = [], 0
    while p + 2 <= len(raw):
        n = struct.unpack_from("<H", raw, p)[0]
        if not n:
            break
        out.append(raw[p + 2:p + 2 + n])
        p += 2 + n
    return out


def groups():
    """``([53 tuples of 6 record ids], [8 weight rows])`` from `et/ET0021.BIN`."""
    c = _plain(os.path.join(paths.ORIGINAL_DDSWIN, "et", "ET0021.BIN"))
    g = [tuple(0x2000 + v for v in struct.unpack_from("<6H", c[0], i * 12))
         for i in range(len(c[0]) // 12)]
    w = [list(c[1][i * 6:i * 6 + 6]) for i in range(len(c[1]) // 6)]
    return g, w


class Cell:
    """One 32x40 patch of the world: two conditional encounter entries."""

    __slots__ = ("bg", "entries")

    def __init__(self, b):
        self.bg = b[0]
        self.entries = []
        for k in (1, 7):
            self.entries.append({
                "cond": struct.unpack_from("<H", b, k)[0],
                "rate": b[k + 2],
                "count": b[k + 3],
                "weights": b[k + 4],
                "group": b[k + 5],
            })

    def active(self):
        """The entry the engine would use with no story flag set.

        `0x004110A5` tests entry 0's condition word through `0x00439420` and
        falls through to entry 1 only if it fails.  A condition word of 0 is
        bank 0 bit 0, which `0x004392B0` answers 0 for unconditionally, and
        `0x00439420` returns *true* for a clear flag -- so a 0 word means "no
        condition" and entry 0 wins.  A non-zero word is a real story flag and
        which entry is live depends on the save; both are reported.
        """
        return self.entries[0] if self.entries[0]["cond"] == 0 else None


def areas():
    """``{area number: [Cell] * 45}`` for every `et/ET1<aa>.BIN`."""
    out = {}
    for p in sorted(glob.glob(os.path.join(paths.ORIGINAL_DDSWIN, "et", "ET10*.BIN"))):
        n = int(os.path.basename(p)[2:6], 16) - 0x1000
        body = _plain(p)[0]
        if len(body) < CELLS * STRIDE:
            continue
        out[n] = [Cell(body[i * STRIDE:(i + 1) * STRIDE]) for i in range(CELLS)]
    return out


def districts():
    """``({area: [45 district indices]}, [names])`` from `et/ET000D.BIN`.

    Container 0 is ``u16 count; u16 offset[count]; grids``, and `0x004120B0`
    indexes the offset table at **2 x the area number**, then reads
    ``grid[cellx + 9 * celly]``.  Container 1 is the ordinary `et` string table.
    """
    c = container.split(open(os.path.join(paths.ORIGINAL_DDSWIN, "et",
                                          "ET000D.BIN"), "rb").read())[0]
    c0, c1 = c[0].body, c[1].body
    n = struct.unpack_from("<H", c0, 0)[0]
    offs = [struct.unpack_from("<H", c0, 2 + 2 * i)[0] for i in range(n)]
    m = struct.unpack_from("<H", c1, 0)[0]
    names = []
    for i in range(m):
        o = struct.unpack_from("<H", c1, 2 + 2 * i)[0]
        names.append(c1[o:c1.find(b"\0", o)].decode("cp932", "replace"))
    grids = {}
    for a in range(n // 2):
        o = offs[2 * a]
        if o + CELLS <= len(c0):
            grids[a] = list(c0[o:o + CELLS])
    return grids, names


def _tsv(rel, key, val):
    out = {}
    p = os.path.join(R, rel)
    if not os.path.exists(p):
        return out
    for ln in open(p, encoding="utf-8"):
        if ln.startswith("#") or not ln.strip():
            continue
        f = ln.rstrip("\n").split("\t")
        if len(f) > max(key, val) and f[val].strip():
            out[f[key].strip()] = f[val].strip()
    return out


def english_districts():
    """``{japanese: english}`` from `tables/districts.tsv` (index, jp, en)."""
    t = _tsv("tables/districts.tsv", 1, 2)
    t.pop("jp", None)
    return t


def demons():
    """``({record id: body}, {record id: English name})``.

    English names come from the installed play build when there is one beside
    the repo, the same way `tools/demon.py` finds them, so a name printed here
    is the name on the player's screen.
    """
    out, en = {}, {}
    root = os.path.join(os.path.dirname(paths.REPO_ROOT), "play", "en", "ddswin")
    for p in sorted(glob.glob(os.path.join(paths.ORIGINAL_DDSWIN, "p", "*.BIN"))):
        b = container.split(open(p, "rb").read())[0][0].body
        if len(b) < 0x7A:
            continue
        rid = int(os.path.basename(p)[1:-4], 16)
        out[rid] = b
        q = os.path.join(root, "p", os.path.basename(p))
        if os.path.exists(q):
            eb = container.split(open(q, "rb").read())[0][0].body
            if len(eb) >= 0x7A and dname(eb) != dname(b):
                en[rid] = dname(eb)
    return out, en


def items():
    recs = itemdb.parse(itemdb.source_body(paths.ORIGINAL_DDSWIN))
    out = {}
    for i, r in enumerate(recs):
        n = r.name
        out[i] = n.decode("cp932", "replace") if isinstance(n, bytes) else (n or "")
    en = _tsv("tables/itemdb.tsv", 0, 3)
    return out, en


def dname(b):
    return b[NAME:NAME + 26].split(b"\0")[0].decode("cp932", "replace")


# --- the joins --------------------------------------------------------------
class World:
    def __init__(self):
        self.groups, self.weights = groups()
        self.areas = areas()
        self.dgrid, self.dnames = districts()
        self.den = english_districts()
        self.demons, self.demons_en = demons()
        self.items, self.iten = items()
        self.mapnames = _tsv("tables/mapnames.tsv", 1, 2)

    def demon_label(self, rid):
        b = self.demons[rid]
        en = self.demons_en.get(rid)
        return "%s (%s)" % (en, dname(b)) if en else dname(b)

    def district(self, area, cell):
        g = self.dgrid.get(area)
        if not g or cell >= len(g):
            return ""
        jp = self.dnames[g[cell]] if g[cell] < len(self.dnames) else ""
        jp = jp.strip("　 ")
        if not jp:
            return ""
        return self.den.get(jp, jp)

    def area_districts(self, area):
        """Every named district inside one area, in cell order, deduplicated."""
        seen, out = set(), []
        for c in range(CELLS):
            d = self.district(area, c)
            if d and d not in seen:
                seen.add(d)
                out.append(d)
        return out

    def area_label(self, area):
        d = self.area_districts(area)
        head = ", ".join(d[:4]) + (" ..." if len(d) > 4 else "")
        return "area %2d (x %4d-%4d, y %4d-%4d)  %s" % (
            area, (area % 8) * AREA_W, (area % 8) * AREA_W + AREA_W - 1,
            (area // 8) * AREA_H, (area // 8) * AREA_H + AREA_H - 1, head or "-")

    def group_use(self):
        """``{group index: {area: {"cells": n, "rate": r, "cond": c, "entry": i}}}``."""
        use = {}
        for a, cells in self.areas.items():
            for ci, cell in enumerate(cells):
                for ei, e in enumerate(cell.entries):
                    if e["group"] == 0 and e["cond"] == 0 and ei == 1:
                        pass            # still record it; group 0 is a real group
                    rec = use.setdefault(e["group"], {}).setdefault(
                        (a, ei), {"cells": 0, "rate": e["rate"],
                                  "cond": e["cond"], "weights": e["weights"]})
                    rec["cells"] += 1
        return use

    def live_groups(self):
        """Group indices some area's cells actually name.

        16 of the 53 groups in `et/ET0021.BIN` are named by no cell of any
        area -- see `docs/encounters.md` section 6.  A demon that is only in one
        of those is in the table and still unreachable through this path.
        """
        return {e["group"] for cells in self.areas.values()
                for c in cells for e in c.entries}

    def demon_places(self, rid):
        """``[(area, entry, slot, weight%, rate%, cells)]`` for one demon."""
        out = []
        use = self.group_use()
        for gi, row in enumerate(self.groups):
            for slot, v in enumerate(row):
                if v != rid:
                    continue
                for (a, ei), rec in sorted(use.get(gi, {}).items()):
                    w = self.weights[rec["weights"]] if rec["weights"] < len(self.weights) else [0] * 6
                    out.append((a, ei, gi, slot, w[slot], rec["rate"],
                                rec["cells"], rec["cond"]))
        return out


# --- printing ---------------------------------------------------------------
def show_demon(w, rid, out):
    b = w.demons[rid]
    item = struct.unpack_from("<H", b, DROP_ITEM)[0]
    out.write("P%04X  %s   Lv %d\n" % (rid, dname(b), b[LEVEL]))
    if item:
        out.write("   drops %s (item %d) at %d%%\n"
                  % (w.iten.get(str(item), w.items.get(item, "?")), item, b[DROP_RATE]))
    else:
        out.write("   drops nothing\n")
    places = w.demon_places(rid)
    if not places:
        gs = [g for g, row in enumerate(w.groups) if rid in row]
        out.write("   in no random encounter: %s\n\n"
                  % ("groups %s, which no area's cells reference" % gs if gs
                     else "member of no encounter group at all (scripted / boss only)"))
        return
    for a, ei, gi, slot, wt, rate, cells, cond in places:
        out.write("   %s\n" % w.area_label(a))
        out.write("      group %d slot %d, weight %d/100, chance byte %d, %d/%d cells%s\n"
                  % (gi, slot, wt, rate, cells, CELLS,
                     "" if cond == 0 else ", only while story flag %d:%d is clear"
                     % (cond & 0x7F, cond >> 8)))
    out.write("\n")


def show_area(w, a, out):
    out.write("%s\n" % w.area_label(a))
    out.write("   districts: %s\n" % ", ".join(w.area_districts(a)))
    seen = {}
    for ci, cell in enumerate(w.areas[a]):
        key = tuple((e["cond"], e["rate"], e["count"], e["weights"], e["group"])
                    for e in cell.entries)
        seen.setdefault(key, []).append(ci)
    for key, cs in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        out.write("   %d cells:\n" % len(cs))
        for ei, (cond, rate, count, wi, gi) in enumerate(key):
            if cond == 0:
                tag = ("always" if ei == 0
                       else "DEAD: entry 0 is unconditional, so this is never reached")
            else:
                tag = "%swhile flag %d:%d is clear" % ("" if ei == 0 else "fallback, ",
                                                       cond & 0x7F, cond >> 8)
            out.write("      entry %d (%s): group %d, chance byte %d, +%d enemies, weights %s\n"
                      % (ei, tag, gi, rate, count,
                         w.weights[wi] if wi < len(w.weights) else "?"))
            for slot, rid in enumerate(w.groups[gi] if gi < len(w.groups) else ()):
                b = w.demons.get(rid)
                if not b:
                    continue
                it = struct.unpack_from("<H", b, DROP_ITEM)[0]
                wt = w.weights[wi][slot] if wi < len(w.weights) else 0
                out.write("         %2d%%  P%04X Lv%-3d %-18s %s\n"
                          % (wt, rid, b[LEVEL], w.demon_label(rid),
                             ("drops %s %d%%" % (w.iten.get(str(it), w.items.get(it, "?")),
                                                 b[DROP_RATE])) if it else ""))
    out.write("\n")


def show_drops(w, idx, out):
    label = w.iten.get(str(idx), w.items.get(idx, "?"))
    out.write("%s (et/ET0001.BIN index %d)\n\n" % (label, idx))
    carriers = [(rid, b) for rid, b in sorted(w.demons.items())
                if struct.unpack_from("<H", b, DROP_ITEM)[0] == idx]
    if not carriers:
        out.write("   no demon carries it -- shop, chest or script only\n")
        return
    live = w.live_groups()
    farmable, stranded, boss = [], [], []
    for rid, b in carriers:
        gs = [g for g, row in enumerate(w.groups) if rid in row]
        if any(g in live for g in gs):
            farmable.append((rid, b))
        elif gs:
            stranded.append((rid, b, gs))
        else:
            boss.append((rid, b))

    out.write("=== repeatable: fight these ===\n")
    for rid, b in farmable:
        show_demon(w, rid, out)
    if not farmable:
        out.write("   none -- no random encounter in the game yields this item\n\n")

    if stranded:
        out.write("=== in an encounter group no area's cells reference ===\n")
        for rid, b, gs in stranded:
            out.write("   P%04X Lv%-3d %-18s %3d%%   groups %s (unused)\n"
                      % (rid, b[LEVEL], w.demon_label(rid), b[DROP_RATE], gs))
    if boss:
        out.write("=== in no encounter group at all -- scripted / boss only ===\n")
        for rid, b in boss:
            out.write("   P%04X Lv%-3d %-18s %3d%%\n"
                      % (rid, b[LEVEL], w.demon_label(rid), b[DROP_RATE]))


def main(argv):
    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if not argv:
        raise SystemExit(__doc__.split("\n\n")[1])
    w = World()

    if argv[0] == "--areas":
        for a in sorted(w.areas):
            out.write("%s\n" % w.area_label(a))
        out.flush()
        return

    if argv[0] == "--area":
        q = argv[1]
        if q.isdigit():
            hits = [int(q)]
        else:
            ql = q.lower()
            hits = [a for a in sorted(w.areas)
                    if any(ql in d.lower() for d in w.area_districts(a))]
        if not hits:
            out.write("no area matches %r\n" % q)
        for a in hits:
            show_area(w, a, out)
        out.flush()
        return

    if argv[0] == "--drops":
        q = argv[1]
        if q.isdigit():
            idxs = [int(q)]
        else:
            ql = q.lower()
            idxs = [i for i, n in w.items.items()
                    if ql in n.lower() or ql in w.iten.get(str(i), "").lower()]
        if not idxs:
            out.write("no item matches %r\n" % q)
        for i in idxs:
            show_drops(w, i, out)
        out.flush()
        return

    q = argv[0].lower()
    found = 0
    for rid, b in sorted(w.demons.items()):
        if q in ("p%04x" % rid).lower() or q in w.demon_label(rid).lower():
            show_demon(w, rid, out)
            found += 1
    if not found:
        out.write("no demon matches %r\n" % argv[0])
    out.flush()


if __name__ == "__main__":
    main(sys.argv[1:])
