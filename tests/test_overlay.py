"""The runtime overlay: table format, the reference model against the byte-edit
builder, the virtual-space rule, and the C hook against the model."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import codec, files, overlay, paths, records, script, tables, vmops  # noqa: E402
from tests import harness  # noqa: E402

REL = "m/MS0017.BIN"
POOL = "m/MS7F03.BIN"


def _rows(rel, sc, text_for, rec_ids=None):
    """Synthetic edited rows for every span of the chosen records."""
    out = []
    for rec in sc.iter_records():
        if rec.tokens is None or rec.blocked is not None or (rec_ids and rec.id not in rec_ids):
            continue
        for sp in rec.spans:
            jp = script.span_text(rec, sp)
            en = text_for(rec, sp, jp)
            if en is None:
                continue
            out.append(tables.Row(rel, sp.rec_key, sp.idx, sp.off, sp.tag, jp, en, "", "", "draft", ""))
    return out


def _ascii(rec, sp, jp):
    plain = codec.strip_tokens(jp).strip()
    if not plain or "{" in jp:
        return None                       # keep rows with inline tokens out of the synthetic set
    return "English line %d of record %02X" % (sp.idx, rec.id)


def _masked_tokens(data):
    """(kind, idx, raw with rel16 operands blanked) -- what must match between
    the overlay stream and the byte-edit build, whose displacements differ."""
    out = []
    for t in vmops.tokenize(data):
        raw = bytearray(data[t.off:t.end])
        for o in t.ops:
            if o.kind == "rel16":
                raw[o.off - t.off:o.off - t.off + 2] = b"\0\0"
        out.append((t.kind, t.idx, bytes(raw)))
    return out


def _image(rel, ci=0):
    """``(image bytes, {id: base}, parsed script)`` for one container."""
    sc = script.parse(rel, files.read_source(rel))
    recs = [records.Record(r.id, r.data) for r in sc.containers[ci]]
    return overlay.image_bytes(recs), records.bases(recs), sc


def _key_of(image, rec_id):
    off, ln = overlay.live_index(image)[rec_id]
    return rec_id, ln, overlay.fnv1a(image[off:off + ln])


# ---------------------------------------------------------------------------
# The precondition the whole virtual layout rests on.
# ---------------------------------------------------------------------------

def test_no_inline_opcode_transfers_control_within_the_same_handle():
    """Why one memo per handle can resolve a virtual program counter.

    A virtual PC names no record on its own -- every record's tails are laid out
    from the same ``image_end`` -- so the hook resolves it through the memo,
    which is the record the fetch *before* it was in.  That is only sound while
    no opcode a span may contain moves the program counter to another record of
    the same buffer: if one did, the memo would have moved on and the tail would
    resolve against the wrong record.

    ``codec.INLINE_OPS`` is the complete list of what may appear inside a span:

    * ``0A``    the newline -- renders, does not branch;
    * ``1E10``  the page wait -- waits, does not branch;
    * ``01``-``08``  the eight pool calls.

    A pool call switches to the pool file's **own buffer** and returns; measured
    in ``traces/2026-09-10-run2.bin``, the caller's index entry is unchanged
    across one (``m/MS00DD`` r0D stays ``(0x05D8, 12)`` while the pool's r05 is
    ``(0x0486, 31)``), which a buffer the pool had been loaded into could not
    manage.  So the pool gets its own memo slot and the caller's survives.

    Nothing else is allowed in.  If this list ever grows an opcode that jumps
    inside the same handle, the virtual layout needs a per-handle tail stack and
    ``docs/PLAN-content-addressing.md`` section 2 has to be reopened.
    """
    assert codec.INLINE_OPS == frozenset({codec.NEWLINE_OP, codec.WAIT_OP}) | codec.POOL_OPS
    assert codec.NEWLINE_OP == 0x00A and codec.WAIT_OP == 0x210
    assert codec.POOL_OPS == frozenset(range(0x01, 0x09))
    # the flow opcodes, stated so that adding one to INLINE_OPS fails here
    flow = frozenset({0x0C, 0x0D}) | frozenset(range(0x10, 0x19))
    assert not (codec.INLINE_OPS & flow), sorted(codec.INLINE_OPS & flow)


def test_max_image_end_still_bounds_every_buffer_one_of_our_records_can_be_in():
    """The per-record tail budget is ``0x10000 - MAX_IMAGE_END``, so the
    constant has to be an over-estimate of every image that can hold a record we
    translate: every container of every ``m/`` file, and every image the
    ``et/ET0007`` merges build.  Re-measured here rather than trusted."""
    from giten import container

    def lens(rel, ci):
        raw = files.read_source(rel, paths.ORIGINAL_DDSWIN)
        cs, _ = container.split(raw)
        if ci >= len(cs):
            return None
        out = {}
        for r in records.parse_body(cs[ci].body).records:
            out.setdefault(r.id, len(r.data))
        return out

    def end(ls):
        return 0x400 + sum(ls.get(i, records.ABSENT_LEN) for i in range(256))

    worst, where = 0, ""
    d = os.path.join(paths.ORIGINAL_DDSWIN, "m")
    for name in sorted(os.listdir(d)):
        if not name.endswith(".BIN"):
            continue
        rel = "m/%s" % name
        raw = files.read_source(rel, paths.ORIGINAL_DDSWIN)
        cs, _ = container.split(raw)
        for ci in range(len(cs)):
            ls = lens(rel, ci)
            if ls and end(ls) > worst:
                worst, where = end(ls), "%s c%d" % (rel, ci)

    raw = files.read_source("et/ET0007.BIN", paths.ORIGINAL_DDSWIN)
    n = int.from_bytes(raw[:2], "little")
    for i in range(n // 3):
        t0, t1, t2 = raw[2 + i * 3:5 + i * 3]
        rels = ["m/MS6000.BIN"]
        for fam, t in ((0x6000, t0), (0x6000, t1), (0x6100, t2)):
            if t != 0xFF:
                rels.append("m/MS%04X.BIN" % (fam + t))
        for ci in range(16):
            merged = {}
            for rel in rels:
                ls = lens(rel, ci)
                if ls:
                    merged.update(ls)
            if merged and end(merged) > worst:
                worst, where = end(merged), "merge row %d c%d" % (i, ci)

    assert worst <= overlay.MAX_IMAGE_END, (
        "%s ends at 0x%04X, past MAX_IMAGE_END 0x%04X: a record's tail could "
        "run off the top of the u16 PC there" % (where, worst, overlay.MAX_IMAGE_END))
    assert overlay.MAX_TAIL_TOTAL == overlay.PC_LIMIT - overlay.MAX_IMAGE_END


def test_engine_index_follows_the_verified_layout():
    sc = script.parse(REL, files.read_source(REL))
    recs = [records.Record(r.id, r.data) for r in sc.containers[0]]
    idx = overlay.engine_index(recs)
    assert len(idx) == 0x400
    base = records.bases(recs)
    off0, len0 = int.from_bytes(idx[0:2], "little"), int.from_bytes(idx[2:4], "little")
    assert (off0, len0) == (0x400, len(recs[0].data)) and base[0] == 0x400
    assert overlay.image_end(recs) == 0x400 + sum(len(r.data) for r in recs) + (256 - len(recs))
    # the hook's script-buffer guard: entry 0 always sits at 0x400
    for rel in ("m/MS6000.BIN", "m/MS610B.BIN"):
        mc = script.parse(rel, files.read_source(rel))
        for c in mc.containers:
            i = overlay.engine_index([records.Record(r.id, r.data) for r in c])
            assert i[:2] == bytes([0x00, 0x04])


def test_overlay_dat_round_trips():
    sc = script.parse(REL, files.read_source(REL))
    entries, findings = overlay.plan(_rows(REL, sc, _ascii))
    assert entries and not findings, findings[:3]
    back = overlay.parse(overlay.build(entries))
    want = sorted(entries, key=lambda e: e.key)
    assert [e.key for e in back] == [e.key for e in want]
    assert [[(s.rec_off, s.jp_len, s.served, s.virt_off, s.data) for s in e.spans]
            for e in back] == \
           [[(s.rec_off, s.jp_len, s.served, s.virt_off, s.data) for s in e.spans]
            for e in want]
    # the record table is sorted, because the hook binary-searches it
    assert [e.key for e in back] == sorted(e.key for e in back)
    for e in back:
        assert [s.rec_off for s in e.spans] == sorted(s.rec_off for s in e.spans)
        # spans do not overlap, and virt_off is non-decreasing so the virtual
        # side is binary-searchable too
        for a, b in zip(e.spans, e.spans[1:]):
            assert a.rec_off + a.served <= b.rec_off
            assert a.virt_off + a.tail == b.virt_off
        assert e.tail_total == sum(s.tail for s in e.spans)
        assert e.tail_total <= overlay.MAX_TAIL_TOTAL
    tails = [s for e in back for s in e.spans if s.tail]
    assert tails
    assert sum(s.tail for s in tails) < sum(len(s.data) for e in back for s in e.spans)


def test_model_walk_equals_the_byte_edit_build_modulo_displacements():
    """Feeding the ORIGINAL image through the model must produce, record by
    record, the same tokens the relocating builder writes -- the two ways of
    applying one translation agree on everything but branch displacements."""
    sc = script.parse(REL, files.read_source(REL))
    rows = _rows(REL, sc, _ascii)
    entries, _ = overlay.plan(rows)
    recs = [records.Record(r.id, r.data) for r in sc.containers[0]]
    base = records.bases(recs)
    image = overlay.image_bytes(recs)
    edits = {(0, int(r.rec.split(":")[1], 16), r.idx): r.en for r in rows}
    built, rep = script.build(sc, edits)
    assert not rep.errors, rep.errors[:3]
    sc2 = script.parse(REL, built)
    checked = 0
    for rec in sc.containers[0]:
        model = overlay.Model(entries, image)
        stream = model.walk(base[rec.id], base[rec.id] + len(rec.data))
        rec2 = next(r for r in sc2.containers[0] if r.id == rec.id)
        assert _masked_tokens(stream) == _masked_tokens(rec2.data), "record %02X" % rec.id
        checked += 1
    assert checked > 5 and sum(len(e.spans) for e in entries) > 50


def test_short_english_is_served_in_place_and_costs_no_virtual_space():
    sc = script.parse(REL, files.read_source(REL))
    rows = _rows(REL, sc, lambda rec, sp, jp: "ok" if "{" not in jp and sp.end - sp.off >= 2 else None)
    entries, findings = overlay.plan(rows)
    assert not findings and entries
    assert not [s for e in entries for s in e.spans if s.tail]
    assert sum(len(e.spans) for e in entries) > 100
    image, base, _ = _image(REL)
    m = overlay.Model(entries, image)
    e = overlay.find_entry(sorted(entries, key=lambda x: x.key), *_key_of(image, 0))
    s = e.spans[0]
    start = base[0] + s.rec_off
    b0, pc = m.fetch(start)
    b1, pc = m.fetch(pc)
    assert (b0, b1, pc) == (ord("o"), ord("k"), start + s.jp_len)


def test_a_longer_line_runs_in_place_then_through_its_virtual_tail():
    sc = script.parse(REL, files.read_source(REL))
    rows = _rows(REL, sc, lambda rec, sp, jp: "abcdefghij" if "{" not in jp and sp.end - sp.off == 4 else None)
    entries, findings = overlay.plan(rows)
    assert not findings and entries
    image, base, _ = _image(REL)
    e, s = next((e, s) for e in entries for s in e.spans if s.tail)
    assert (s.served, s.tail) == (4, 6)
    m = overlay.Model(entries, image)
    start = base[e.rec_id] + s.rec_off
    virt = overlay.live_end(image) + s.virt_off
    seen, pc = [], start
    for _ in range(10):
        b, pc = m.fetch(pc)
        seen.append(b)
        if len(seen) == 4:
            assert pc == virt                                 # head done: into the tail
    assert bytes(seen) == b"abcdefghij" and pc == start + s.jp_len


def test_virtual_space_is_bounded_per_record():
    rel = "m/MS006A.BIN"
    sc = script.parse(rel, files.read_source(rel))
    rows = _rows(rel, sc, lambda rec, sp, jp: "x" * 12000 if "{" not in jp else None)
    entries, findings = overlay.plan(rows)
    assert any("overlay-space" in msg for _, msg in findings)
    assert all(e.tail_total <= overlay.MAX_TAIL_TOTAL for e in entries)


def test_two_files_that_hold_one_record_must_agree_about_its_english():
    """The one residual of content addressing, and the gate that stops it.

    v6 keys on the Japanese bytes, so two files carrying a byte-identical record
    are one key and get one translation.  If the tables disagree, one of the two
    files would silently be served the other's line -- so the disagreement is a
    finding and :func:`overlay.build` refuses the table while it stands.
    """
    rel_a, rel_b = "m/MS0006.BIN", "m/MS0012.BIN"
    a = script.parse(rel_a, files.read_source(rel_a))
    b = script.parse(rel_b, files.read_source(rel_b))
    ra = next(r for r in a.containers[0] if r.id == 0)
    rb = next(r for r in b.containers[0] if r.id == 0)
    assert ra.data == rb.data, "these two files no longer share record 00"

    def row(rel, rec, en):
        sp = rec.spans[0]
        return tables.Row(rel, sp.rec_key, sp.idx, sp.off, sp.tag,
                          script.span_text(rec, sp), en, "", "", "draft", "")

    agree = [row(rel_a, ra, "Nobody here."), row(rel_b, rb, "Nobody here.")]
    entries, findings = overlay.plan(agree)
    assert not [f for f in findings if "overlay-conflict" in f[1]], findings[:2]
    assert not overlay.conflicts(entries)
    shared = [s for e in entries for s in e.spans if len(s.sources) > 1]
    assert shared, "the two rows did not land on one key"
    overlay.build(entries)                      # accepted

    clash = [row(rel_a, ra, "Nobody here."), row(rel_b, rb, "Nothing here.")]
    entries, findings = overlay.plan(clash)
    msgs = [m for _w, m in findings if "overlay-conflict" in m]
    assert len(msgs) == 1, findings
    for wanted in (rel_a, rel_b, "Nobody here.", "Nothing here."):
        assert wanted in msgs[0], msgs[0]
    try:
        overlay.build(entries)
    except ValueError as exc:
        assert "unify_duplicates" in str(exc)
    else:
        raise AssertionError("build accepted a table with an overlay-conflict")


def _two_records_that_share_a_span():
    """Two records with one id, one length, one opening span -- different bytes.

    This is the shape the key has to separate.  Built rather than found, because
    what is being tested is the *rule*, and a synthetic pair states it without
    depending on which two files happen to look alike this month.
    """
    span = b"Aa Bb Cc Dd Ee Ff"                     # the bytes both records hold
    a, b = span + b"\x11\x22\x33\x44", span + b"\x55\x66\x77\x88"
    assert len(a) == len(b) and a[:len(span)] == b[:len(span)] and a != b
    ea = overlay.RecEntry(7, len(a), overlay.fnv1a(a),
                          [overlay.SpanEntry(0, len(span), b"first file", served=10,
                                             sources=[("m/MS0001.BIN", 0, 7, 0)])])
    eb = overlay.RecEntry(7, len(b), overlay.fnv1a(b),
                          [overlay.SpanEntry(0, len(span), b"other file", served=10,
                                             sources=[("m/MS0002.BIN", 0, 7, 0)])])
    table = sorted([ea, eb], key=lambda e: e.key)
    return table, a, b, len(span)


def test_the_key_is_the_whole_record_and_not_one_span():
    """Hashing the span would make these two records one key.

    Two files can share a line and differ in what follows it.  If the key were
    the span's Japanese, they would collide, and the *other* spans of one would
    be served into the other -- English at addresses that hold different bytes.
    So the key is the whole record, and this is what says so.
    """
    table, a, b, _n = _two_records_that_share_a_span()
    assert table[0].key != table[1].key
    ia = overlay.image_bytes([records.Record(7, a)])
    ib = overlay.image_bytes([records.Record(7, b)])
    base = overlay.live_index(ia)[7][0]
    assert overlay.live_index(ib)[7][0] == base
    assert overlay.Model(table, ia).walk(base, base + len(a)) == b"first file" + a[17:]
    assert overlay.Model(table, ib).walk(base, base + len(b)) == b"other file" + b[17:]


# ---------------------------------------------------------------------------
# The C hook, built natively, against the model.
# ---------------------------------------------------------------------------

def test_c_hook_serves_the_same_bytes_as_the_model():
    """The exact hook.c that goes into the exe, built natively, walked over an
    original image with a real overlay.dat, byte for byte against the model."""
    tmp = tempfile.mkdtemp(prefix="giten-harness-")
    try:
        exe = harness.build(tmp, "the C hook")
        if exe is None:
            return
        sc = script.parse(REL, files.read_source(REL))
        entries, _ = overlay.plan(_rows(REL, sc, _ascii))
        with open(os.path.join(tmp, "overlay.dat"), "wb") as fh:
            fh.write(overlay.build(entries))
        recs = [records.Record(r.id, r.data) for r in sc.containers[0]]
        img = overlay.image_bytes(recs)
        imgp = os.path.join(tmp, "img.bin")
        with open(imgp, "wb") as fh:
            fh.write(img)
        base = records.bases(recs)

        for rec in sc.containers[0]:
            start, stop = base[rec.id], base[rec.id] + len(rec.data)
            got, pc = harness.one(exe, tmp, imgp, 3, start, stop)
            assert got == overlay.Model(entries, img).walk(start, stop), "record %02X" % rec.id
            assert pc == stop

        # A record whose CONTENT we do not hold is not served -- which is the
        # whole rule, so it has to be shown rejecting.  One byte of a record's
        # data is flipped: its length and offset are untouched, so the buffer
        # still looks exactly like the one we planned against and only the hash
        # differs.  (v5 hashed the record INDEX, so this very edit was invisible
        # to it.)
        off, ln = overlay.live_index(img)[2]
        unknown = bytearray(img)
        unknown[off + ln // 2] ^= 0xFF
        up = os.path.join(tmp, "unknown.bin")
        with open(up, "wb") as fh:
            fh.write(unknown)
        got, _pc = harness.one(exe, tmp, up, 3, off, off + 8)
        assert got == bytes(unknown[off:off + 8]), "a changed record must not be served"

        # ...and a virtual pc in a buffer holding no record of ours must NOT
        # reach ORIG_FETCH: that address only exists because this overlay made
        # it, and reading it walks off the buffer.  0xFF instead, pc still moves.
        end = overlay.live_end(img)
        got, pc = harness.one(exe, tmp, up, 3, end, end + 4)
        assert got == bytes([0xFF]) * 4, got
        assert pc == end + 4

        # pace(): 60 ticks a second whether the clock is fine (1 ms) or coarse
        # (Windows' 15.6 ms default), and no burst of catch-up ticks after a stall
        for g in (1, 16):
            r = harness.pace(exe, tmp, g, 10000)
            assert abs(int(r["ticks"]) - 600) <= 2, (g, r)
        r = harness.pace(exe, tmp, 1, 10000, 5000, 2000)
        assert abs(int(r["ticks"]) - 480) <= 3, r          # 8 s of running time
        assert int(r["after_stall"]) <= 3, r               # ~2.4 ticks fit in 40 ms; no burst
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_c_hook_stops_serving_when_the_buffer_is_swapped_under_the_handle():
    """The defect v6 removes, driven through one process.

    The engine loads every shop, terminal and bar on a map into the same handle
    under the same pseudo file id, so the hook's ``(handle, fid)`` binding went
    stale and the weapon shop's line came out of a terminal.  Measured from the
    2026-09-10 session: ``m/MS0101`` record 2 is 12 bytes at 0x41C, the next
    script's record 2 is 9 bytes at 0x423, and both were served
    *"Hurry up and choose."*

    Here the buffer is overwritten **in place** -- same base pointer, the memo's
    only other check -- so the index entry is the sole thing that can invalidate
    it.  The reloaded buffer must be served exactly what the model says about
    *it*, and in particular must not carry a byte of the shop's English.
    """
    tmp = tempfile.mkdtemp(prefix="giten-swap-")
    try:
        exe = harness.build(tmp, "the buffer-swap path")
        if exe is None:
            return
        draft = os.path.join(paths.BUILD_DIR, "tables_draft")
        if not os.path.isdir(draft):
            return                              # tree not generated in this checkout
        rels = ("m/MS0101.BIN", "m/MS00A0.BIN")
        rows = []
        for rel in rels:
            p = os.path.join(draft, *rel.split("/")) + ".tsv"
            if not os.path.exists(p):
                return
            rows += tables.read(p)
        entries, _ = overlay.plan(rows)
        with open(os.path.join(tmp, "overlay.dat"), "wb") as fh:
            fh.write(overlay.build(entries))

        imgs, files_ = {}, {}
        for rel in rels:
            img, _base, _sc = _image(rel)
            imgs[rel] = img
            files_[rel] = os.path.join(tmp, rel.replace("/", "_"))
            with open(files_[rel], "wb") as fh:
                fh.write(img)

        shop, later = rels
        si = overlay.live_index(imgs[shop])[2]
        li = overlay.live_index(imgs[later])[2]
        assert (si[0], si[1]) == (0x041C, 12), si    # the trace's own numbers
        assert (li[0], li[1]) == (0x0423, 9), li

        got = harness.walks(exe, tmp, [
            "load 3 %s" % harness.quoted(files_[shop]),
            "walk 3 %d %d" % (si[0], si[0] + si[1]),
            "reload 3 %s" % harness.quoted(files_[later]),
            "walk 3 %d %d" % (li[0], li[0] + li[1]),
        ])
        want_shop = overlay.Model(entries, imgs[shop]).walk(si[0], si[0] + si[1])
        want_later = overlay.Model(entries, imgs[later]).walk(li[0], li[0] + li[1])
        assert b"Hurry up" in want_shop, want_shop
        assert got[0][0] == want_shop, (got[0][0], want_shop)
        assert got[1][0] == want_later, (got[1][0], want_later)
        assert b"Hurry up" not in got[1][0], got[1][0]

        # ...and the same handle, reloaded a third time with a demon-merge
        # buffer: every record of it, byte for byte.
        from tests.test_merged_overlay import ROW17, merged_image
        merged = merged_image(ROW17)
        mp = os.path.join(tmp, "merged.bin")
        with open(mp, "wb") as fh:
            fh.write(merged)
        draft_rows = [r for p in tables.iter_tables(draft) for r in tables.read(p)]
        all_entries, _ = overlay.plan(draft_rows)
        with open(os.path.join(tmp, "overlay.dat"), "wb") as fh:
            fh.write(overlay.build(all_entries))
        idx = overlay.live_index(merged)
        live = [r for r in range(256) if idx[r][1] > 1]
        lines = ["load 3 %s" % harness.quoted(files_[shop]),
                 "walk 3 %d %d" % (si[0], si[0] + si[1]),
                 "reload 3 %s" % harness.quoted(mp)]
        for r in live:
            lines.append("walk 3 %d %d" % (idx[r][0], idx[r][0] + idx[r][1]))
        got = harness.walks(exe, tmp, lines)
        for n, r in enumerate(live, start=1):
            want = overlay.Model(all_entries, merged).walk(idx[r][0], idx[r][0] + idx[r][1])
            assert got[n][0] == want, "record %02X after the reload" % r
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_record_swapped_for_one_of_the_same_shape_is_not_served_the_old_english():
    """The memo's hardest case, in the C.

    A record id plus an offset and a length is not content.  Measured over the
    corpus, 92 ``(id, offset, length)`` slots hold more than one record -- 257 in
    all, 80 of the slots holding something we translate -- and ``rec 02`` at
    0x423 with length 9 is seven different records, which is the third wrong
    line in the session that prompted v6.  So a buffer reloaded in place can
    present a *different* record at the same id, offset and length, and every
    check except one passes: the program counter the hook last handed back.

    Two records here differ only after their shared opening span, which is the
    worst case -- the hash must cover the whole record and the memo must not
    survive the swap.
    """
    tmp = tempfile.mkdtemp(prefix="giten-reshape-")
    try:
        exe = harness.build(tmp, "the same-shape reload path")
        if exe is None:
            return
        table, a, b, _n = _two_records_that_share_a_span()
        with open(os.path.join(tmp, "overlay.dat"), "wb") as fh:
            fh.write(overlay.build(table))
        paths_ = {}
        for name, data in (("a.bin", a), ("b.bin", b)):
            paths_[name] = os.path.join(tmp, name)
            with open(paths_[name], "wb") as fh:
                fh.write(overlay.image_bytes([records.Record(7, data)]))
        ia = overlay.image_bytes([records.Record(7, a)])
        ib = overlay.image_bytes([records.Record(7, b)])
        base = overlay.live_index(ia)[7][0]
        assert overlay.live_index(ia)[7] == overlay.live_index(ib)[7], (
            "the two records no longer occupy the same slot; the test is vacuous")

        got = harness.walks(exe, tmp, [
            "load 3 %s" % harness.quoted(paths_["a.bin"]),
            "walk 3 %d %d" % (base, base + len(a)),
            "reload 3 %s" % harness.quoted(paths_["b.bin"]),
            "walk 3 %d %d" % (base, base + len(b)),
        ])
        assert got[0][0] == overlay.Model(table, ia).walk(base, base + len(a))
        assert got[1][0] == overlay.Model(table, ib).walk(base, base + len(b))
        assert got[0][0].startswith(b"first file")
        assert got[1][0].startswith(b"other file"), got[1][0]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _reshaped_pair():
    """Two buffers whose record 7 starts at the same address with a different
    length, each with a translated span at the same offset inside it."""
    a = b"AAAAA" + b"0123456789" + b"aaaaa"             # 20 bytes
    b = b"BBBBB" + b"0123456789" + b"bbbbbbbbb"         # 24 bytes
    ea = overlay.RecEntry(7, len(a), overlay.fnv1a(a),
                          [overlay.SpanEntry(5, 10, b"AAAENGLISH", served=10,
                                             sources=[("m/MS0001.BIN", 0, 7, 0)])])
    eb = overlay.RecEntry(7, len(b), overlay.fnv1a(b),
                          [overlay.SpanEntry(5, 10, b"BBBENGLISH", served=10,
                                             sources=[("m/MS0002.BIN", 0, 7, 0)])])
    lead = records.Record(0, b"\x01\x02\x03")
    ia = overlay.image_bytes([lead, records.Record(7, a)])
    ib = overlay.image_bytes([lead, records.Record(7, b)])
    return sorted([ea, eb], key=lambda e: e.key), ia, ib


def test_a_reloaded_record_of_a_different_length_is_re_hashed():
    """The memo's index check, on its own.

    The program-counter check cannot catch this one: the walk *is* continuous --
    the buffer changed between two fetches and the engine came back to the
    address the hook handed out.  What says the memo is stale is the buffer's own
    index entry: record 7 is 20 bytes here and 24 there.
    """
    tmp = tempfile.mkdtemp(prefix="giten-reshape2-")
    try:
        exe = harness.build(tmp, "the memo's index check")
        if exe is None:
            return
        table, ia, ib = _reshaped_pair()
        with open(os.path.join(tmp, "overlay.dat"), "wb") as fh:
            fh.write(overlay.build(table))
        ps = {}
        for name, img in (("a.bin", ia), ("b.bin", ib)):
            ps[name] = os.path.join(tmp, name)
            with open(ps[name], "wb") as fh:
                fh.write(img)
        base = overlay.live_index(ia)[7][0]
        assert overlay.live_index(ib)[7][0] == base
        assert overlay.live_index(ia)[7][1] != overlay.live_index(ib)[7][1]

        got = harness.walks(exe, tmp, [
            "load 3 %s" % harness.quoted(ps["a.bin"]),
            "walk 3 %d %d" % (base, base + 5),       # into record 7, memo set
            "reload 3 %s" % harness.quoted(ps["b.bin"]),
            "walk 3 %d %d" % (base + 5, base + 15),  # resumes at the very same pc
        ])
        model = overlay.Model(table, ia)
        assert got[0][0] == model.walk(base, base + 5) == b"AAAAA"
        model = overlay.Model(table, ib)
        assert got[1][0] == model.walk(base + 5, base + 15)
        assert got[1][0] == b"BBBENGLISH", got[1][0]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_memos_survive_a_pool_call_into_another_handle():
    """Interleaved handles, which is what a pool call really is.

    Our English contains pool calls (``{03:0B}`` and friends), and the engine
    answers one by switching to the pool file's own buffer and coming back.  The
    memo is per handle for exactly that reason -- and the return address is
    often a **virtual** PC, which only resolves while this handle's memo still
    names the record whose tail it is.  So: walk into a span until the PC goes
    virtual, run a pool record on another handle, then resume.  The two halves
    must join up into the same bytes an uninterrupted walk gives.
    """
    tmp = tempfile.mkdtemp(prefix="giten-pool-")
    try:
        exe = harness.build(tmp, "the interleaved-handle path")
        if exe is None:
            return
        draft = os.path.join(paths.BUILD_DIR, "tables_draft")
        p = os.path.join(draft, "m", "MS0017.BIN.tsv")
        if not os.path.exists(p):
            return
        entries, _ = overlay.plan(tables.read(p))
        with open(os.path.join(tmp, "overlay.dat"), "wb") as fh:
            fh.write(overlay.build(entries))
        img, base, _sc = _image(REL)
        pimg, _pbase, _psc = _image(POOL)
        ip = os.path.join(tmp, "ms0017.bin")
        pp = os.path.join(tmp, "ms7f03.bin")
        with open(ip, "wb") as fh:
            fh.write(img)
        with open(pp, "wb") as fh:
            fh.write(pimg)

        end = overlay.live_end(img)
        table = sorted(entries, key=lambda e: e.key)
        pick = None
        for rec_id in range(256):
            off, ln = overlay.live_index(img)[rec_id]
            if ln <= 1:
                continue
            e = overlay.find_entry(table, *_key_of(img, rec_id))
            if e is None:
                continue
            for s in e.spans:
                # a span that runs out of room in place AND carries a pool call:
                # the case the interleave is really about
                if s.tail and any(1 <= b <= 8 for b in s.data):
                    pick = (off + s.rec_off, end + s.virt_off, off + s.rec_off + s.jp_len)
                    break
            if pick:
                break
        assert pick, "no span in m/MS0017 has both a tail and a pool call"
        start, virt, stop = pick

        pidx = overlay.live_index(pimg)
        prec = next(r for r in range(256) if pidx[r][1] > 1)
        pstart, pstop = pidx[prec][0], pidx[prec][0] + pidx[prec][1]

        got = harness.walks(exe, tmp, [
            "load 3 %s" % harness.quoted(ip),
            "load 5 %s" % harness.quoted(pp),
            "walk 3 %d %d" % (start, virt),      # in place, up to the tail
            "walk 5 %d %d" % (pstart, pstop),    # the pool file, on its own handle
            "walk 3 %d %d" % (virt, stop),       # back into the virtual tail
            "walk 5 %d %d" % (pstart, pstop),    # and the pool memo still works
        ])
        model = overlay.Model(entries, img)
        whole = model.walk(start, stop)
        assert got[0][0] + got[2][0] == whole, (got[0][0], got[2][0], whole)
        assert got[2][0], "nothing came out of the virtual tail"
        assert got[1][0] == got[3][0] == pimg[pstart:pstop]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# The rule that was missing: the overlay must never answer an address a branch
# jumps to.
#
# A rel16's target is a byte in the ORIGINAL file -- almost always the trailing
# `1E 10` page wait of the very line being translated, which is how a script
# says "skip the words, go straight to the page break".  The byte builder
# refuses or re-anchors those edits.  The overlay inherited neither: it served
# any address inside a span, so the jump landed on a letter of English and the
# interpreter ran prose as opcodes.  278 spans shipped that way, across 75
# files, and `docs/limits.md` recorded it as a saving ("the 84 branched-into
# spans cost the shipped patch nothing").
#
# The fix costs no English: the bytes the cap displaces move into the virtual
# tail, so a sequential read still shows the whole line.  Only the jumped-into
# path changes, and it changes to what the documentation always claimed it did
# -- the original Japanese from the jump onward.
# ---------------------------------------------------------------------------

def test_the_overlay_never_answers_an_address_a_branch_jumps_to():
    """The invariant, over every file that had the fault, from the real tables."""
    import collections
    from giten import extract_v2

    # the files that actually carry branched-into spans, so the test exercises
    # the rule rather than asserting a vacuous truth
    rels = ["m/MS0000.BIN", "m/MS000E.BIN", "m/MS0031.BIN", "m/MS005C.BIN",
            "m/MS000D.BIN", "m/MS0017.BIN"]
    text_dir = extract_v2.text_v2_dir()
    rows = [r for p in tables.iter_tables(text_dir) for r in tables.read(p)
            if r.file in rels]
    assert rows, "no table rows for the files under test"
    entries, _findings = overlay.plan(rows)
    assert entries, "nothing planned"
    table = sorted(entries, key=lambda e: e.key)

    checked = collections.Counter()
    for rel in rels:
        sc = script.parse(rel, files.read_source(rel))
        for ci, cont in enumerate(sc.containers):
            recs = [records.Record(r.id, r.data) for r in cont]
            base = records.bases(recs)
            targets = script._branch_targets(cont, base)
            seen = set()
            for rec in cont:
                if rec.id in seen:
                    continue
                seen.add(rec.id)
                e = overlay.find_entry(table, rec.id, len(rec.data),
                                       overlay.fnv1a(rec.data))
                if e is None:
                    continue
                for s in e.spans:
                    lo = base[rec.id] + s.rec_off
                    # a branch onto a span's FIRST byte is fine and always was:
                    # it gets the English from byte 0 and the line reads right.
                    # What must never happen is a branch landing part-way in.
                    inside = targets & set(range(lo + 1, lo + s.served))
                    assert not inside, (
                        "%s c%d: the overlay answers %s, address(es) a branch "
                        "jumps to" % (rel, ci, ["0x%04X" % a for a in sorted(inside)[:8]]))
                    if any(lo < t < lo + s.jp_len for t in targets):
                        checked["spans a branch jumps into"] += 1
                        if s.served < min(len(s.data), s.jp_len):
                            checked["spans the cap actually shortened"] += 1
    assert checked["spans a branch jumps into"] > 20, checked
    assert checked["spans the cap actually shortened"] > 10, checked


def _one_record_table(rec_id, data, spans):
    """A one-entry table over a synthetic record, plus the image holding it."""
    image = overlay.image_bytes([records.Record(rec_id, data)])
    ent = overlay.RecEntry(rec_id, len(data), overlay.fnv1a(data), spans)
    return [ent], image, overlay.live_index(image)[rec_id][0]


def test_capping_a_span_moves_english_to_the_tail_instead_of_dropping_it():
    """The cap must cost coverage nothing: the whole line still reads."""
    en = b"An English line long enough to overflow its Japanese."
    jp = bytes(range(0x30, 0x48))                       # 24 Japanese bytes
    # a branch aimed 4 bytes from the end of the span (its page wait)
    s = overlay.SpanEntry(0, len(jp), en, served=0x14, virt_off=0,
                          sources=[("m/MS0000.BIN", 0, 5, 0)])
    table, image, base = _one_record_table(5, jp, [s])
    assert s.tail == len(en) - 0x14
    model = overlay.Model(table, image)

    # the branch target reads the ORIGINAL byte, not our English
    assert model.fetch(base + 0x14)[0] == image[base + 0x14]
    # and a sequential walk from the span start still sees every English byte
    assert overlay.Model(table, image).walk(base, base + len(jp)) == en


def test_the_cap_survives_a_round_trip_through_overlay_dat():
    """`served` is stored, so a parsed overlay serves what the planner meant."""
    en = b"An English line long enough to overflow its Japanese."
    jp = bytes(range(0x30, 0x48))
    s = overlay.SpanEntry(0, len(jp), en, served=0x14, virt_off=0,
                          sources=[("m/MS0000.BIN", 0, 5, 0)])
    ent = overlay.RecEntry(5, len(jp), overlay.fnv1a(jp), [s])
    back = overlay.parse(overlay.build([ent]))[0]
    assert back.key == ent.key
    assert len(back.spans) == 1
    assert back.spans[0].served == 0x14
    assert back.spans[0].tail == s.tail
    assert back.spans[0].data == en


def test_every_span_the_overlay_serves_starts_where_a_token_starts():
    """A span start that is not a token boundary is an address the engine only
    reaches *inside* another token, so English there would overwrite that
    token's operands.

    No span in the corpus does this, and the two files below were the ones a
    first measurement wrongly accused -- it attributed spans to records by
    address range, which double-counts containers carrying duplicate record ids.
    Kept as the regression test for a property the whole overlay rests on, on
    the files most likely to break it (16 containers each, duplicate ids).
    """
    from giten import extract_v2
    rels = ["m/MS6012.BIN", "m/MS610B.BIN"]
    rows = [r for p in tables.iter_tables(extract_v2.text_v2_dir())
            for r in tables.read(p) if r.file in rels]
    if not rows:
        return                                  # nothing written for these yet
    entries, _findings = overlay.plan(rows)
    table = sorted(entries, key=lambda e: e.key)
    checked = 0
    for rel in rels:
        sc = script.parse(rel, files.read_source(rel))
        for cont in sc.containers:
            seen = set()
            for rec in cont:
                if rec.id in seen:
                    continue
                seen.add(rec.id)
                e = overlay.find_entry(table, rec.id, len(rec.data),
                                       overlay.fnv1a(rec.data))
                if e is None:
                    continue
                toks = rec.tokens if rec.tokens is not None else rec.span_tokens
                starts = {t.off for t in (toks or [])}
                for s in e.spans:
                    assert s.rec_off in starts, (
                        "%s record %02X: span at +0x%04X starts inside a token"
                        % (rel, rec.id, s.rec_off))
                    checked += 1
    assert checked


def test_no_span_ends_on_a_dangling_escape_prefix():
    """English may not end on 1D/1E/1F.

    The engine reads an escape prefix and then takes the NEXT byte as the
    opcode's second half -- and that byte comes from the original stream at the
    span's end.  So our text and the game's bytes combine into an opcode that
    is in neither.  It shipped: `m/MS6000` 12:D2[3] ended `... 01 00 1e`, the
    byte at the span's end is `1F`, and together they made `1E1F` -- which also
    swallowed the `1F` that was itself a prefix, putting every token after it
    one byte out.

    Checked over the whole draft tree, because that is what ships; the two rows
    that trip it are both promoted references, not anything a human wrote.
    """
    from giten import extract_v2

    draft = os.path.join(paths.BUILD_DIR, "tables_draft")
    text_dir = draft if os.path.isdir(draft) else extract_v2.text_v2_dir()
    rows = [r for p in tables.iter_tables(text_dir) for r in tables.read(p)]
    assert rows
    entries, findings = overlay.plan(rows)
    bad = [(e.rec_id, s.rec_off) for e in entries for s in e.spans
           if s.data and s.data[-1] in vmops.ESCAPE]
    assert not bad, bad[:5]
    # and the rule has to be doing work, not passing because nothing trips it
    assert [f for f in findings if "escape prefix" in f[1]], \
        "no row tripped the rule -- has the source changed?"


def test_the_dead_dictionary_is_never_translated():
    """`m/MS7F05` holds one data run the interpreter walks and prints.

    `tables/` leaves it blank on purpose; only the draft promotion filled it,
    and it reached the screen as "Dictionary 5" during a battle.  The overlay
    must carry no entry for it.
    """
    draft = os.path.join(paths.BUILD_DIR, "tables_draft")
    if not os.path.isdir(draft):
        return
    rows = [r for p in tables.iter_tables(draft) for r in tables.read(p)]
    dead = [r for r in rows if r.file == "m/MS7F05.BIN" and r.en]
    assert not dead, [(r.rec, r.idx, r.en) for r in dead]
