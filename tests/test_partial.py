"""Prefix tiling and its safety kernel.

The whole risk of serving text from a partially-understood record is that a span
boundary is wrong, because the hook replaces every byte in ``[start, start+served)``
and then resumes at ``end``.  So these tests are mostly about *refusal*: the kernel
has to reject the spans that a naive "everything before the failure" rule would
happily emit.
"""
from __future__ import annotations

import glob
import io
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


def test_prefix_tiling_is_retired_and_nothing_opts_into_it():
    """The opt-in list is gone, and so is the branch that read it.

    ``m/MS0080`` was the only file on it, and it tiles completely since the
    tokenizer started walking the container image: the six-byte trailer that
    defeated a record-in-isolation walk reads its last byte out of the record
    with the next id, like any other straddling token.  So there is nothing left
    for the prefix path to do, and `script.parse` no longer has a branch that
    calls it.

    The kernel below is kept on purpose -- it is the written form of the safety
    condition and the tests above still exercise all three of its checks -- so
    this asserts the *wiring* is gone, not the module.
    """
    from giten import script
    assert not hasattr(partial, "PREFIX_TILE_FILES")
    assert partial.PREFIX_TILING_RETIRED
    src = io.open(script.__file__, encoding="utf-8").read()
    assert "PREFIX_TILE_FILES" not in src, "script.parse still opts files in"
    sc = script.parse(SHOPS, files.read_source(SHOPS))
    for rec in sc.iter_records():
        assert rec.blocked != script.PREFIX_NOTE, rec.key
        if rec.data:
            assert rec.tokens is not None, rec.key


def test_the_five_shop_records_are_never_served():
    """The strict rule, on the file it actually costs something.

    `m/MS0080` tiles, so nothing about the model refuses it.  What refuses it is
    the engine: each of the five records was warped to and dispatched exactly two
    tokens -- the `1F 00` no-op and the `02 1F` pool call at 0x0002, whose return
    lands on the `00` terminator at 0x0004 -- and drew nothing, five times out of
    five, while three independent searches found nothing in the game that names
    file 0x80 at all.  The shop dialogue at 0x0009 is never reached.

    So the overlay does not serve it, and says so per row rather than silently.
    Ten of the twenty rows carry English; all ten are for a screen no session can
    reach, which is the whole of what the rule costs on this corpus.
    """
    from giten import extract_v2, overlay, paths, pool

    rows = extract_v2.rows_for(SHOPS, files.read_source(SHOPS),
                               pool.load(paths.ORIGINAL_DDSWIN))
    assert len(rows) == 20, len(rows)
    assert all("@noedit" in r.note for r in rows),         [r.rec for r in rows if "@noedit" not in r.note]
    for i, r in enumerate(rows):
        # every row, not just the blank ones: half of them are pre-filled with
        # their own Japanese, which is not an edit and would not be planned
        r.en = "English placeholder %d" % i
    entries, findings = overlay.plan(rows, paths.ORIGINAL_DDSWIN)
    assert not entries, "a record nothing enters was planned into the overlay"
    assert len(findings) == 20, len(findings)
    for _where, why in findings:
        assert "nothing enters this file" in why, why


def test_serving_english_never_changes_a_byte_outside_a_span():
    """The end-to-end safety proof for the overlay path.

    Stated exactly: outside the served ranges the hook must return the original
    image byte.  Inline ops *inside* a span (pool calls, newlines) are span
    content and may differ.  What may never change is a byte the interpreter
    dispatches as structure.

    Run on `m/MS0017`, an ordinary served file.  It used to run on `m/MS0080`,
    which was the worked example for prefix tiling; that file is not served at
    all now (nothing enters it), so the proof moved to a file where it is about
    something that ships.
    """
    from giten import codec, extract_v2, overlay, paths, pool, records

    rel = "m/MS0017.BIN"
    rows = extract_v2.rows_for(rel, files.read_source(rel),
                               pool.load(paths.ORIGINAL_DDSWIN))
    for r in rows:
        # plain ASCII, and only where the Japanese holds no 0xFF (which the
        # overlay counts) -- the point here is the bytes outside the spans
        if not codec.has_japanese(r.jp) or "{" in r.jp:
            continue
        r.en = "English line %d" % r.idx
    entries, findings = overlay.plan(rows, paths.ORIGINAL_DDSWIN)
    assert entries and not findings, findings[:3]

    sc = script.parse(rel, files.read_source(rel))
    cont = sc.containers[0]
    rr = [records.Record(r.id, r.data) for r in cont]
    base = records.bases(rr)
    image = overlay.image_bytes(rr)

    hook = overlay.Model(entries, image)
    table = sorted(entries, key=lambda e: e.key)
    served, ends = [], []
    for r in cont:
        e = overlay.find_entry(table, r.id, len(r.data), overlay.fnv1a(r.data))
        if e is None:
            continue
        for s in e.spans:
            lo_ = base[r.id] + s.rec_off
            served.append((lo_, lo_ + s.served))
            ends.append(lo_ + s.jp_len)
    assert served

    checked = 0
    for r in cont:
        if not r.data:
            continue
        lo, hi = base[r.id], base[r.id] + len(r.data)
        for pc in range(lo, hi):
            if any(a <= pc < b for a, b in served):
                continue
            got, _nxt = hook.fetch(pc)
            assert got == image[pc],                 "pc 0x%04X outside every span served %02X, image has %02X"                 % (pc, got, image[pc])
            checked += 1
    assert checked > 50, checked

    # and every span resumes on the untouched image
    for end in ends:
        if end < len(image):
            assert overlay.Model(entries, image).fetch(end)[0] == image[end], hex(end)
