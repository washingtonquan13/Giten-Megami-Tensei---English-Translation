"""Spans that are not text, and the two rules that keep English out of them.

`m/MS610D` is a negotiation script with binary data mixed into it -- real menu
options (`Save Heart`, `Give Food`, `Grin`, `Wipe Away`) interleaved with tables
the tokenizer walks into and calls text.  Those fake spans decode to the rare
clothing-radical block (褫 襁 襄 褻 褶 袿 襌 褝 襠 襞 褓), which is where binary
lands when it is read as Shift-JIS, and a `02 00` inside one reads as a pool
call -- so promotion substituted **"Devil Buster" into the middle of a data
table**.

Two rules keep them out, and both are here because the obvious version of each
was tried and found wrong:

1. **A span that follows opcode `11`, in a container holding a record we cannot
   tile, is data.**  Both halves matter.  49 of the 50 such spans are data and
   sit only in `m/MS610D`, `m/MS6200` and `m/MS6500` -- the same files whose
   records refuse to tile, which is the tell that the walk is out of step.  The
   fiftieth, `m/MS6000` 12:CE[1], is `失敗！` -> `Failure!` and is real.  "No
   kana" does not separate them (12:CE[1] has kanji and no kana) and neither
   does the clothing-radical block (it holds 裂 and 裏, and 580 real lines use
   them).  The container's own tiling does -- the same correlation that explains
   every off-boundary branch target.
2. **0xFF is counted, not merely present.**  The older rule refused a span whose
   Japanese held 0xFF when the English held none.  A span with *two* in the
   Japanese and *one* in the English passed it, and exactly one did:
   `m/MS610D` 0:FE[4], the only one of the 25 that ever reached the overlay.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import overlay, paths, tables

DRAFT = os.path.join(paths.BUILD_DIR, "tables_draft")
KANA = re.compile(r"[぀-ゟ゠-ヿ]")
CJK = re.compile(r"[一-鿿]")


def _rows():
    if not os.path.isdir(DRAFT):
        return []
    return [r for p in tables.iter_tables(DRAFT) for r in tables.read(p)]


def test_the_data_span_rule_needs_both_halves():
    """Neither half alone is the rule, and each was tried and found wrong.

    "Follows opcode 11" is not enough: `m/MS6000` 12:CE[1] is `失敗！` ->
    `Failure!`, real text, and refusing it would lose a line.
    "No kana" is not enough either -- that is exactly what let 12:CE[1] through
    the first version, because it has kanji and no kana.  Nor is the
    clothing-radical block the data lands in: it contains 裂 and 裏, and 580
    real lines use them.

    What separates them is the container's own tiling, which is the same
    correlation that explains every off-boundary branch target.
    """
    rows = _rows()
    if not rows:
        return
    tagged = [r for r in rows if r.tag == overlay.DATA_TAG]
    assert len(tagged) >= 40, "only %d spans follow opcode %s now" % (
        len(tagged), overlay.DATA_TAG)

    real = [r for r in tagged if r.file == "m/MS6000.BIN"]
    assert real, "the counter-example is gone; the rule may be over-broad again"
    assert not KANA.search(real[0].jp), (
        "%s %s[%d] now has kana, so it no longer demonstrates why "
        "'no kana' was the wrong test" % (real[0].file, real[0].rec, real[0].idx))

    entries, findings = overlay.plan(rows, None)
    served = set()
    for e in entries:
        for s in e.spans:
            served.add((e.rel, "%d:%02X" % (e.ci, s.rec_id), s.idx))
    assert (real[0].file, real[0].rec, real[0].idx) in served, (
        "the rule is refusing real text in a container that tiles cleanly")

    refused = {w.rsplit("[", 1)[0].split()[0] for w, m in findings
               if "follows opcode" in m}
    assert refused <= {"m/MS610D.BIN", "m/MS6200.BIN", "m/MS6500.BIN"}, sorted(refused)


def test_the_overlay_serves_no_english_that_still_carries_japanese():
    """The outcome both rules exist for.

    A row whose English still holds CJK is either untranslated or -- the case
    that matters -- data with a pool substitution spliced into it.  Either way
    the overlay must not put it in front of the interpreter.
    """
    rows = _rows()
    if not rows:
        return
    entries, _ = overlay.plan(rows, None)
    served = set()
    for e in entries:
        for s in e.spans:
            served.add((e.rel, "%d:%02X" % (e.ci, s.rec_id), s.idx))
    bad = [r for r in rows if r.edited and CJK.search(r.en)
           and (r.file, r.rec, r.idx) in served]
    assert not bad, "%d served row(s) still carry Japanese in their English: %s" % (
        len(bad), [(r.file, r.rec, r.idx, r.en[:24]) for r in bad[:4]])


def test_the_structural_byte_is_counted_and_not_merely_looked_for():
    """Presence is not enough, and one span proved it.

    `m/MS610D` 0:FE[4]'s Japanese carries two 0xFF and its English one, so a
    presence test let it through while a byte quietly went missing.  0x00435CF0
    scans for that byte through the fetch we hook, so a dropped one is a real
    scan walking off the end.
    """
    src = open(os.path.join(paths.REPO_ROOT, "giten", "overlay.py"),
               encoding="utf-8").read()
    assert "jp.count(STRUCTURAL_BYTE) != data.count(STRUCTURAL_BYTE)" in src, (
        "the 0xFF rule no longer counts; a span that drops one of several would ship")

    rows = _rows()
    if not rows:
        return
    hit = [r for r in rows
           if r.file == "m/MS610D.BIN" and r.rec == "0:FE" and r.idx == 4]
    if not hit:
        return                      # the row ids moved; the src check still stands
    entries, findings = overlay.plan(rows, None)
    where = {w.split()[0] + " " + w.split()[1] for w, _m in findings}
    assert "m/MS610D.BIN 0:FE[4]" in where, "the span that proved the bug is served again"
