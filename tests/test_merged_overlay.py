"""overlay.dat v5: a span placed against the buffer that is actually running.

v4 asked two questions the demon-conversation buffers cannot answer.  *Which
file is this?* -- answered by hashing the whole 1024-byte record index, which
belongs to a merge of up to five files and matches nothing we hold.  *Where does
this span go?* -- answered from our model of one file's record layout, which the
merge moves.  So `rebind()` returned 0 and 7,943 spans were never served.

v5 asks neither.  A span says which record it lives in and where inside it, and
carries a hash of the Japanese it replaces:

    addr = live_index[rec].offset + rec_off
    serve only if fnv1a(live[addr : addr + jp_len]) == jp_hash

A record the merge moved is found, because the live index says where it went.
A record another file replaced fails the hash and is dropped -- not served at a
plausible-looking address, which is the failure mode that matters.  Virtual
addresses shift with the image end for the same reason: a merged buffer is
longer, and tails handed out from the old end would land on real records.

These tests are the offline half.  The C hook implements the same rules and
`tests/test_overlay.py` walks both over the same data; that test needs to
execute a freshly linked binary, which some environments refuse.
"""
from __future__ import annotations

import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import files, overlay, paths, records, script

HOOK = os.path.join(paths.REPO_ROOT, "giten", "exe", "hook.c")
BUILT = os.path.join(paths.BUILD_DIR, "overlay-v5.dat")

#: et/ET0007.BIN row 0: the demon whose conversation merges these onto MS6000
ROW0 = ("m/MS6000.BIN", "m/MS6003.BIN", "m/MS600A.BIN")


def _recs(rel, ci=0):
    sc = script.parse(rel, files.read_source(rel))
    return sc.containers[ci] if ci < len(sc.containers) else []


def _merged(rels, ci=0):
    """The image the engine builds: later files replace earlier ones by id."""
    m = {}
    for rel in rels:
        seen = set()
        for r in _recs(rel, ci):
            if r.id not in seen:            # first occurrence wins within a file
                seen.add(r.id)
                m[r.id] = r.data
    return overlay.image_bytes([records.Record(i, m[i]) for i in sorted(m)])


def _entry_for(rel, ci=0):
    """The overlay entry the shipped tables produce for one container.

    Read from the draft tree rather than synthesised, because what is being
    tested is placement of the English we actually ship -- a synthetic row would
    prove the arithmetic and nothing about the corpus.
    """
    from giten import tables
    path = os.path.join(paths.BUILD_DIR, "tables_draft", *rel.split("/"))
    path += ".tsv"
    if not os.path.exists(path):
        return None, None               # tree not generated in this checkout
    entries, _ = overlay.plan(tables.read(path), None)
    own = [records.Record(r.id, r.data) for r in _recs(rel, ci)]
    fp = overlay.fingerprint(own)
    return next((e for e in entries if e.fp == fp), None), own


def test_the_hook_and_the_builder_agree_on_the_format_version():
    """A mismatch is silent: the hook sets state -1 and the game plays in
    Japanese, with nothing on screen or on disk saying why."""
    src = io.open(HOOK, encoding="utf-8").read()
    m = re.search(r'"GTOV" \*/ \|\| h->version != (\d+)\)', src)
    assert m, "hook.c no longer checks the overlay version the same way"
    assert int(m.group(1)) == overlay.VERSION, (
        "hook.c reads v%s, giten/overlay.py writes v%d" % (m.group(1), overlay.VERSION))


def test_the_hook_reads_the_same_span_fields_the_builder_writes():
    """Field order is the format; C alignment happens to match `<HHHHHHIHHI>`
    here, and this is what says so out loud."""
    src = io.open(HOOK, encoding="utf-8").read()
    m = re.search(r"struct span \{([^}]*)\}", src, re.S)
    assert m, "struct span not found in hook.c"
    got = [f.strip() for f in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", m.group(1))]
    want = ["u16", "start", "jp_len", "virt", "len", "served", "pad",
            "u32", "data_off", "u16", "rec", "rec_off", "u32", "jp_hash"]
    assert got == want, got
    assert overlay.SPAN.size == 24, overlay.SPAN.size


def test_a_span_finds_itself_in_the_merged_buffer():
    """The whole point: m/MS6000's English, placed in the buffer the engine
    actually builds for a demon conversation."""
    e, own = _entry_for("m/MS6000.BIN")
    if e is None:
        return                      # build/tables_draft not generated

    assert e.spans

    alone = overlay.resolve(e, overlay.image_bytes(own))
    assert len(alone) == len(e.spans), "%d of %d resolve against the file itself" % (
        len(alone), len(e.spans))

    merged = overlay.resolve(e, _merged(ROW0))
    assert len(merged) == len(e.spans), "%d of %d resolve against the merge" % (
        len(merged), len(e.spans))

    # ...and it is not a no-op: the merge really does move most of them
    by_key = {(s.rec_id, s.rec_off): s.start for s in alone}
    moved = [s for s in merged if by_key[(s.rec_id, s.rec_off)] != s.start]
    assert len(moved) > 20, "only %d span(s) moved; is this still a merge?" % len(moved)


def test_a_span_refuses_a_buffer_that_is_not_its_own():
    """The hash is the whole safety argument, so prove it rejects."""
    e, own = _entry_for("m/MS6000.BIN")
    if e is None:
        return                      # build/tables_draft not generated

    for other in ("m/MS0017.BIN", "m/MS6003.BIN"):
        img = overlay.image_bytes([records.Record(r.id, r.data) for r in _recs(other)])
        got = overlay.resolve(e, img)
        assert got == [], "%d of m/MS6000's spans resolved inside %s" % (len(got), other)


def test_virtual_addresses_follow_the_image_end():
    """A merged buffer is longer, so English that did not fit in place has to
    move up with it or it lands on records that only exist in the merge."""
    e, own = _entry_for("m/MS6000.BIN")
    if e is None:
        return                      # build/tables_draft not generated

    solo, merged = overlay.image_bytes(own), _merged(ROW0)
    assert overlay._live_end(merged) > overlay._live_end(solo)
    for img in (solo, merged):
        end = overlay._live_end(img)
        tails = [s for s in overlay.resolve(e, img) if s.tail]
        assert tails, "no tails to check"
        assert min(s.virt for s in tails) >= end, "a tail overlaps a real record"
        assert max(s.vend for s in tails) <= overlay.PC_LIMIT


def test_no_entry_is_larger_than_the_hook_can_verify():
    """The hook keeps one bit per span in a fixed array and refuses an entry it
    cannot cover, so the cap has to be above the real worst case."""
    src = io.open(HOOK, encoding="utf-8").read()
    cap = int(re.search(r"#define MAX_SPANS (\d+)", src).group(1))
    assert re.search(r"nspans > MAX_SPANS", src), (
        "hook.c no longer refuses an entry it cannot verify")
    if not os.path.exists(BUILT):
        return                      # nothing built in this checkout
    ents = overlay.parse(open(BUILT, "rb").read())
    worst = max(len(e.spans) for e in ents)
    assert worst <= cap, "%d spans in one entry, cap is %d" % (worst, cap)
