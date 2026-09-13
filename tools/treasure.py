"""Every treasure chest in the game, what is in it, and what opens it.

    python tools/treasure.py                  # every chest, grouped by map
    python tools/treasure.py --item diamond   # where is this item in a chest?
    python tools/treasure.py --item 172       # or the et/ET0001.BIN index
    python tools/treasure.py --map 0016       # one map file
    python tools/treasure.py --ornate         # only the moon-gated chests
    python tools/treasure.py --renewable      # the ones et/ET0019.BIN refills
    python tools/treasure.py --summary        # counts, and the gem chests

A chest is **not** a script grant, which is why `docs/encounters.md` section 13's
opcode scan could not see one.  It is a **map object**: `m/M####.BIN` carries,
per floor, a list of 16-byte entries keyed on the tile the player is standing
on, and the engine copies the matching entry to `ds:0x0047BB50` and runs the
script record the entry names.  Every chest in the game names `m/MS0037.BIN`,
which reads its own 16 bytes back through `1E AD`/`1E AC` -- so the contents are
in the map file, not in any script.  `docs/treasure.md` carries the evidence.

**The moon gate is real.**  `m/MS0037.BIN` r01 -- the 豪華な装飾を施した箱,
the ornate chest -- is the only one of the four entry records that runs a
`1F 17` switch on the 28-step lunar counter `ds:0x00491566`, and the only key
that gets past it is 15, i.e. counter 14, which is the extreme column of every
row of `et/ET0003.BIN`: the full moon.  Eighteen chests in the game are that
kind, and **`et/ET0019.BIN` is a 15-entry list of their "already opened" flags
that `0x00420E40` clears the moment the counter reaches 15** -- so thirteen
ornate chests and two pickups come back every lunar month.
"""
from __future__ import annotations

import argparse
import glob
import os
import struct
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)

from giten import container, itemdb, paths  # noqa: E402

#: `m/MS0037.BIN`, the chest script.  `0x00418200(5, 6)` runs
#: `file = entry[5], record = entry[6]` for every object of this list.
CHEST_FILE = 0x37

#: the floor header is 13 u16 absolute body offsets, one per object list;
#: index 10 is the one the engine reads as `floor+0x28`, stride 16.
OBJECT_LIST = 10
STRIDE = 16

#: `m/MS0037.BIN` entry records, by `entry[6]`
PRESENTATION = {
    0: "chest",              # r00  宝箱が置かれている
    1: "ornate chest",       # r01  豪華な装飾を施した箱 -- FULL MOON ONLY
    2: "pickup",             # r02  no prompt, no message
    3: "pickup",             # r03  no prompt, no message
}

#: `entry[7]`, read by `m/MS0037.BIN` r08 as `1E AC (offset 7, 1 byte)` and
#: switched with `1F 19` (first case >= key, `0x004327C0`): 0, 1, 2, else.
#: `r0F` then defaults a zero count to 1, so 0 is "one of this item".
KIND_ITEM, KIND_MACCA, KIND_MAG = 0, 1, 2

MAPNAMES = os.path.join(paths.REPO_ROOT, "tables", "mapnames.tsv")
ITEMTABLE = os.path.join(paths.REPO_ROOT, "tables", "itemdb.tsv")

#: `0x00420B50` loads `et/ET0019.BIN` with `0x00401D40` -- the **plaintext**
#: reader, so `docs/encounters.md` section 2.1 applies and `container.split`
#: must not be used on it.  `0x00420E40` walks it as `{u8 bank, u8 bit}` pairs
#: to a `0xFF` and clears each flag, and its one caller is `0x00420CF0`'s
#: `cmp ds:0x00491566, 0x0F` -- the step after the full moon.
RENEW_TABLE = "et/ET0019.BIN"


def renewable_flags(root: "str | None" = None) -> "set[int]":
    """The chest flags the full moon clears, as the same word the map stores."""
    root = root or paths.ORIGINAL_DDSWIN
    raw = open(os.path.join(root, "et", "ET0019.BIN"), "rb").read()[2:]
    out, i = set(), 0
    while i + 1 < len(raw) and raw[i] != 0xFF:
        out.add((raw[i + 1] << 8) | raw[i])
        i += 2
    return out


class Chest:
    __slots__ = ("map_id", "floor", "raw")

    def __init__(self, map_id, floor, raw):
        self.map_id, self.floor, self.raw = map_id, floor, raw

    x = property(lambda s: s.raw[0])
    y = property(lambda s: s.raw[1])
    obj_kind = property(lambda s: s.raw[2])
    value = property(lambda s: struct.unpack_from("<H", s.raw, 3)[0])
    record = property(lambda s: s.raw[6])
    count = property(lambda s: s.raw[7])
    #: `entry[11..12]`: the bank/bit word `m/MS0037.BIN` r04 tests and r10 sets
    #: -- the per-chest "already opened" flag.  Same shape as the encounter
    #: cell's condition word (`docs/encounters.md` section 3).
    flag = property(lambda s: struct.unpack_from("<H", s.raw, 11)[0])

    @property
    def moon_gated(self) -> bool:
        return self.record == 1

    @property
    def contents(self):
        """``(kind, index_or_amount, count)`` -- kind in {"item","macca","mag"}."""
        k = self.count
        if k == KIND_MACCA:
            return ("macca", self.value, 1)
        if k == KIND_MAG:
            return ("mag", self.value, 1)
        return ("item", self.value, max(k, 1))


# --- loading ----------------------------------------------------------------
def _body(path: str) -> bytes:
    conts, end = container.split(open(path, "rb").read())
    if len(conts) != 1 or end != os.path.getsize(path):
        raise ValueError("%s: not one clean container" % os.path.basename(path))
    return conts[0].body


def _floors(body: bytes):
    """``(index, [13 list offsets])`` per floor, exactly as `0x00421470` reads."""
    n = struct.unpack_from("<H", body, 4)[0]
    for i in range(n):
        head = struct.unpack_from("<H", body, 6 + 2 * i)[0]
        yield i, [struct.unpack_from("<H", body, head + 2 * j)[0] for j in range(13)]


def chests(root: "str | None" = None):
    """Every chest in every `m/M####.BIN`, in file then floor then list order."""
    root = root or paths.ORIGINAL_DDSWIN
    out = []
    for path in sorted(glob.glob(os.path.join(root, "m", "M[0-9A-Fa-f]*.BIN"))):
        name = os.path.basename(path).upper()
        if name.startswith("MS"):
            continue
        map_id = int(name[1:5], 16)
        body = _body(path)
        for fi, head in _floors(body):
            off = head[OBJECT_LIST]
            while off < len(body) and body[off] != 0xFF:
                raw = body[off:off + STRIDE]
                if len(raw) == STRIDE and raw[5] == CHEST_FILE:
                    out.append(Chest(map_id, fi, raw))
                off += STRIDE
    return out


# --- names ------------------------------------------------------------------
def _tsv(path, key, val):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            c = line.rstrip("\n").split("\t")
            if len(c) > max(key, val) and c[val].strip():
                out[c[key].strip()] = c[val].strip()
    return out


def item_names():
    """``{index: name}`` -- English from `tables/itemdb.tsv`, else Japanese."""
    recs = itemdb.parse(itemdb.source_body(paths.ORIGINAL_DDSWIN))
    en = _tsv(ITEMTABLE, 0, 3)
    out = {}
    for i, r in enumerate(recs):
        n = r.name
        jp = n.decode("cp932", "replace") if isinstance(n, bytes) else (n or "")
        out[i] = en.get(str(i)) or en.get("%d" % i) or jp
    return out


def map_names():
    """``{map id: name}`` from `tables/mapnames.tsv` (English where we have it)."""
    jp = _tsv(MAPNAMES, 0, 1)
    en = _tsv(MAPNAMES, 0, 2)
    out = {}
    for k in set(jp) | set(en):
        try:
            out[int(k, 16)] = en.get(k) or jp.get(k) or ""
        except ValueError:
            pass
    return out


def describe(c: Chest, items) -> str:
    kind, v, n = c.contents
    if kind == "macca":
        return "%d Macca" % v
    if kind == "mag":
        return "%d MAG" % v
    nm = items.get(v, "item %d" % v)
    return nm if n == 1 else "%s x%d" % (nm, n)


# --- reports ----------------------------------------------------------------
def _row(c, items, maps, renew=()):
    return "  M%04X f%-2d (%2d,%2d)  %-13s  %-28s  flag %04X%s" % (
        c.map_id, c.floor, c.x, c.y, PRESENTATION.get(c.record, "r%02X" % c.record),
        describe(c, items), c.flag, "  RENEWS" if c.flag in renew else "")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--item", help="item name fragment, or an ET0001 index")
    ap.add_argument("--map", help="one map id, hex (e.g. 0016)")
    ap.add_argument("--ornate", action="store_true", help="only the moon-gated chests")
    ap.add_argument("--renewable", action="store_true",
                    help="only the chests et/ET0019.BIN refills every lunar month")
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args(argv)

    items, maps = item_names(), map_names()
    renew = renewable_flags()
    rows = chests()

    if a.ornate:
        rows = [c for c in rows if c.moon_gated]
    if a.renewable:
        rows = [c for c in rows if c.flag in renew]
    if a.map:
        want = int(a.map, 16)
        rows = [c for c in rows if c.map_id == want]
    if a.item:
        try:
            idx = int(a.item)
            rows = [c for c in rows if c.contents[0] == "item" and c.value == idx]
        except ValueError:
            frag = a.item.lower()
            rows = [c for c in rows if c.contents[0] == "item"
                    and frag in items.get(c.value, "").lower()]

    if a.summary:
        print("%d chest objects in %d map files" % (
            len(rows), len({c.map_id for c in rows})))
        for r, label in sorted(PRESENTATION.items()):
            n = len([c for c in rows if c.record == r])
            print("  record %02X  %-13s  %d" % (r, label, n))
        print("  %d of them refill every lunar month (et/ET0019.BIN)"
              % len([c for c in rows if c.flag in renew]))
        gems = [c for c in rows if c.contents[0] == "item" and 157 <= c.value <= 172]
        print("\n%d chests hold a gem (items 157-172):" % len(gems))
        for c in gems:
            print(_row(c, items, maps, renew), " ", maps.get(c.map_id, ""))
        return 0

    last = None
    for c in rows:
        if c.map_id != last:
            last = c.map_id
            print("\nM%04X  %s" % (c.map_id, maps.get(c.map_id, "")))
        print(_row(c, items, maps, renew))
    print("\n%d chests" % len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
