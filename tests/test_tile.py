"""The census, and the engine's own tiling read back out of a trace.

The fixtures under ``tests/data/observed/`` are the only evidence in this repo
that does not come from the model: each one is a list of program counters the
*engine* started a token at, in one record, identified by that record's content.
:func:`test_the_model_tiles_every_boundary_the_engine_was_observed_at` is
therefore the one check a model change cannot satisfy by changing both sides.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import files, overlay, paths, script, tile

ROPPONGI = os.path.join(paths.BUILD_DIR, "traces", "2026-09-11-roppongi-trace.bin")
PLAY = os.path.join(os.path.dirname(paths.REPO_ROOT), "play", "en", "ddswin")


def test_observe_refuses_a_trace_with_no_record_hash():
    old = os.path.join(paths.REPO_ROOT, "traces", "2026-09-08-warp17-spill.bin")
    if not os.path.exists(old):
        return
    try:
        tile.read_events(old)
    except tile.TooOld:
        return
    raise AssertionError("a v2 trace was accepted; it carries no record hash")


def test_a_boundary_is_pc0_minus_the_width_of_the_dispatched_character():
    """The rule, on a synthetic event, both widths.

    `pc0` is one past the token's FIRST byte because the caller fetches that
    byte before calling exec_token -- the operands are consumed later, inside
    the handler.  Getting this wrong puts every boundary one token too far
    along, which is the bug the old `partial.observed_boundaries` had.
    """
    ev = tile.Ev(0, 0, 0, 0, ch=0x82A0, idx_off=0x400, idx_len=10, pc0=0x40A,
                 flags=tile.core.REC_FROM_PC, rec_hash=0, image_end=0, handle=0)
    assert ev.width == 2
    assert ev.pc0 - ev.width - ev.idx_off == 8
    ev = tile.Ev(0, 0, 0, 0, ch=0x1F, idx_off=0x400, idx_len=10, pc0=0x409,
                 flags=tile.core.REC_FROM_PC, rec_hash=0, image_end=0, handle=0)
    assert ev.width == 1
    assert ev.pc0 - ev.width - ev.idx_off == 8


def test_the_model_tiles_every_boundary_the_engine_was_observed_at():
    """The acceptance test for the whole model, on the records it has answers for."""
    fixtures = tile.load_fixtures()
    assert fixtures, "no observed fixtures; run `giten tile observe --write-fixtures`"
    bad = []
    for fx in fixtures:
        rel, ci, rec_id = fx["rel"], fx["ci"], fx["rec"]
        sc = script.parse(rel, files.read_source(rel))
        # By CONTENT, not by position: `m/MS6800` c0 holds record 0x0E twice
        # with different bytes, and the engine keeps the *last* copy installed.
        # Taking the first would compare the fixture against a record the engine
        # never executed.
        rec = next((r for r in sc.containers[ci]
                    if r.id == rec_id and overlay.fnv1a(r.data) == fx["hash"]),
                   None)
        assert rec is not None, (
            "%s c%d r%02X: no record with the observed bytes any more"
            % (rel, ci, rec_id))
        toks = rec.span_tokens or []
        starts = {t.off for t in toks}
        miss = [b for b in fx["boundaries"] if b not in starts]
        if miss:
            bad.append((rel, ci, rec_id, miss[:8]))
    assert not bad, (
        "the model no longer starts a token where the engine did: %s" % bad[:10])


def test_every_observed_record_still_parses_to_the_bytes_it_was_observed_in():
    """A fixture names a record by content; the census has to still hold it."""
    fixtures = tile.load_fixtures()
    keys = {(r.rel, r.ci, r.rec_id) for r in tile.census()}
    for fx in fixtures:
        assert (fx["rel"], fx["ci"], fx["rec"]) in keys, fx["rel"]


def test_observe_agrees_with_the_engine_on_the_roppongi_session():
    """The validation run: a real four-hour session, and zero disagreements.

    The session ran with `overlay.dat` installed, so the engine was handed
    English bytes inside every record the overlay serves and a boundary read off
    one of those events would be measured against text that was never there.
    Those records are dropped rather than judged -- which is exactly why
    `giten warp` builds a tree with no overlay.
    """
    if not (os.path.exists(ROPPONGI) and os.path.isdir(PLAY)):
        return
    rep = tile.observe(ROPPONGI, PLAY)
    assert rep.version == 4, rep.version
    assert len(rep.seen) == 246, len(rep.seen)
    assert rep.agree == 1414, rep.agree
    assert rep.disagree == 0, [
        (k, v["disagree"]) for k, v in rep.seen.items() if v["disagree"]][:10]
    # and the overlay exclusion is doing real work, not nothing
    assert rep.overlaid > 100000, rep.overlaid
