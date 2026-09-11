"""Opcode `10` is four bytes, and the broken character is the game's own.

Ten spans in `m/MS0031` begin on the trailing byte of a two-byte character, so
they extract as `｢きなり`, `ﾚしい事情`, `ｳ事だと` -- and shifting one byte back
reads perfectly in all ten (`いきなり`, `詳しい事情`, `無事だと`).  That is a
seductive argument and it is wrong, which is the reason this file exists: four
earlier rules looked equally decisive and every one of them was wrong on the
corpus, so "reads better" is not evidence here.

`10 01 01 82` is opcode `10`, a rel16 of `01 01`, and `82` as the condition's
expression selector.  `0x82` is above the expression table's `0x5D` bound, so the
reader takes it as the nullary "invalid" kind and consumes one byte -- and the
`82` it eats is the lead byte of `い`.

**Four independent things say so, and this test pins the three that are cheap.**

1. The engine's own program counter.  `traces/2026-09-08-warp31-fallthrough.bin`
   was taken with that record's opening branch redirected so the region actually
   executes: pc goes 0x3F -> 0x43, and no logged token starts at 0x42.
2. The glyph blitter, which is not the interpreter, drew `｢きなり、倒れるんだもん。`
   in that same session.  The engine really does lose the character.
3. Every one of the ten rel16s targets exactly `token + 0x104`, a constant --
   because the rel16 is `01 01` at +1..+2 in all ten.  If the fourth byte were
   part of the target it could not be constant while that byte varies (`82`,
   `8F`, `96`).
4. Walking opcode `10`'s handler (`tools/opcode_operands.py`, handler
   `0x00430055`) reports `(0 u8, 1 u16, 0 u32, 1 expr)` on every path.  Not
   asserted here: it shells out to objdump dozens of times.

So there is nothing to fix in the tokenizer, and the ten rows are translatable
as they stand -- the selector byte lives *inside* the token, which
:func:`test_our_english_cannot_reach_the_expression_selector` is here to keep
true, since English starting one byte earlier would be read as a real selector.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import files, paths, records, script, vmops

REL = "m/MS0031.BIN"
TRACE = os.path.join(paths.REPO_ROOT, "traces", "2026-09-08-warp31-fallthrough.bin")
GLYPHS = os.path.join(paths.REPO_ROOT, "traces", "2026-09-08-warp31-glyphs.bin")

#: selectors run 0x00..0x5D; above that the reader takes the nullary "invalid"
#: kind and consumes exactly the one selector byte
SELECTOR_MAX = 0x5D


def _lead(b: int) -> bool:
    return 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xEF


def _sites():
    """``(ci, rec, span, token)`` for every span opened by `10 xx xx <lead>`."""
    sc = script.parse(REL, files.read_source(REL))
    out = []
    for ci, cont in enumerate(sc.containers):
        base = records.bases([records.Record(x.id, x.data) for x in cont])
        for rec in cont:
            if rec.tokens is None:
                continue
            toks = {t.off: t for t in rec.tokens}
            for sp in rec.spans:
                t = toks.get(sp.off - 4)
                if t is None or rec.data[sp.off - 4] != 0x10:
                    continue
                if not _lead(rec.data[sp.off - 1]):
                    continue
                out.append((ci, base, rec, sp, t))
    return out


def test_the_engines_own_pc_never_lands_on_the_disputed_byte():
    """The measurement the reading argument has to beat, and does not.

    If opcode `10` were three bytes the text would start at 0x42 and the engine
    would log a token there -- `ch=0x82A2` if it read the pair, `ch=0x0082` if it
    read the byte alone.  Neither appears.  It logs 0x3F then 0x43.
    """
    if not os.path.exists(TRACE):
        return                      # the trace is gitignored; see traces/README.md
    blob = open(TRACE, "rb").read()
    sc = script.parse(REL, files.read_source(REL))
    base = records.bases([records.Record(x.id, x.data)
                          for x in sc.containers[0]])[0x01]

    starts, at = [], 8
    while at + 20 <= len(blob):
        f, r, _pc, ch = struct.unpack_from("<HHHH", blob, at)
        pc0 = struct.unpack_from("<H", blob, at + 16)[0]
        if f == 0x0031 and r == 0x01 and pc0:
            starts.append((pc0 - (2 if ch > 0xFF else 1) - base, ch))
        at += 20
    assert starts, "the trace holds no tokens for %s r01" % REL

    offs = {s for s, _ in starts}
    assert 0x3F in offs and 0x43 in offs, sorted(offs)[:40]
    assert 0x42 not in offs, "the engine executed 0x42, so opcode 10 is 3 bytes here"

    # and every start it logged is one of ours
    rec = next(x for x in sc.containers[0] if x.id == 0x01)
    ours = {t.off for t in rec.tokens} | {s.off for s in rec.spans}
    for s in sorted(offs):
        if 0 <= s < len(rec.data):
            ours_here = s in ours or any(
                sp.off <= s < sp.end for sp in rec.spans)
            assert ours_here, "engine start 0x%02X is not on any boundary of ours" % s


def test_the_ten_rel16_targets_are_constant_so_the_fourth_byte_is_not_the_target():
    """Arithmetic that does not depend on any trace.

    The fourth byte varies across the ten (`82`, `8F`, `96`) while the target
    offset does not.  A rel16 that included it could not do that.
    """
    sites = _sites()
    # 11 since 2026-09-11: r0B tiles now that a token may read its operands out
    # of the next record, and it carries an eleventh site.  The invariant is
    # unchanged -- the target offset is still constant while the fourth byte is
    # not -- which is the whole content of this test.
    assert len(sites) == 11, "expected 11 sites, found %d" % len(sites)
    deltas, fourth = set(), set()
    for _ci, base, rec, _sp, t in sites:
        r = next(o for o in t.ops if o.kind == "rel16")
        deltas.add(vmops.rel16_target(base[rec.id], t, r) - base[rec.id] - t.off)
        fourth.add(rec.data[t.off + 3])
    assert deltas == {0x104}, sorted(deltas)
    assert len(fourth) > 1, "the fourth byte does not vary, so this proves nothing"


def test_our_english_cannot_reach_the_expression_selector():
    """Why the ten rows are safe to translate, and what would stop being true.

    The selector sits at token+3, one byte before the span, so English never
    overwrites it and it stays above 0x5D.  If a span ever started *on* the
    selector, an English line beginning with a capital (0x41-0x5A, all under
    0x5D) would hand the reader a real kind and it would consume operands out of
    our prose -- and opcode `10` branches on the result, so control flow would
    move.
    """
    for _ci, _base, rec, sp, t in _sites():
        assert t.off + t.size == sp.off, (
            "the span now starts inside the token at 0x%04X" % t.off)
        assert rec.data[t.off + 3] > SELECTOR_MAX, (
            "selector 0x%02X at 0x%04X is a valid kind" % (rec.data[t.off + 3], t.off + 3))


def test_the_blitter_drew_the_broken_character():
    """The confirmation from outside the interpreter entirely."""
    if not os.path.exists(GLYPHS):
        return
    from giten import textlog
    drawn = b"".join(r.raw for r in textlog.read(GLYPHS) if r.kind == 0)
    s = drawn.decode("cp932", "replace")
    assert "きなり" in s, "the line under test was not drawn in this session"
    i = s.index("きなり")
    assert s[i - 1] == "\uff62", (
        "the engine drew %r before きなり; if that is now い, the engine reads "
        "the pair and opcode 10 is 3 bytes" % s[i - 1])
