"""The demon-negotiation runtime image is a MERGE of several files.

Why this file exists
--------------------
``giten/records.py`` used to state, as a verified fact, that "each container is
its own runtime image, which is also what 0x43AA90 does: it loads exactly one
container per call".  The second half is true and the conclusion does not
follow.  ``0x0040EB00`` calls ``0x0043AA90`` sixteen times on one open file --
once per container slot -- and ``0x0040EB70`` calls ``0x0040EB00`` up to five
times with *different files*, all merging into the same sixteen buffers:

    0x0040EB70(row, id):
        0x0040EB00(row, 0x6000, kind 9, slots 0..15)        # m/MS6000, always
        t = table[id * 3]                                   # et/ET0007.BIN
        if t[0] != 0xFF: 0x0040EB00(row, 0x6000 + t[0], 9, 0..15)
        if t[1] != 0xFF: 0x0040EB00(row, 0x6000 + t[1], 9, 0..15)
        if t[2] != 0xFF: 0x0040EB00(row, 0x6100 + t[2], 9, 0..15)
        0x0040EB00(row, [row + 0x38], kind 14, 0..15)       # et/ID%04X.BIN

``0x0043ABC0`` writes each record into the shared 256-entry index by id,
resizing the buffer by ``new_len - old_len``, so a later file **replaces** an
earlier file's record and shifts every record with a higher id.

Why it matters
--------------
The overlay identifies a script buffer by ``(FILEID, fnv1a of the whole
1024-byte record index)``.  For this family neither half is knowable from a
filename: the engine reports ``0xE0 + slot`` as the file id (``0x0040EB57``
stamps the descriptor), and the index belongs to a merge chosen at runtime.
``rebind()`` therefore returns 0 and **every** span of English in m/MS6xxx --
7,943 of them -- is silently never served.  That is what the 2026-09-07
negotiation session showed on screen as Japanese.

The tests below pin the merge itself, so that a future "simplification" back to
one-container-per-image fails here rather than in a play session.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import files, overlay, paths, records, script


#: The engine's own index entries for slot 0 (the id it reports as 0x00E0),
#: read out of a recorded play session (build/trace/en-negotiate.bin,
#: 2026-09-07) by the tracer, which snapshots ``[handle_table[ctx.handle] +
#: rec * 4]`` before each token.  Kept as literal data so the finding outlives
#: the trace file.
ENGINE_INDEX_SLOT0 = {
    0x00: (0x0400, 143), 0x02: (0x04A2, 47),  0x07: (0x06C3, 119),
    0x17: (0x0C6C, 52),  0x18: (0x0CA0, 148), 0x20: (0x0DFE, 84),
    0x21: (0x0E52, 202), 0x29: (0x0FF9, 221), 0x2F: (0x1281, 90),
    0x30: (0x12DB, 89),  0x32: (0x13DA, 103), 0x65: (0x16DC, 65),
    0x97: (0x1BCE, 976), 0x9A: (0x1FFB, 557), 0x9B: (0x2228, 4),
}

#: The one entry no file on disk can account for: every other length and every
#: offset comes out right, including 0x97's own offset.  976 - 82 = 894 bytes
#: the engine puts there at runtime.  Left as a named exception rather than
#: fudged, because pretending to explain it would hide the real limit: the
#: index is not a static property of the files, so no static fingerprint of it
#: can identify this buffer.
RUNTIME_SIZED_RECORD = 0x97


def _lens(rel, ci=0):
    """``{record id: length}`` for one container, first occurrence wins."""
    sc = script.parse(rel, files.read_source(rel))
    if not sc.containers or ci >= len(sc.containers):
        return None
    out = {}
    for r in sc.containers[ci]:
        out.setdefault(r.id, len(r.data))
    return out


def _index(lens):
    """``{id: (offset, length)}`` under the engine's rule: data starts at
    0x400, absent records occupy one byte, ids are laid out in id order."""
    off, out = 0x400, {}
    for i in range(256):
        n = lens.get(i, records.ABSENT_LEN)
        out[i] = (off, n)
        off += n
    return out


def _agree(lens):
    idx = _index(lens)
    return sum(1 for rid, want in ENGINE_INDEX_SLOT0.items() if idx.get(rid) == want)


def test_et0007_is_the_demon_to_extra_scripts_table():
    """25 rows of 3 bytes behind a length word, each naming up to three files.

    0xFF means "no file in this position".  The first two are m/MS60xx, the
    third m/MS61xx -- which is why the table can point at 0x16 (MS6016) in one
    column and 0x0C (MS610C) in another without collision.
    """
    raw = files.read_source("et/ET0007.BIN")
    n = int.from_bytes(raw[:2], "little")
    assert n == 75, "table length word is %d, expected 75" % n
    assert len(raw) >= 2 + n
    rows = [tuple(raw[2 + i * 3:5 + i * 3]) for i in range(n // 3)]
    assert len(rows) == 25, len(rows)
    assert rows[0] == (0x03, 0x0A, 0xFF), rows[0]
    for t0, t1, t2 in rows:
        for fam, t in ((0x6000, t0), (0x6000, t1), (0x6100, t2)):
            if t == 0xFF:
                continue
            rel = "m/MS%04X.BIN" % (fam + t)
            assert os.path.exists(os.path.join(paths.game_root(), *rel.split("/"))), rel


def test_one_file_alone_cannot_be_the_negotiation_image():
    """m/MS6000 on its own explains only 10 of the 15 entries.

    This is the assertion that fails if anyone restores the old
    one-container-per-image reading: it is not a rounding error, it is five
    records in the wrong place, and every branch in them is measured against
    those offsets.
    """
    alone = _agree(_lens("m/MS6000.BIN"))
    assert alone == 10, "m/MS6000.BIN alone agrees on %d entries, expected 10" % alone


def test_the_merge_reproduces_the_engines_own_index():
    """MS6000 + MS6003 + MS600A (et/ET0007 row 0) explains 12 of 15, and the
    three it misses are one record.

    Record 0x97's *offset* is right and its length is not, so every record
    below it is placed correctly and the two above it (0x9A, 0x9B) are wrong by
    exactly 976 - 82 = 894.  Counting entries understates the model: 14 of the
    15 lengths and 13 of the 15 offsets are right, and one runtime-sized record
    accounts for everything that is left.
    """
    merged = dict(_lens("m/MS6000.BIN"))
    for rel in ("m/MS6003.BIN", "m/MS600A.BIN"):
        merged.update(_lens(rel))
    idx = _index(merged)

    wrong = sorted(rid for rid, want in ENGINE_INDEX_SLOT0.items() if idx.get(rid) != want)
    assert _agree(merged) == 12, "merge agrees on %d entries: %s" % (
        _agree(merged), ["%02X" % r for r in wrong])
    assert wrong == [0x97, 0x9A, 0x9B], ["%02X" % r for r in wrong]

    # every disagreement traces back to the one runtime-sized record
    assert idx[RUNTIME_SIZED_RECORD][0] == ENGINE_INDEX_SLOT0[RUNTIME_SIZED_RECORD][0]
    delta = (ENGINE_INDEX_SLOT0[RUNTIME_SIZED_RECORD][1]
             - idx[RUNTIME_SIZED_RECORD][1])
    for rid in (0x9A, 0x9B):
        assert idx[rid][0] + delta == ENGINE_INDEX_SLOT0[rid][0], rid
        assert idx[rid][1] == ENGINE_INDEX_SLOT0[rid][1], rid


def test_merging_is_what_moves_the_records_not_a_duplicate_id_rule():
    """MS6003 is the file that supplies record 0x32, and MS6000 does not have it.

    Ruled out first, and kept ruled out: within m/MS6000 container 0 only two
    ids repeat, and first / last / longest all produce the same index -- so the
    divergence was never about which duplicate wins.
    """
    a = _lens("m/MS6000.BIN")
    b = _lens("m/MS6003.BIN")
    assert a.get(0x32) != 103, "MS6000 already had record 0x32 at 103 bytes"
    assert b.get(0x32) == 103, "MS6003 no longer supplies record 0x32 at 103 bytes"

    sc = script.parse("m/MS6000.BIN", files.read_source("m/MS6000.BIN"))
    seen, dup = set(), set()
    for r in sc.containers[0]:
        (dup if r.id in seen else seen).add(r.id)
    assert len(dup) == 2, "container 0 now has %d duplicate ids" % len(dup)

    first, last = {}, {}
    for r in sc.containers[0]:
        first.setdefault(r.id, len(r.data))
        last[r.id] = len(r.data)
    assert _agree(first) == _agree(last) == 10


def test_no_static_index_can_identify_this_buffer_which_is_why_v6_does_not_try():
    """The finding that killed identity binding, kept as the reason it died.

    v4 and v5 identified a buffer by hashing its 1024-byte record index and
    matching that against a hash built from one container of one file.  This
    buffer defeats that twice over:

    * its index is the *merged* one, so no single container can equal it;
    * the merged index cannot even be computed statically, because record 0x97
      is 976 bytes at run time against 82 on disk -- the loader builds the rest.

    So the answer to "which file is this" was unavailable, and `rebind()`
    returned 0 for every demon conversation.  v6 does not ask: it reads the
    record the program counter is in out of the buffer's own index and keys on
    that record's bytes.  Both halves of the old obstacle are asserted here,
    because they are why the question was abandoned rather than answered better.
    """
    sc = script.parse("m/MS6000.BIN", files.read_source("m/MS6000.BIN"))
    recs = [records.Record(r.id, r.data) for r in sc.containers[0]]
    lone = overlay.fnv1a(overlay.engine_index(recs))

    merged = dict(_lens("m/MS6000.BIN"))
    for rel in ("m/MS6003.BIN", "m/MS600A.BIN"):
        merged.update(_lens(rel))
    idx = _index(merged)
    blob = bytearray()
    for i in range(256):
        off, ln = idx[i]
        blob += off.to_bytes(2, "little") + ln.to_bytes(2, "little")
    assert overlay.fnv1a(bytes(blob)) != lone, (
        "a single container now hashes the same as the merged image")

    # ...and even the merged index is not the engine's, because record 0x97 is
    # 894 bytes longer at run time than anything on disk.
    off, ln = idx[RUNTIME_SIZED_RECORD]
    assert (off, ln) != ENGINE_INDEX_SLOT0[RUNTIME_SIZED_RECORD]


def test_the_records_of_this_buffer_are_found_by_content_without_any_of_that():
    """And the same buffer, answered.

    Every record the merge leaves in place keeps its bytes, so it keeps its v6
    key -- and the address it moved to comes out of the buffer's own index, not
    out of any model of a file.  Including record 0x97, whose length no file on
    disk explains: it is simply a key we do not hold, and a key we do not hold
    is served nothing.
    """
    rels = ("m/MS6000.BIN", "m/MS6003.BIN", "m/MS600A.BIN")
    own, merged = {}, {}
    for rel in rels:                            # later files replace earlier ones
        sc = script.parse(rel, files.read_source(rel))
        seen = set()
        for r in sc.containers[0]:
            if r.id in seen:
                continue
            seen.add(r.id)
            merged[r.id] = r.data
            if rel == "m/MS6000.BIN":
                own[r.id] = r.data

    a = overlay.image_bytes([records.Record(i, own[i]) for i in sorted(own)])
    b = overlay.image_bytes([records.Record(i, merged[i]) for i in sorted(merged)])
    ia, ib = overlay.live_index(a), overlay.live_index(b)

    kept = moved = 0
    for i in sorted(own):
        if merged[i] != own[i]:
            continue                            # a record the merge replaced
        kept += 1
        ka = (i, ia[i][1], overlay.fnv1a(a[ia[i][0]:ia[i][0] + ia[i][1]]))
        kb = (i, ib[i][1], overlay.fnv1a(b[ib[i][0]:ib[i][0] + ib[i][1]]))
        assert ka == kb, "record %02X changed key in the merge" % i
        if ia[i][0] != ib[i][0]:
            moved += 1
    assert kept > 20 and moved > 5, (kept, moved)
