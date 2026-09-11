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

**r0B: the one `pairs_ff` in the corpus with no terminator (added 2026-09-08).**
Its `1F 04` at 0x236 is real -- the rel16 is `0x00C9`, targeting record offset
0x0303, which is the record's own final `00` terminator, a jump to the end that
no misaligned walk would produce by chance.  What is broken is the condition
list: the record holds only two `0xFF` bytes, both at 0x113/0x114 and both
legitimately consumed by an earlier `1F 01`, so nothing after 0x23A can end the
list.  The engine's loop was read rather than assumed:

    call 0x4393e0        ; *a = first & 0x7F, *b = second; returns -1 if first & 0x80
    cmp  bx,0xffff       ; bit 7 set?
    jne  body            ; no -> evaluate the pair and loop
    cmp  ax,0x7f         ; set, and (first & 0x7F) == 0x7F -> first byte is exactly 0xFF
    je   terminate

which is precisely what `_read_pairs_ff` implements.  Corpus-wide, **916 of 919
`1F03`/`1F04` sites terminate inside their own record**; the three that do not
are r0B and two byte-identical copies of one record in `m/MS6F00`/`m/MS6F1F`,
files already established as not script at all.  So the model is right and this
record is the single broken one.

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


def test_r0b_is_the_only_unterminated_pairs_ff_in_the_corpus():
    """The model is right 916 times; r0B is the exception, not the rule.

    If this count ever drops, `_read_pairs_ff` has been changed and the change
    is wrong -- the engine's loop at 0x0042FEB0 terminates only on a first byte
    of exactly 0xFF, and it costs two bytes.
    """
    good, bad = 0, []
    tab = vmops.table()
    for rel in files.all_encoded():
        if not rel.startswith("m/"):
            continue
        try:
            sc = script.parse(rel, files.read_source(rel))
        except Exception:
            continue
        for ci, cont in enumerate(sc.containers):
            for r in cont:
                if r.tokens is not None:
                    good += sum(1 for t in r.tokens
                                if t.kind == "op" and t.idx in (0x103, 0x104))
                    continue
                d, i = r.data, 0
                while i < len(d):
                    b = d[i]
                    if b >= 0x20:
                        i += 2 if (vmops.is_sjis_lead(b) and i + 1 < len(d)) else 1
                        continue
                    idx, head = ((vmops.ESCAPE[b] + d[i + 1], 2)
                                 if b in vmops.ESCAPE else (b, 1))
                    try:
                        j, _ = vmops._read_operands(d, i + head, tab.operands(idx), tab)
                    except vmops.TileError:
                        if idx in (0x103, 0x104):
                            bad.append((rel, ci, r.id))
                        break
                    i = j
    assert good >= 916, "only %d pairs_ff sites terminate cleanly now" % good
    # 2026-09-11: this list is now EMPTY, and the reason is the interesting
    # part.  Since `vmops.tokenize_record` walks the container image, a
    # `pairs_ff` list may end in the next record -- which is exactly what the
    # engine's loop at 0x0042FEB0 would do, since its byte fetch has no bound --
    # so all three records tile.  That is not the same as the list being sound:
    # see the test below, which pins how far each of them reaches.
    assert bad == [], bad


#: The three records whose ``1F 03``/``1F 04`` list runs out of its own record,
#: with how many bytes past the end it takes to find a ``0xFF``.  ``m/MS6F00``
#: and ``m/MS6F1F`` are byte-identical here and are ``data`` anyway; the one
#: that matters is ``m/MS0031`` r0B.
RUNAWAY_PAIRS_FF = {
    ("m/MS0031.BIN", 0, 0x0B): 406,
    ("m/MS6F00.BIN", 31, 0x1B): 61,
    ("m/MS6F1F.BIN", 0, 0x1B): 61,
}


def test_the_three_runaway_pairs_ff_lists_are_the_only_long_straddles():
    """A token reading 406 bytes into the next record is a claim, not a fact.

    Letting the walk cross a record boundary is right -- the engine's fetch has
    no bound -- but "right" has a scale.  47 of the 50 straddling records finish
    within **six** bytes and their last token is control flow emitted at the end
    of a chunk.  These three are a different animal: `m/MS0031` r0B holds only
    two `0xFF` bytes, both consumed at 0x113 by an earlier `1F 01`, so its
    condition list cannot end inside the record at all and the walk keeps going
    until it meets an `0xFF` 406 bytes into r0C.

    So the record tiles, and what it tiles into is still the open question --
    which is why `build/warp/MS0031-r0B` exists.  This test exists so that the
    three cannot quietly become four, and so that a change which "fixes" r0B by
    shortening the list has to face the 916 sites that terminate cleanly.
    """
    got = {}
    for rel in sorted({k[0] for k in RUNAWAY_PAIRS_FF}):
        sc = script.parse(rel, files.read_source(rel))
        for ci, cont in enumerate(sc.containers):
            for r in cont:
                if r.straddle > 8:
                    assert r.tokens[-1].idx in (0x103, 0x104), (
                        "%s c%d r%02X straddles %d bytes on opcode 0x%03X, which "
                        "is not a pairs_ff -- read it before re-baselining"
                        % (rel, ci, r.id, r.straddle, r.tokens[-1].idx))
                    got[(rel, ci, r.id)] = r.straddle
    assert got == RUNAWAY_PAIRS_FF, got

    # and corpus-wide there are no others
    n = 0
    for rel in files.all_encoded():
        if not rel.startswith("m/"):
            continue
        sc = script.parse(rel, files.read_source(rel))
        n += sum(1 for c in sc.containers for r in c if r.straddle > 8)
    assert n == len(RUNAWAY_PAIRS_FF), n


def test_r0bs_branch_targets_its_own_records_terminator():
    """Why the token is real even though its operand is broken."""
    _cont, _base, have = _container()
    d = have[0x0B]
    assert d[0x236:0x238] == b"", d[0x236:0x23A].hex()
    rel = int.from_bytes(d[0x238:0x23A], "little")
    tgt = 0x23A + rel
    assert tgt == len(d) - 1, "the branch no longer targets the record's last byte"
    assert d[tgt] == 0x00, "that byte is no longer the terminator"
    assert d.count(0xFF) == 2 and d.index(0xFF) == 0x113, (
        "the record's 0xFF bytes moved; the 'no terminator possible' claim needs rechecking")
