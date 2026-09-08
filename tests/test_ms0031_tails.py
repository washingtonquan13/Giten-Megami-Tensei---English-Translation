"""The six `m/MS0031` records that refuse to tile are broken data, not a bad model.

Five of the six are now explained, and none of them is a defect in the
tokenizer.  Two shapes:

**Dead data after a terminator (r00, r0D).**  Opcode `00` is
`or ax,0xFFFF; ret`, which ends the interpreter's run loop.  r00 has ten
terminators, the last at 0x5F with 177 bytes after it; r0D has two, the last at
0x31 with 4.  The walk fails *inside* those regions.  r0D's tail even carries the
canonical switch shape -- `31 14 ff` is a switch *entry*, matching
`0F 00 00 31 12 01 00 ... 31 11 ff` in four records that do tile.

**A branch that eats the terminator and spills into the next record (r02, r03,
r17).**  This looked like a model bug and is not.  All 22 tiling records in the
container end with a `0x00` byte, and r02/r03 contain exactly one `0x00` each --
the last one -- which our model consumes as part of a rel16, leaving them with no
terminator at all.  Predictions were registered before the run
(`tools/make_warp_seq.py`) and the engine chose ours:

* **r17 has no terminator.**  74 tokens execute past its end; the first is at
  r18+0x01 with `ch=0x00D2` -- the bare trailing byte of `1F D2`, exactly as
  predicted, because opcode `10`'s expression (selector `00` = `[u8]`) consumes
  r17's final `00` plus one byte of r18.
* **r02 crashes the game.**  Its closing `18` reads its rel16 as `00 1F` -- its
  own last byte plus r03's first -- and branches to
  `0x0C9D + 0x1F00 = 0x2B9D`, past the 0x2457 end of the image.  The player saw
  the dialogue play and then the process die.

The glyph log is the cleanest evidence in the project: the **same**
`[1FD2]泪：[1FD3]` marker is drawn twice in one session -- `泪：` when r17 is
entered at offset 0, `ﾒ泪：` when r18 is entered at offset 1 by the spill.  Same
bytes, two renderings, decided only by entry point.  That also retroactively
explains the identical `ﾒ泪：` in r01.

**What this does NOT establish.**  That these records are unreachable.  Only one
`0C`/`0D` reference to `m/MS0031` exists in the whole corpus (r1B) and the file
appears in none of the 668,311 events across nine play traces -- but those
sessions are all early-game and this is plainly a late-game scene, and the
intra-container reachability walk does not follow `0E`/`0F` switch targets, so it
under-approximates.  Evidence, not proof.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import files, paths, records, script, vmops

TRACE = os.path.join(paths.REPO_ROOT, "traces", "2026-09-08-warp17-spill.bin")
GLYPHS = os.path.join(paths.REPO_ROOT, "traces", "2026-09-08-warp17-glyphs.bin")
REL = "m/MS0031.BIN"


def _container():
    sc = script.parse(REL, files.read_source(REL))
    cont = list(sc.containers[0])
    recs = [records.Record(r.id, r.data) for r in cont]
    return cont, records.bases(recs), {r.id: r.data for r in recs}


def _events():
    blob = open(TRACE, "rb").read()
    n = (len(blob) - 8) // 20
    out = []
    for i in range(n):
        f, r, pc, ch = struct.unpack_from("<HHHH", blob, 8 + i * 20)
        pc0 = struct.unpack_from("<H", blob, 8 + i * 20 + 16)[0]
        out.append((f, r, pc, ch, pc0))
    return out


def test_r00_and_r0d_fail_only_inside_dead_data_after_a_terminator():
    """Not a model defect: nothing executes those bytes."""
    cont, _base, have = _container()
    tab = vmops.table()
    for rid, fail_at in ((0x00, 0x60), (0x0D, 0x33)):
        d = have[rid]
        i, last_stop = 0, None
        while i < fail_at:
            b = d[i]
            if b >= 0x20:
                i += 2 if (vmops.is_sjis_lead(b) and i + 1 < len(d)) else 1
                continue
            idx, head = ((vmops.ESCAPE[b] + d[i + 1], 2) if b in vmops.ESCAPE
                         else (b, 1))
            try:
                j, _ = vmops._read_operands(d, i + head, tab.operands(idx), tab)
            except vmops.TileError:
                break
            if idx in (0x000, 0x00C):
                last_stop = i
            i = j
        assert last_stop is not None and last_stop < fail_at, (
            "r%02X no longer has a terminator before its failure" % rid)


def test_the_engine_spilled_out_of_r17_into_the_next_record():
    """Prediction A, on the program counter."""
    if not os.path.exists(TRACE):
        return
    _cont, base, have = _container()
    end17 = base[0x17] + len(have[0x17])
    assert base[0x18] == end17, "r18 no longer follows r17"
    past = [e for e in _events()
            if e[0] == 0x0031 and e[4]
            and (e[4] - (2 if e[3] > 0xFF else 1)) >= end17
            and (e[4] - (2 if e[3] > 0xFF else 1)) < base[0x18] + len(have[0x18])]
    assert len(past) >= 40, "only %d tokens ran past r17's end" % len(past)
    first = min(past, key=lambda e: e[4])
    start = first[4] - (2 if first[3] > 0xFF else 1)
    assert start == base[0x18] + 1, (
        "the spill landed at 0x%04X, not r18+1" % start)
    assert first[3] == 0x00D2, (
        "the first spilled token read 0x%04X, not the bare 0xD2" % first[3])


def test_r02_branches_past_the_end_of_the_image_which_is_the_crash():
    """The trace's last event, and the arithmetic behind it."""
    if not os.path.exists(TRACE):
        return
    _cont, base, have = _container()
    size = 0x400 + sum(len(have.get(i, b"\x00")) for i in range(256))
    ev = _events()
    last = ev[-1]
    assert last[3] == 0x0018, "the run no longer ends on opcode 18 (got 0x%04X)" % last[3]
    assert last[2] == 0x2B9D, "the branch target moved: 0x%04X" % last[2]
    assert last[2] >= size, (
        "0x%04X is inside the 0x%04X image, so it would not crash" % (last[2], size))
    # and it is what our own model computes for that token
    d = have[0x02]
    assert d[-2:] == b"\x18\x00", d[-4:].hex()
    rel = int.from_bytes(bytes([d[-1], have[0x03][0]]), "little")
    assert (base[0x02] + len(d) + 1 + rel) & 0xFFFF == 0x2B9D


def test_the_same_marker_is_drawn_two_ways_in_one_session():
    """The controlled experiment: only the entry point differs."""
    if not os.path.exists(GLYPHS):
        return
    from giten import textlog
    s = b"".join(r.raw for r in textlog.read(GLYPHS)
                 if r.kind == 0).decode("cp932", "replace")
    hits = [i for i in range(len(s)) if s.startswith("\u6cea\uff1a", i)]
    assert len(hits) == 2, "expected 泪： twice, found %d" % len(hits)
    assert s[hits[0] - 1] != "\uff92", "the r17 rendering is garbled too"
    assert s[hits[1] - 1] == "\uff92", "the spilled rendering is no longer garbled"
