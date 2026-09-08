"""Which `m/MS6xxx` files the game can actually load -- and why 67 untiled
records stopped being a problem.

`docs/todo.md` item 4 spent weeks treating `m/MS610D` as a file whose *loader we
had not found yet*: 40 untiled records, 92 served spans, no warp that reaches it.
It has no loader.  Nothing in the shipped game can name it.

The demon-negotiation image is the only thing that loads an `m/MS61xx` file, and
it builds the name in exactly one instruction:

    0x0040EC31   add $0x6100,%edx        # edx = table[id*3 + 2]
    0x0040EC37   push $0x9               # kind 9 -> m\ms%.4x.bin

and the table is not a guess -- `0x0040EB70` loads it itself, lazily, and caches
the pointer:

    0x0040EB7F   push $0x7               # file id 7
    0x0040EB7D   push $0xc               # kind 12 -> et\et%.4x.bin
    0x0040EB81   call 0x401dd0           # -> et/ET0007.BIN
    0x0040EB99   movl $0x47b058,0x47b4f8

`et/ET0007.BIN`'s third column holds `{00, 06, 07, 08, 09, 0B, 0C}`.  It never
holds `0D`, so `m/MS610D` is never named.  Nor can a script name it: every
file-referencing opcode either hardcodes a pool (`m/MS7F0x`) or takes a **u8**
id that resolves to `m/MS00xx`, so no u16 file id ever reaches the router from
script data.

**What this is worth.** 67 of the corpus's 73 untiled records are in files that
cannot be loaded.  Every reachable `m/MS6xxx` file tiles perfectly.  The real
remaining gap is six records in one container of `m/MS0031`.

**The limit, stated rather than papered over.**  The row index is a `u16` read
from a struct field (`0x47b16f`, stride 254), not a bounded loop counter, so
this does not prove the engine can never pass an index past the table's 25 rows.
It proves there is no *designed* path to these files; an out-of-bounds index
would be a bug producing an arbitrary merge, not a loader.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import files, paths, script

#: `0x0040EB70` pushes these to load its own table: id 7, kind 12 = et\et%.4x.bin
MERGE_TABLE = "et/ET0007.BIN"
#: the third column is added to this, at 0x0040EC31
FAMILY_61 = 0x6100
PAT = re.compile(r"^m/MS([0-9A-Fa-f]{4})\.BIN$")


def _rows():
    raw = files.read_source(MERGE_TABLE)
    n = int.from_bytes(raw[:2], "little")
    assert n == len(raw) - 2 and n % 3 == 0, (n, len(raw))
    return [tuple(raw[2 + i * 3:5 + i * 3]) for i in range(n // 3)]


def _reachable_6xxx():
    out = {0x6000}
    for t0, t1, t2 in _rows():
        if t0 != 0xFF:
            out.add(0x6000 + t0)
        if t1 != 0xFF:
            out.add(0x6000 + t1)
        if t2 != 0xFF:
            out.add(FAMILY_61 + t2)
    return out


def reachable(rel: str) -> bool:
    m = PAT.match(rel)
    if not m:
        return True                       # m/M*.BIN and friends: other loaders
    fid = int(m.group(1), 16)
    if fid < 0x100:                       # 0C/0D name m/MS00xx by a u8
        return True
    if 0x7F00 <= fid <= 0x7F07:           # the macro pools, hardcoded per opcode
        return True
    if 0x6000 <= fid <= 0x61FF:
        return fid in _reachable_6xxx()
    return False                          # no instruction forms the id


def test_the_merge_table_is_et0007_and_it_never_names_ms610d():
    """The two facts the whole reachability argument rests on."""
    rows = _rows()
    assert len(rows) == 25, len(rows)
    t2 = {t[2] for t in rows if t[2] != 0xFF}
    assert t2 == {0x00, 0x06, 0x07, 0x08, 0x09, 0x0B, 0x0C}, sorted(t2)
    assert 0x0D not in t2, "et/ET0007 now names m/MS610D; the family is reachable again"

    # and every file it does name exists, which is what rules out the two other
    # tables in et/ that share this shape (ET1011 misses 22, ET10FF misses 9)
    for t0, t1, t2b in rows:
        for fam, t in ((0x6000, t0), (0x6000, t1), (FAMILY_61, t2b)):
            if t == 0xFF:
                continue
            rel = "m/MS%04X.BIN" % (fam + t)
            assert os.path.exists(os.path.join(paths.game_root(), *rel.split("/"))), rel


def test_no_script_opcode_can_name_a_file_by_a_u16_id():
    """The hole "no immediate in the exe" would otherwise leave open."""
    import json
    import io
    with io.open(os.path.join(paths.REPO_ROOT, "docs", "opcodes.json"),
                 encoding="utf-8") as fh:
        ops = json.load(fh)["opcodes"]
    for k, v in ops.items():
        if not (v.get("refs_record") and v.get("uses", 0) > 0):
            continue
        ref = v.get("record_ref") or {}
        f = ref.get("file") or ""
        assert "u8 file id" in f or f.startswith("m/MS7F"), (
            "opcode %s references %r -- if a script can pass a full file id, "
            "reachability cannot be decided from the exe alone" % (k, f))


def test_every_untiled_record_outside_ms0031_is_in_a_file_nothing_can_load():
    """The payoff, and the assertion that fails if that stops being true."""
    bad, unreach_untiled = [], 0
    for rel in sorted(files.all_encoded()):
        if not rel.startswith("m/"):
            continue
        sc = script.parse(rel, files.read_source(rel))
        un = sum(1 for c in sc.containers for r in c if r.tokens is None)
        if not un:
            continue
        if reachable(rel):
            bad.append((rel, un))
        else:
            unreach_untiled += un
    assert unreach_untiled == 67, unreach_untiled
    assert bad == [("m/MS0031.BIN", 6)], (
        "untiled records now sit in a reachable file: %s" % bad)
