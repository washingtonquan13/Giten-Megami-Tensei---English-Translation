"""overlay.dat v6: a span found by the CONTENT of the record it translates.

v4 asked two questions the demon-conversation buffers cannot answer.  *Which
file is this?* -- answered by hashing the whole 1024-byte record index, which
belongs to a merge of up to five files and matches nothing we hold.  *Where does
this span go?* -- answered from our model of one file's record layout, which the
merge moves.  v5 answered the second question properly (a span said which record
it lived in and carried a hash of the Japanese it replaced) but kept the first,
so the answer still had to be *bound* to a buffer, and the binding went stale
every time the engine reused a handle -- which it does for every shop on a map
and for every demon.

v6 asks neither.  The key of a span is the content of its record::

    (record id, record length, FNV-1a of the record's bytes)

The hook finds the record the PC is in from the buffer's own index, hashes it,
and looks the triple up.  A record the merge moved is found, because the index
says where it went.  A record another file replaced is a different key and is
simply not there.  Neither case needs to know that a merge happened -- and
nothing survives a buffer swap that should not, because nothing is remembered
except a memo that re-checks the live index on every fetch.

These tests are the offline half plus the C conformance walks.  The C harness
needs to execute a freshly linked binary, which some environments refuse; see
``tests/harness.py``.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import files, overlay, paths, records, script, tables  # noqa: E402
from tests import harness  # noqa: E402

HOOK = os.path.join(paths.REPO_ROOT, "giten", "exe", "hook.c")
DRAFT = os.path.join(paths.BUILD_DIR, "tables_draft")

#: et/ET0007.BIN row 0: the demon whose conversation merges these onto MS6000
ROW0 = ("m/MS6000.BIN", "m/MS6003.BIN", "m/MS600A.BIN")

#: et/ET0007 row 17: this merge REPLACES four of m/MS6000's records, which is
#: the case the old all-or-nothing membership rule could not survive -- and
#: which v6 does not have to survive, because a replaced record is simply a
#: different key.
ROW17 = ("m/MS6000.BIN", "m/MS6100.BIN")

_TABLE = None


def draft_table():
    """The overlay table the shipped draft tree produces, planned once.

    Read from the draft tree rather than synthesised, because what is being
    tested is placement of the English we actually ship -- a synthetic row would
    prove the arithmetic and nothing about the corpus.
    """
    global _TABLE
    if _TABLE is None:
        if not os.path.isdir(DRAFT):
            _TABLE = False
        else:
            rows = [r for p in tables.iter_tables(DRAFT) for r in tables.read(p)]
            entries, _ = overlay.plan(rows, None)
            _TABLE = sorted(entries, key=lambda e: e.key)
    return _TABLE or None


def _recs(rel, ci=0):
    sc = script.parse(rel, files.read_source(rel))
    return sc.containers[ci] if ci < len(sc.containers) else []


def merged_image(rels, ci=0):
    """The image the engine builds: later files replace earlier ones by id."""
    m = {}
    for rel in rels:
        seen = set()
        for r in _recs(rel, ci):
            if r.id not in seen:            # first occurrence wins within a file
                seen.add(r.id)
                m[r.id] = r.data
    return overlay.image_bytes([records.Record(i, m[i]) for i in sorted(m)])


def _key(image, rec_id):
    off, ln = overlay.live_index(image)[rec_id]
    return rec_id, ln, overlay.fnv1a(image[off:off + ln])


def test_the_hook_and_the_builder_agree_on_the_format_version():
    """A mismatch is silent: the hook sets state -1 and the game plays in
    Japanese, with nothing on screen or on disk saying why."""
    src = io.open(HOOK, encoding="utf-8").read()
    m = re.search(r"#define OVERLAY_VERSION (\d+)", src)
    assert m, "hook.c no longer names the overlay version it reads"
    assert int(m.group(1)) == overlay.VERSION, (
        "hook.c reads v%s, giten/overlay.py writes v%d" % (m.group(1), overlay.VERSION))
    assert "h->version != OVERLAY_VERSION" in src


def test_the_hook_reads_the_same_fields_the_builder_writes():
    """Field order is the format; C alignment happens to match the struct
    formats here, and this is what says so out loud."""
    src = io.open(HOOK, encoding="utf-8").read()
    m = re.search(r"struct rec \{([^}]*)\}", src, re.S)
    assert m, "struct rec not found in hook.c"
    got = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", m.group(1))
    assert got == ["u16", "rec_id", "jp_len", "u32", "jp_hash", "span_first",
                   "u16", "nspans", "tail_total"], got
    assert overlay.REC.size == 16, overlay.REC.size

    m = re.search(r"struct span \{([^}]*)\}", src, re.S)
    assert m, "struct span not found in hook.c"
    got = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", m.group(1))
    assert got == ["u16", "rec_off", "jp_len", "served", "len", "virt_off",
                   "pad", "u32", "data_off"], got
    assert overlay.SPAN.size == 16, overlay.SPAN.size


def test_the_hook_has_no_file_identity_left():
    """The definition of done, as a test.

    Every one of these names belonged to the machinery that decided *which file
    a buffer is*.  That question is what went stale, so the fix is not a better
    answer to it -- it is that the hook never asks.
    """
    src = io.open(HOOK, encoding="utf-8").read()
    code = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)     # comments may say why
    for gone in ("FILEID", "MAX_MERGE", "entry_fits", "rebind", "struct dir",
                 "c_fid", "merged_slot", "FP_BYTES", "MAX_SPANS"):
        assert gone not in code, "hook.c still uses %s" % gone
    assert not re.search(r"\bfp\b", code), "hook.c still has an fp"
    # and it is keyed on content instead
    assert "find_entry" in code and "jp_hash" in code
    assert "fnv1a(base + off, ln)" in code, (
        "the hook no longer hashes the record it is standing in")


def test_a_record_finds_itself_in_the_merged_buffer():
    """The whole point: m/MS6000's English, placed in the buffer the engine
    actually builds for a demon conversation, with no notion of a file."""
    table = draft_table()
    if table is None:
        return                      # build/tables_draft not generated

    own = merged_image(["m/MS6000.BIN"])
    merged = merged_image(ROW0)
    assert overlay.live_end(merged) > overlay.live_end(own)

    alone = moved = 0
    oidx, midx = overlay.live_index(own), overlay.live_index(merged)
    for rec in range(256):
        if oidx[rec][1] <= 1:
            continue
        e = overlay.find_entry(table, *_key(own, rec))
        if e is None:
            continue
        alone += 1
        # the same key, found in the merge, at whatever address the merge put it
        assert overlay.find_entry(table, *_key(merged, rec)) is e, "record %02X" % rec
        if oidx[rec][0] != midx[rec][0]:
            moved += 1
    assert alone > 20, alone
    # ...and it is not a no-op: the merge really does move records we translate,
    # which is the case no static model of one file's layout could follow
    assert moved >= 5, "only %d record(s) moved; is this still a merge?" % moved


def test_a_record_refuses_a_buffer_that_is_not_its_own():
    """The hash is the whole safety argument, so prove it rejects.

    A record *id* that exists in both files but holds different bytes must not
    resolve to m/MS6000's entry -- that is the exact shape of the bug v6
    removes, and the only thing standing between them is the content hash.
    """
    table = draft_table()
    if table is None:
        return

    own = merged_image(["m/MS6000.BIN"])
    oidx = overlay.live_index(own)
    mine = {rec: overlay.find_entry(table, *_key(own, rec))
            for rec in range(256) if oidx[rec][1] > 1}
    mine = {k: v for k, v in mine.items() if v is not None}
    assert mine

    checked = 0
    for other in ("m/MS0017.BIN", "m/MS6003.BIN"):
        img = merged_image([other])
        idx = overlay.live_index(img)
        for rec, e in mine.items():
            if idx[rec][1] <= 1:
                continue
            if img[idx[rec][0]:idx[rec][0] + idx[rec][1]] == \
               own[oidx[rec][0]:oidx[rec][0] + oidx[rec][1]]:
                continue                    # genuinely the same record
            got = overlay.find_entry(table, *_key(img, rec))
            assert got is not e, (
                "record %02X of %s resolved to m/MS6000's entry" % (rec, other))
            checked += 1
    assert checked > 5, checked


def test_virtual_addresses_follow_the_image_end():
    """A merged buffer is longer, so English that did not fit in place has to
    move up with it or it lands on records that only exist in the merge.

    v6 does that by construction: a tail's address is ``image_end + virt_off``
    and ``image_end`` is read out of the running buffer, so it cannot be
    anything else.  What is checkable is the bound -- the tail must still fit
    under 0x10000 in the longest buffer the record can be in.
    """
    table = draft_table()
    if table is None:
        return
    for rels in (["m/MS6000.BIN"], ROW0, ROW17):
        image = merged_image(rels)
        end = overlay.live_end(image)
        idx = overlay.live_index(image)
        tails = 0
        for rec in range(256):
            if idx[rec][1] <= 1:
                continue
            e = overlay.find_entry(table, *_key(image, rec))
            if e is None:
                continue
            assert end + e.tail_total <= overlay.PC_LIMIT, (rels, rec)
            for s in e.spans:
                if s.tail:
                    tails += 1
                    assert end + s.virt_off >= end
        assert tails, "no tails to check for %s" % (rels,)


def _walk_every_record(exe, tmp, table, image, what):
    """Walk every live record of ``image`` through the C hook and the model."""
    p = os.path.join(tmp, "img.bin")
    with open(p, "wb") as fh:
        fh.write(image)
    idx = overlay.live_index(image)
    live = [r for r in range(256) if idx[r][1] > 1]
    lines = ["load 3 %s" % harness.quoted(p)]
    for r in live:
        lines.append("walk 3 %d %d" % (idx[r][0], idx[r][0] + idx[r][1]))
    got = harness.walks(exe, tmp, lines)
    assert len(got) == len(live)
    for (bs, pc), r in zip(got, live):
        want = overlay.Model(table, image).walk(idx[r][0], idx[r][0] + idx[r][1])
        assert bs == want, "%s: record %02X" % (what, r)
        assert pc == idx[r][0] + idx[r][1]
    return len(live)


def test_the_c_hook_serves_a_merged_buffer_the_way_the_model_does():
    """The end-to-end proof for the demon-conversation fix.

    Everything above this runs the Python model.  This runs the exact hook.c
    that goes into the exe, over the image the engine really builds for a demon
    conversation, and demands the same bytes the model gives.

    Without it the fix would rest on the model and the C agreeing by
    construction, which is the assumption that produced every bug on this list.
    """
    table = draft_table()
    if table is None:
        return
    tmp = tempfile.mkdtemp(prefix="giten-merge-")
    try:
        exe = harness.build(tmp, "the merged-buffer path")
        if exe is None:
            return
        with open(os.path.join(tmp, "overlay.dat"), "wb") as fh:
            fh.write(overlay.build(table))
        image = merged_image(ROW0)
        checked = _walk_every_record(exe, tmp, table, image, "ROW0")
        # 98 records carry data in this merged image; the number is pinned so
        # that a walk which quietly stops covering the buffer fails here.
        assert checked == 98, "%d records walked, expected 98" % checked

        # and the English really is in there -- otherwise the walk above would
        # pass just as well with the overlay switched off
        idx = overlay.live_index(image)
        whole = b"".join(overlay.Model(table, image).walk(idx[r][0], idx[r][0] + idx[r][1])
                         for r in range(256) if idx[r][1] > 1)
        for wanted in (b"Friendly", b"Intimidating", b">How will you speak to them?",
                       b"Gaze passionately", b"Persuade"):   # the last two are demon files
            assert wanted in whole, wanted
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_c_hook_serves_a_merge_that_displaced_a_record():
    """The merge that REPLACES four of m/MS6000's records.

    Under v4/v5's all-or-nothing membership rule this became "serve none of this
    file".  Under v6 it is not a case at all: a replaced record is different
    bytes, so it is a different key, and every other record of the buffer is
    found exactly as before.
    """
    table = draft_table()
    if table is None:
        return
    image = merged_image(ROW17)
    own = merged_image(["m/MS6000.BIN"])
    oidx, midx = overlay.live_index(own), overlay.live_index(image)
    displaced = [r for r in range(256)
                 if oidx[r][1] > 1 and midx[r][1] > 1
                 and own[oidx[r][0]:oidx[r][0] + oidx[r][1]]
                 != image[midx[r][0]:midx[r][0] + midx[r][1]]]
    assert displaced, "this merge is supposed to displace some records"

    tmp = tempfile.mkdtemp(prefix="giten-merge17-")
    try:
        exe = harness.build(tmp, "the displaced-record path")
        if exe is None:
            return
        with open(os.path.join(tmp, "overlay.dat"), "wb") as fh:
            fh.write(overlay.build(table))
        checked = _walk_every_record(exe, tmp, table, image, "ROW17")
        assert checked == 73, "%d records walked, expected 73" % checked

        # and it is the negotiation English, not just any bytes
        idx = overlay.live_index(image)
        whole = b"".join(overlay.Model(table, image).walk(idx[r][0], idx[r][0] + idx[r][1])
                         for r in range(256) if idx[r][1] > 1)
        for wanted in (b"It seems to have understood",
                       b" put heart and soul into speaking",
                       b"The COMP seems to be malfunctioning"):
            assert wanted in whole, wanted
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
