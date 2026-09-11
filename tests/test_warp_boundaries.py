"""The 22 warp traces, and the three things they said about the model.

`build/traces/warp-*.bin` is the engine tiling records nothing had ever run.
Across all 22, after this work, **zero boundaries disagree with the model**.
What the session did produce is three findings, and each one is pinned here at
the exact offset the engine dispatched at, so that a later model change has to
move a number rather than a paragraph.

1. **A `10` whose `rel16` is 1 branches into the second byte of its own
   expression.**  This is the whole of the old "opcode 10 is 6 bytes to us and 4
   to the engine" disagreement: the token really is six bytes, and the engine's
   next program counter really is four bytes on -- because it took the branch.

2. **A straddling token changes the phase of the record it lands in.**
   `m/MS0031` c0 r0B's final `1F 04` is 612 bytes; the engine's own program
   counter after it is `r0C + 0x0196`, one byte off the phase the model tiles r0C
   in.  Both readings are real; which one the bytes are depends on how the
   engine got there.

3. **The Shift-JIS lead-byte rule is the engine's.**  The old brief suspected the
   two above were a lead-byte disagreement -- a one-byte character the model
   reads as a double-byte lead.  They are not, and the rule is checked here
   against every character the engine was ever seen fetching.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import files, overlay, paths, records, script, tile, vmops  # noqa: E402

TRACES = os.path.join(paths.BUILD_DIR, "traces")
WARPS = os.path.join(paths.BUILD_DIR, "warp")


def _fixture(rel, ci, rec_id):
    name = tile.fixture_name(rel, ci, rec_id)
    path = os.path.join(tile.OBSERVED_DIR, name)
    assert os.path.exists(path), "%s has no observed fixture" % name
    import json
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _rec(rel, ci, rec_id):
    sc = script.parse(rel, files.read_source(rel))
    rec = next(r for r in sc.containers[ci] if r.id == rec_id)
    return sc, rec


def _bases(sc, ci):
    recs = [records.Record(r.id, r.data) for r in sc.containers[ci]]
    return records.bases(recs)


# --------------------------------------------------------------------------
# 1.  the `10` sites
# --------------------------------------------------------------------------
def test_opcode_10_is_six_bytes_and_a_rel16_of_one_lands_inside_its_expression():
    """`m/MS0031` c0 r0B 0x00B6, measured twice by the engine in one token.

    Bytes `10 01 00 0f 82 bb`: opcode `10` = `rel16, expr`, the expression being
    selector `0x0F` (kind 12, one `u16`), so six bytes.  `rel16` = 1 and the
    displacement is measured from the byte after the operand, so the target is
    `0x00B9 + 1 = 0x00BA` -- the *second* byte of that expression.  The engine
    dispatched at 0x00B6 and its next program counter was 0x00BA, where it read
    `82 bb` (そ) and drew 「それがまず‥‥」; falling through would have started at
    0x00BC and drawn 「れがまず」.  Both 0x00B6 and 0x00BA are in the fixture.

    This is the site the 2026-09-06 note filed as "ours 6 bytes, the text is at
    +4": +4 *is* the branch target, and there was never a missing byte.
    """
    _sc, rec = _rec("m/MS0031.BIN", 0, 0x0B)
    tok = next(t for t in rec.span_tokens if t.off == 0x00B6)
    assert tok.kind == "op" and tok.idx == 0x010 and tok.size == 6
    assert bytes(rec.data[0x00B6:0x00BC]) == b"\x10\x01\x00\x0f\x82\xbb"
    rel = next(o for o in tok.ops if o.kind == "rel16")
    assert rel.value == 1
    assert vmops.rel16_target(0, tok, rel) == 0x00BA

    fx = _fixture("m/MS0031.BIN", 0, 0x0B)
    assert 0x00B6 in fx["boundaries"]
    assert 0x00BA in fx["boundaries"]
    # and the model does NOT start a token at 0x00BA: it is an entry, not a
    # boundary, and `tile` has to say so rather than calling it a defect
    starts = {t.off for t in rec.span_tokens}
    assert 0x00BA not in starts


def test_the_same_shape_in_r0c_and_the_one_in_r17_that_enters_r19():
    """`r0C` 0x01D6 is the same site; `r17` 0x0079's target is in another record."""
    _sc, r0c = _rec("m/MS0031.BIN", 0, 0x0C)
    tok = next(t for t in r0c.span_tokens if t.off == 0x01D6)
    assert tok.size == 6 and tok.idx == 0x010
    assert 0x01DA in _fixture("m/MS0031.BIN", 0, 0x0C)["boundaries"]

    sc, r17 = _rec("m/MS0031.BIN", 0, 0x17)
    base = _bases(sc, 0)
    tok = next(t for t in r17.span_tokens if t.off == 0x0079)
    rel = next(o for o in tok.ops if o.kind == "rel16")
    target = vmops.rel16_target(base[0x17], tok, rel)
    assert target == base[0x19] + 0x0050, (hex(target), hex(base[0x19]))
    # the engine went there: r19's first observed program counter is 0x0050, and
    # the byte there is a HALF-WIDTH kana -- one byte to the engine and one byte
    # to the model.  The model tiles r19 from offset 0, where the same byte is
    # the second half of `82 c8` (な), so 0x0050 is not a token start.
    fx = _fixture("m/MS0031.BIN", 0, 0x19)
    assert min(fx["boundaries"]) == 0x0050
    _sc2, r19 = _rec("m/MS0031.BIN", 0, 0x19)
    assert r19.data[0x0050] == 0xC8 and not vmops.is_sjis_lead(0xC8)
    assert 0x0050 not in {t.off for t in r19.span_tokens}


# --------------------------------------------------------------------------
# 2.  the straddle that changes a record's phase
# --------------------------------------------------------------------------
def test_r0b_straddles_612_bytes_and_the_engine_reads_r0c_from_0x0196():
    """The model's own arithmetic predicts the engine's program counter exactly.

    r0B's last token is the corpus's only `pairs_ff` with no terminator of its
    own; against the container image it runs 612 bytes from 0x0236 and ends 406
    bytes past r0B.  r0C is 0x14B0 - 0x11AC = 772 bytes further on in the image,
    so the landing is r0C + 0x0196 -- which is exactly where the engine's next
    dispatch was, and one byte off the phase the model tiles r0C in.
    """
    sc, r0b = _rec("m/MS0031.BIN", 0, 0x0B)
    base = _bases(sc, 0)
    last = r0b.span_tokens[-1]
    assert last.off == 0x0236 and last.size == 612
    assert r0b.straddle == 406
    landing = base[0x0B] + len(r0b.data) + r0b.straddle
    assert landing == base[0x0C] + 0x0196, (hex(landing), hex(base[0x0C]))
    fx = _fixture("m/MS0031.BIN", 0, 0x0C)
    assert min(fx["boundaries"]) == 0x0196
    _sc2, r0c = _rec("m/MS0031.BIN", 0, 0x0C)
    assert 0x0195 in {t.off for t in r0c.span_tokens}   # the model's phase
    assert 0x0196 not in {t.off for t in r0c.span_tokens}


def test_r00_straddles_into_r01_and_the_engine_reads_r01_from_0x0002():
    """The same thing one container-image step later, and it explains r01 too."""
    sc, r00 = _rec("m/MS0031.BIN", 0, 0x00)
    base = _bases(sc, 0)
    # r00 is `unreached`, so its walk stops before the end; the closure that
    # reaches its tail is the one `tile` uses, and it is what predicts 0x0002
    m = tile._Model(sc)
    assert 0x0002 in m.entry_starts(0, 0x01)
    assert 0x0004 in m.entry_starts(0, 0x01)
    fx = _fixture("m/MS0031.BIN", 0, 0x01)
    assert set(fx["boundaries"]) >= {0x0002, 0x0004}
    assert base[0x01] == base[0x00] + len(r00.data)


# --------------------------------------------------------------------------
# 3.  the lead-byte rule
# --------------------------------------------------------------------------
def test_the_engine_never_disagrees_with_the_sjis_lead_byte_rule():
    """Every character the engine was seen fetching, against `is_sjis_lead`.

    The engine takes a second byte only when the `_ismbblead` bit `0x04` is set
    in the locale table at `0x00490C11` (`0x00438F00`), and the model's rule is
    the hard-coded `0x81..0x9F` / `0xE0..0xFC`.  Rather than read the table out
    of a running process, this reads the answer off the traces: `ch > 0xFF` says
    the engine fetched two bytes.  Over all 22 warp traces there are **no**
    disagreements, 23 distinct lead bytes were exercised and 9 distinct
    single-byte ones, and no byte was ever seen both ways.
    """
    names = sorted(n for n in os.listdir(TRACES)
                   if n.startswith("warp-") and n.endswith(".bin"))
    if not names:
        return
    index = tile.record_index(paths.game_root())
    two, one, bad = set(), set(), []
    for name in names:
        _ver, events = tile.read_events(os.path.join(TRACES, name))
        for ev in events:
            if ev.virtual or not ev.from_pc or not ev.idx_len or not ev.pc0:
                continue
            hit = index.get((ev.rec, ev.idx_len, ev.rec_hash))
            if not hit:
                continue
            data = hit[0][3]
            off = ev.pc0 - ev.width - ev.idx_off
            if not (0 <= off and off + ev.width <= len(data)):
                continue
            want = (bytes([ev.ch >> 8, ev.ch & 0xFF]) if ev.ch > 0xFF
                    else bytes([ev.ch]))
            if data[off:off + ev.width] != want:
                continue
            b = data[off]
            if b < 0x20:
                continue                    # an opcode, not a character
            (two if ev.width == 2 else one).add(b)
            if (ev.width == 2) != vmops.is_sjis_lead(b):
                bad.append((name, hit[0][0], hex(off), hex(b), ev.width))
    assert not bad, bad[:10]
    assert not (two & one), sorted(hex(b) for b in two & one)
    assert len(two) == 23 and len(one) == 9, (len(two), len(one))
    assert 0xC8 in one and 0x82 in two       # the two the old brief suspected


# --------------------------------------------------------------------------
# 4.  what the switch handler really reads, from the exe
# --------------------------------------------------------------------------
def test_the_switch_handler_skips_a_non_matching_entry_without_reading_its_kind():
    """`0x004327C0`, both loops, byte for byte.

    This is the evidence that `_read_switch`'s `kind > 1` refusal is not
    VM-faithful: the engine steps a non-matching case with one `READ_U8` and one
    `READ_U16` and never looks at the byte, so a table is `4N + 1` whatever its
    kinds are.  The refusal is kept anyway -- dropping it grows a 390-byte `0F`
    over `m/MS0031` c0 r00's dialogue, which the engine was observed drawing --
    and `giten/vmops.py` says so where the code is.

    Pinned as the instruction bytes rather than as a disassembly listing so the
    test needs no objdump.
    """
    from giten.exe import patch
    from giten.exe.pe import PE
    img = open(patch.ORG, "rb").read()
    pe = PE(img, "o")

    def at(va, n):
        return img[pe.va2off(va):pe.va2off(va) + n]

    def call_target(va):
        assert img[pe.va2off(va)] == 0xE8
        rel = int.from_bytes(at(va + 1, 4), "little", signed=True)
        return va + 5 + rel

    READ_U8, READ_U16 = 0x00438FA0, 0x00438FC0
    # mode 1 (0F): the non-matching arm at 0x4327F1
    assert call_target(0x004327F1) == READ_U8
    assert call_target(0x004327F6) == READ_U16
    assert at(0x004327FB, 2) == b"\xeb\x25"            # jmp 0x432822, next key
    # mode 0 (0E): the same shape at 0x432891
    assert call_target(0x00432891) == READ_U8
    assert call_target(0x00432896) == READ_U16
    # and the matching arm is the only place the kind byte is tested
    assert call_target(0x004327FD) == READ_U8
    assert at(0x00432802, 2) == b"\x84\xc0"            # test al,al
    assert call_target(0x0043280A) == 0x00433EC0       # kind != 0 -> rel16
    assert call_target(0x00432816) == 0x00433C10       # kind == 0 -> file,rec
    # the terminator is exactly 0xFF, and nothing else ends the table
    assert at(0x004327DE, 3) == b"\x80\xfb\xff"        # cmp bl,0xff
    assert at(0x00432829, 3) == b"\x80\xfb\xff"


def test_dropping_the_kind_guard_would_swallow_boundaries_the_engine_dispatched():
    """The measurement that keeps the guard, run rather than quoted.

    With the refusal removed, `m/MS0031` c0 r00's `0F` at 0x0060 consumes 390
    bytes -- past the end of a 273-byte record -- and covers every one of the 86
    program counters the engine was observed at from 0x006B on.  A table that
    covers bytes the engine itself dispatched as tokens is not a table.
    """
    data = _rec("m/MS0031.BIN", 0, 0x00)[1].data
    i = 0x0061
    # the VM-faithful read: 4 bytes a case, any kind, until 0xFF
    while i + 4 <= len(data) and data[i] != 0xFF:
        i += 4
    assert i > len(data) - 4, (
        "r00's 0F table now terminates inside the record; re-take the "
        "measurement in giten/vmops._read_switch")
    fx = _fixture("m/MS0031.BIN", 0, 0x00)
    covered = [b for b in fx["boundaries"] if 0x0060 < b < len(data)]
    assert len(covered) >= 80, len(covered)
