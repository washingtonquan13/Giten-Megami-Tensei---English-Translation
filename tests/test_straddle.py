"""A token at the end of a record is an ordinary token.

`base(id) = 0x400 + sum of the lengths` (an absent record being one `0x00`), and
the interpreter's byte fetch `0x00438E50` is a plain `[base + pc++]` with no
bound, so a record's final token legally reads its operands out of the next
record.  The record layer is an *index* into one image, not a limit on the walk.
`vmops.tokenize_record` walks that image; 63 records that "refused to tile" were
only ever being measured against the wrong bound.

What the walk does **not** do is widen text.  269 records end on a Shift-JIS lead
byte and growing those would renumber their spans to describe a character half in
one record and half in the next -- unservable by the overlay, unwritable by a
translator.  Every straddle actually observed is control flow.

Three things still have to hold, and they are what this file pins:

* the byte builder refuses to **rebuild** a straddling record, because moving it
  moves operand bytes it does not own;
* the byte builder refuses to **edit a span that holds those operand bytes**, in
  the record they actually live in;
* `script._branch_targets` **does** see them, so a branch into a straddling
  record's text still protects that text from an edit.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import files, records, script, vmops

REL = "m/MS0031.BIN"


def _cont(rel=REL, ci=0):
    sc = script.parse(rel, files.read_source(rel))
    assert sc.ok, sc.error
    return sc, sc.containers[ci]


# --- the image --------------------------------------------------------------
def test_the_runtime_image_is_id_order_with_a_zero_for_every_absent_record():
    _sc, cont = _cont()
    rr = [records.Record(r.id, r.data) for r in cont]
    image = records.runtime_image(rr)
    base = records.bases(rr)
    uniq = _by_id(cont)
    assert len(image) == (sum(max(len(r.data), 0) for r in uniq)
                          + (256 - len(uniq)) * records.ABSENT_LEN)
    for r in cont:
        off = base[r.id] - records.INDEX_SIZE
        assert image[off:off + len(r.data)] == r.data, "r%02X" % r.id
    # every id with no record is exactly one 0x00
    have = {r.id for r in cont}
    for i in range(256):
        if i in have:
            continue
        off = base[i] - records.INDEX_SIZE
        assert image[off:off + 1] == b"\x00", "absent record 0x%02X" % i


def _by_id(cont):
    seen, out = set(), []
    for r in cont:
        if r.id in seen:
            continue
        seen.add(r.id)
        out.append(r)
    return out


def test_id_order_is_not_file_order_and_the_image_follows_the_ids():
    """The distinction that makes the walk read the right neighbour."""
    found = None
    for rel in ("m/MS610D.BIN", "m/MS0031.BIN", "m/MS6000.BIN"):
        sc = script.parse(rel, files.read_source(rel))
        for cont in sc.containers:
            ids = [r.id for r in cont]
            if ids != sorted(ids):
                found = (rel, ids)
                break
        if found:
            break
    assert found, "no container stores its records out of id order any more"
    rel, _ids = found
    sc = script.parse(rel, files.read_source(rel))
    for cont in sc.containers:
        rr = [records.Record(r.id, r.data) for r in cont]
        image, base = records.runtime_image(rr), records.bases(rr)
        for r in cont:
            off = base[r.id] - records.INDEX_SIZE
            if image[off:off + len(r.data)] == r.data:
                continue
            # the only records not in the image are the losing copies of a
            # duplicate id, which the loader never installs
            assert sum(1 for x in cont if x.id == r.id) > 1, "r%02X" % r.id


# --- the records ------------------------------------------------------------
def test_a_straddling_record_is_tiled_blocked_and_counted():
    _sc, cont = _cont()
    r17 = next(r for r in cont if r.id == 0x17)
    assert r17.tokens is not None and not r17.untiled
    assert r17.blocked == script.STRADDLE_NOTE
    assert r17.straddle == 1, r17.straddle
    last = r17.tokens[-1]
    assert last.off < len(r17.data) < last.off + last.size
    assert r17.data[last.off:].hex(" ") == "10 01 01 00", r17.data[last.off:].hex(" ")
    assert r17.spans, "its dialogue is still extracted"


def test_the_last_token_reads_the_next_records_first_byte():
    """r17's `10 01 01 00` wants one more byte, and takes r18's first."""
    _sc, cont = _cont()
    rr = [records.Record(r.id, r.data) for r in cont]
    image, base = records.runtime_image(rr), records.bases(rr)
    r17 = next(r for r in cont if r.id == 0x17)
    r18 = next(r for r in cont if r.id == 0x18)
    assert base[0x18] == base[0x17] + len(r17.data)
    last = r17.tokens[-1]
    got = image[base[0x17] - records.INDEX_SIZE + last.off:
                base[0x17] - records.INDEX_SIZE + last.off + last.size]
    assert got[-1] == r18.data[0], (got.hex(" "), r18.data[:2].hex(" "))


def test_the_losing_copy_of_a_duplicate_id_is_tiled_in_isolation():
    """It is never installed, so nothing follows it in the image.

    Found by breaking it: tiling every record at `bases()[id]` walks the *first*
    copy's bytes with the *second* copy's length, which produced spans whose text
    did not re-encode to its own bytes (`m/MS6012` c4 0x14) and a table row the
    writer refused.
    """
    sc = script.parse("m/MS6012.BIN", files.read_source("m/MS6012.BIN"))
    cont = sc.containers[4]
    dupes = [r for r in cont if r.id == 0x14]
    assert len(dupes) == 2, len(dupes)
    for r in dupes:
        for sp in r.spans:
            assert sp.end <= len(r.data), (r.order, sp.off, sp.end, len(r.data))


# --- what the builder does about them ---------------------------------------
def test_branch_targets_include_a_straddling_record():
    """3a: a branch into straddling text still protects that text."""
    _sc, cont = _cont()
    rr = [records.Record(r.id, r.data) for r in cont]
    base = records.bases(rr)
    got = script._branch_targets(cont, base)
    # the mutation: without their tokens the set shrinks
    saved = {}
    for r in cont:
        if r.straddle:
            saved[r.id], r.tokens = r.tokens, None
    assert saved, "m/MS0031 c0 has no straddling record any more"
    without = script._branch_targets(cont, base)
    for r in cont:
        if r.id in saved:
            r.tokens = saved[r.id]
    assert without < got, (len(without), len(got))


def test_the_builder_refuses_to_edit_a_straddling_record():
    sc, cont = _cont()
    r17 = next(r for r in cont if r.id == 0x17)
    sp = r17.spans[0]
    out, rep = script.build(sc, {(0, 0x17, sp.idx): "English"})
    assert rep.errors and "@straddle" in rep.errors[0], rep.errors[:2]
    assert out == sc.raw, "the record was rebuilt anyway"


def test_the_builder_refuses_a_span_holding_a_previous_records_operand_bytes():
    """r0B's `pairs_ff` runs 406 bytes into r0C, over all fourteen of its spans.

    Editing one of those spans would rewrite the operands of an instruction in a
    record the edit never named.  Twenty spans corpus-wide are refused for this:
    fourteen here, two in `m/MS610D` and four in the two `data` files.
    """
    sc, cont = _cont()
    r0b = next(r for r in cont if r.id == 0x0B)
    r0c = next(r for r in cont if r.id == 0x0C)
    assert r0b.straddle == 406, r0b.straddle
    assert r0c.spans
    inside = [s for s in r0c.spans if s.off < r0b.straddle]
    assert len(inside) == 14, len(inside)
    out, rep = script.build(sc, {(0, 0x0C, s.idx): "English" for s in r0c.spans})
    # Counted, but not pinned to a single number: one or two of the fourteen are
    # already refused a step earlier by `_drop_branched_into` (a branch lands
    # inside them), and which guard gets there first is not the point.
    assert rep.straddled_into >= 13, rep.straddled_into

    # The property that is the point: no English is written into r0B's reach,
    # while r0C's later spans are edited.
    after = script.parse(REL, out)
    a0c = next(x for x in after.containers[0] if x.id == 0x0C)
    assert b"English" not in a0c.data[:r0b.straddle],         "English was written over r0B's operand bytes"
    assert b"English" in a0c.data, "nothing in r0C was edited at all"
    assert rep.changed_spans > 0, rep.changed_spans

    # What the guard does NOT prevent, recorded because `giten audit` reports
    # it and it is the strongest argument that r0B's 406-byte reading is wrong:
    # r0C's own `rel16` slots are relocated when the container moves, and those
    # bytes are inside r0B's token too.  No edit policy can fix that -- either
    # r0B is not really reading 406 bytes, or r0B and r0C cannot both be built.
    assert a0c.data[:r0b.straddle] != r0c.data[:r0b.straddle], (
        "relocation no longer touches r0B's reach -- re-read the audit output "
        "before deleting this")


def test_relocation_leaves_a_straddling_records_bytes_verbatim():
    """Its rel16 reads a byte it does not own, so it cannot be rewritten here.

    Edit a record with a *lower* id, which moves everything above it, and check
    that the straddling record's own bytes come through unchanged.
    """
    sc, cont = _cont()
    victim = next(r for r in cont if r.id == 0x0E and r.spans and not r.blocked)
    out, rep = script.build(sc, {(0, victim.id, victim.spans[0].idx):
                                 "a much longer English line than the original"})
    assert rep.changed_records >= 1, rep.errors[:2]
    after = script.parse(REL, out)
    for r in cont:
        if not r.straddle:
            continue
        a = next(x for x in after.containers[0] if x.id == r.id and x.order == r.order)
        assert a.data == r.data, "r%02X was rewritten" % r.id


def test_the_straddle_states_are_what_the_census_says():
    from giten import tile
    rows = tile.census()
    assert sum(1 for r in rows if r.state == tile.STRADDLE) == 50
    assert not [r for r in rows if r.state == tile.PREFIX], (
        "prefix tiling is back; m/MS0080 should tile completely now")
