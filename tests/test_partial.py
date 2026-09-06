"""Prefix tiling and its safety kernel.

The whole risk of serving text from a partially-understood record is that a span
boundary is wrong, because the hook replaces every byte in ``[start, start+served)``
and then resumes at ``end``.  So these tests are mostly about *refusal*: the kernel
has to reject the spans that a naive "everything before the failure" rule would
happily emit.
"""
from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import files, partial, script, vmops  # noqa: E402

SHOPS = "m/MS0080.BIN"


def _rec(rel, rec_id):
    sc = script.parse(rel, files.read_source(rel))
    for cont in sc.containers:
        for r in cont:
            if r.id == rec_id:
                return r
    raise AssertionError("no record 0x%02X in %s" % (rec_id, rel))


def test_prefix_tiling_agrees_with_the_tokenizer_on_records_that_tile():
    """It must be the same function for every record that already works --
    otherwise adding it could disturb 20,440 records that ship today."""
    tab = vmops.table()
    checked = 0
    for p in sorted(glob.glob("original/ddswin/m/MS00*.BIN"))[:40]:
        rel = "m/" + os.path.basename(p)
        sc = script.parse(rel, files.read_source(rel))
        if not sc.ok:
            continue
        for cont in sc.containers:
            for r in cont:
                if not r.data or r.untiled:
                    continue
                full = vmops.tokenize(r.data, tab)
                pre, ok = partial.tokenize_prefix(r.data, tab)
                assert ok == len(r.data), (rel, r.id, ok, len(r.data))
                assert [(t.off, t.size, t.idx) for t in pre] == \
                       [(t.off, t.size, t.idx) for t in full], (rel, r.id)
                checked += 1
    assert checked > 200, checked


def test_the_shop_records_yield_exactly_their_real_text():
    accepted = {}
    for rec_id in range(5):
        r = _rec(SHOPS, rec_id)
        keep, ok, rejected = partial.safe_spans(SHOPS, 0, rec_id, r.data)
        assert ok < len(r.data), "record 0x%02X tiles fully now" % rec_id
        assert len(keep) == 2, (rec_id, len(keep))
        assert len(rejected) == 2, (rec_id, len(rejected))
        r.tokens = partial.tokenize_prefix(r.data)[0]
        accepted[rec_id] = [script.span_text(r, sp) for sp in keep]

    # the five shopkeepers, by name
    names = [accepted[i][0] for i in range(5)]
    assert names == ["武器屋：", "道具屋：", "薬屋：", "酒屋：", "病院："], names
    for i in range(5):
        assert "" not in accepted[i][1]
        assert len(accepted[i][1]) > 10


def test_the_header_artifacts_are_refused():
    """The naive rule would emit these: they lie before the failure point.  They
    come from a mis-tiled header (``02 1f`` read as opcode + operand), so their
    boundaries are not trustworthy."""
    r = _rec(SHOPS, 0)
    _keep, _ok, rejected = partial.safe_spans(SHOPS, 0, 0, r.data)
    offs = sorted(sp.off for sp, _why in rejected)
    assert offs == [2, 5], offs
    for _sp, why in rejected:
        assert "not a text-introducing opcode" in why, why


def test_a_span_outside_the_tiled_prefix_is_refused():
    r = _rec(SHOPS, 0)
    toks, ok = partial.tokenize_prefix(r.data)
    spans = script.find_spans(0, 0, r.data, toks)
    sp = [s for s in spans if s.off == 21][0]

    class Fake:                                  # same span, pretend the walk
        off, end = sp.off, sp.end                # stopped before it
    try:
        partial.verify_span(r.data, toks, 20, Fake())
    except partial.UnsafeSpan as exc:
        assert "not inside the tiled prefix" in str(exc), exc
    else:
        raise AssertionError("a span past the failure point was accepted")


def test_a_span_that_does_not_read_as_text_is_refused():
    """This is the check that catches a start landing mid-character -- exactly
    how the known-bad `j性：` spans present."""
    assert not partial._clean_text(b"\x1f\xd2\x95\x90", 0, 4)      # opcode inside
    assert not partial._clean_text(b"\x95", 0, 1)                  # half a char
    assert partial._clean_text("武器屋：".encode("cp932"), 0, 8)
    assert partial._clean_text(b"\x0a" + "あ".encode("cp932"), 0, 3)   # \n is inline


def test_every_accepted_span_is_pure_text_and_ends_on_a_boundary():
    for rec_id in range(5):
        r = _rec(SHOPS, rec_id)
        toks, ok = partial.tokenize_prefix(r.data)
        keep, _ok, _rej = partial.safe_spans(SHOPS, 0, rec_id, r.data)
        starts = {t.off for t in toks}
        for sp in keep:
            assert sp.off in starts and sp.end in starts, (rec_id, sp.off, sp.end)
            inside = [t for t in toks if sp.off <= t.off < sp.end]
            assert inside, (rec_id, sp.off)
            for t in inside:
                assert t.kind == "text" or t.idx in (0x00A,) or t.idx < 0x20, \
                    ("non-text token in span", rec_id, sp.off, t.kind, hex(t.idx or 0))


def test_the_trailer_is_never_served():
    """The six-byte trailer is what defeats the tokenizer; no accepted span may
    reach it, or the hook would serve English over an opcode."""
    FOOT = bytes.fromhex("1f0010010100")
    for rec_id in range(5):
        r = _rec(SHOPS, rec_id)
        assert r.data.endswith(FOOT)
        foot_at = len(r.data) - len(FOOT)
        keep, _ok, _rej = partial.safe_spans(SHOPS, 0, rec_id, r.data)
        for sp in keep:
            assert sp.end <= foot_at, (rec_id, sp.off, sp.end, foot_at)


def test_prefix_tiling_is_opt_in_per_file():
    assert SHOPS in partial.PREFIX_TILE_FILES
    assert len(partial.PREFIX_TILE_FILES) == 1, \
        "widen this only after the added file has been play-tested"


def test_serving_english_never_changes_a_byte_outside_a_span():
    """The end-to-end safety proof for the overlay path.

    Stated exactly: outside the served ranges the hook must return the original
    image byte.  Inline ops *inside* a span (pool calls, newlines) are span
    content and may differ -- the English for r03 drops two {08:25} calls.  What
    may never change is a byte the interpreter dispatches as structure, and in
    particular the six-byte trailer that defeats the tokenizer.
    """
    from giten import extract_v2, overlay, paths, pool, records

    rows = extract_v2.rows_for(SHOPS, files.read_source(SHOPS),
                               pool.load(paths.ORIGINAL_DDSWIN))
    assert len(rows) == 10, len(rows)
    for r in rows:
        if not r.en:
            r.en = "English placeholder"
    entry_list, findings = overlay.plan(rows, paths.ORIGINAL_DDSWIN)
    assert not findings, findings
    entry = entry_list[0]

    sc = script.parse(SHOPS, files.read_source(SHOPS))
    cont = sc.containers[0]
    rr = [records.Record(r.id, r.data) for r in cont]
    base = records.bases(rr)
    image = bytearray(0x10000)
    idx = overlay.engine_index(rr)
    image[:len(idx)] = idx
    for r in cont:
        image[base[r.id]:base[r.id] + len(r.data)] = r.data
    image = bytes(image)

    hook = overlay.Model(entry, image)
    served = [(s.start, s.start + s.head) for s in entry.spans]
    FOOT = bytes.fromhex("1f0010010100")

    checked = 0
    for r in cont:
        if not r.data:
            continue
        lo, hi = base[r.id], base[r.id] + len(r.data)
        foot_at = hi - len(FOOT)
        # no span may reach into the trailer
        assert not [1 for a, b in served if a < hi and b > foot_at], \
            "a span overlaps the trailer of record 0x%02X" % r.id
        for pc in range(lo, hi):
            if any(a <= pc < b for a, b in served):
                continue
            got, _nxt = hook.fetch(pc)
            assert got == image[pc], \
                "pc 0x%04X outside every span served %02X, image has %02X" \
                % (pc, got, image[pc])
            checked += 1
    assert checked > 50, checked

    # and every span resumes on the untouched image
    for s in entry.spans:
        if s.end < len(image):
            assert hook.fetch(s.end)[0] == image[s.end], hex(s.end)
