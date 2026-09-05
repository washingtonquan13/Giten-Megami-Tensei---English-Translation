"""The runtime overlay: table format, the reference model against the byte-edit
builder, the virtual-space rule, and the C hook against the model."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import codec, files, overlay, records, script, tables, vmops  # noqa: E402
from giten.exe import tracer  # noqa: E402

REL = "m/MS0017.BIN"


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


def test_engine_index_and_fingerprint_follow_the_verified_layout():
    sc = script.parse(REL, files.read_source(REL))
    recs = [records.Record(r.id, r.data) for r in sc.containers[0]]
    idx = overlay.engine_index(recs)
    assert len(idx) == 0x400
    base = records.bases(recs)
    off0, len0 = int.from_bytes(idx[0:2], "little"), int.from_bytes(idx[2:4], "little")
    assert (off0, len0) == (0x400, len(recs[0].data)) and base[0] == 0x400
    assert overlay.image_end(recs) == 0x400 + sum(len(r.data) for r in recs) + (256 - len(recs))
    # containers of a multi-container file tell apart by fingerprint
    for rel in ("m/MS6000.BIN", "m/MS610B.BIN"):
        mc = script.parse(rel, files.read_source(rel))
        idx = [overlay.engine_index([records.Record(r.id, r.data) for r in c]) for c in mc.containers]
        assert len({overlay.fnv1a(i[:overlay.FP_BYTES]) for i in idx}) == len(set(idx))
        assert all(i[:2] == bytes([0x00, 0x04]) for i in idx)   # the hook's script-buffer guard


def test_overlay_dat_round_trips():
    sc = script.parse(REL, files.read_source(REL))
    entries, findings = overlay.plan(_rows(REL, sc, _ascii))
    assert entries and not findings, findings[:3]
    back = overlay.parse(overlay.build(entries))
    assert [(e.fid, e.fp, e.image_end) for e in back] == [(e.fid, e.fp, e.image_end) for e in entries]
    assert [[(s.start, s.end, s.virt, s.data) for s in e.spans] for e in back] == \
           [[(s.start, s.end, s.virt, s.data) for s in e.spans] for e in entries]
    e = entries[0]
    assert e.spans == sorted(e.spans, key=lambda s: s.start)
    tails = e.tails
    assert tails and tails[0].virt == e.image_end and tails[-1].vend <= overlay.PC_LIMIT
    for a, b in zip(tails, tails[1:]):
        assert a.vend == b.virt and a.end <= b.start
    assert all(s.virt == 0 for s in e.spans if not s.tail)
    assert all(s.head == min(len(s.data), s.end - s.start) for s in e.spans)
    assert sum(s.tail for s in e.spans) < sum(len(s.data) for s in e.spans)   # virtual space is only the excess


def test_model_walk_equals_the_byte_edit_build_modulo_displacements():
    """Feeding the ORIGINAL image through the model must produce, record by
    record, the same tokens the relocating builder writes -- the two ways of
    applying one translation agree on everything but branch displacements."""
    sc = script.parse(REL, files.read_source(REL))
    rows = _rows(REL, sc, _ascii)
    entries, _ = overlay.plan(rows)
    ent = entries[0]
    recs = [records.Record(r.id, r.data) for r in sc.containers[0]]
    base = records.bases(recs)
    model = overlay.Model(ent, overlay.image_bytes(recs))
    edits = {(0, int(r.rec.split(":")[1], 16), r.idx): r.en for r in rows}
    built, rep = script.build(sc, edits)
    assert not rep.errors, rep.errors[:3]
    sc2 = script.parse(REL, built)
    checked = 0
    for rec in sc.containers[0]:
        stream = model.walk(base[rec.id], base[rec.id] + len(rec.data))
        rec2 = next(r for r in sc2.containers[0] if r.id == rec.id)
        assert _masked_tokens(stream) == _masked_tokens(rec2.data), "record %02X" % rec.id
        checked += 1
    assert checked > 5 and sum(1 for _ in ent.spans) > 50


def test_short_english_is_served_in_place_and_costs_no_virtual_space():
    sc = script.parse(REL, files.read_source(REL))
    rows = _rows(REL, sc, lambda rec, sp, jp: "ok" if "{" not in jp and sp.end - sp.off >= 2 else None)
    entries, findings = overlay.plan(rows)
    assert not findings and entries and not entries[0].tails and len(entries[0].spans) > 100
    e = entries[0]
    recs = [records.Record(r.id, r.data) for r in sc.containers[0]]
    m = overlay.Model(e, overlay.image_bytes(recs))
    s = e.spans[0]
    b0, pc = m.fetch(s.start)
    b1, pc = m.fetch(pc)
    assert (b0, b1, pc) == (ord("o"), ord("k"), s.end)              # two bytes in place, then the hand-back


def test_a_longer_line_runs_in_place_then_through_its_virtual_tail():
    sc = script.parse(REL, files.read_source(REL))
    rows = _rows(REL, sc, lambda rec, sp, jp: "abcdefghij" if "{" not in jp and sp.end - sp.off == 4 else None)
    entries, findings = overlay.plan(rows)
    assert not findings and entries
    e = entries[0]
    s = next(x for x in e.spans if x.tail)
    assert (s.head, s.tail) == (4, 6)
    recs = [records.Record(r.id, r.data) for r in sc.containers[0]]
    m = overlay.Model(e, overlay.image_bytes(recs))
    seen, pc = [], s.start
    for _ in range(10):
        b, pc = m.fetch(pc)
        seen.append(b)
        if len(seen) == 4:
            assert pc == s.virt                                       # head done: into the tail
    assert bytes(seen) == b"abcdefghij" and pc == s.end


def test_virtual_space_is_bounded_per_file():
    rel = "m/MS006A.BIN"
    sc = script.parse(rel, files.read_source(rel))
    rows = _rows(rel, sc, lambda rec, sp, jp: "x" * 12000 if "{" not in jp else None)
    entries, findings = overlay.plan(rows)
    assert any("overlay-space" in msg for _, msg in findings)
    assert all(e.spans[-1].vend <= overlay.PC_LIMIT for e in entries)


def test_c_hook_serves_the_same_bytes_as_the_model():
    """The exact hook.c that goes into the exe, built natively, walked over an
    original image with a real overlay.dat, byte for byte against the model."""
    if shutil.which("gcc") is None:
        return
    here = os.path.dirname(os.path.abspath(__file__))
    tmp = tempfile.mkdtemp(prefix="giten-harness-")
    exe = os.path.join(tmp, "hook_harness.exe")
    gcc = tracer.short_path(shutil.which("gcc"))
    # no CRT: the mingw driver cannot link its own CRT from a path with spaces
    subprocess.run([gcc, "-O2", "-Wall", "-Werror", "-ffreestanding", "-fno-builtin", "-nostdlib",
                    "-o", exe, tracer.HOOK_SOURCE, os.path.join(here, "hook_harness.c"),
                    "-I", here, "-lkernel32", "-e", "_start"], check=True)
    sc = script.parse(REL, files.read_source(REL))
    entries, _ = overlay.plan(_rows(REL, sc, _ascii))
    with open(os.path.join(tmp, "overlay.dat"), "wb") as fh:
        fh.write(overlay.build(entries))
    ent = entries[0]
    recs = [records.Record(r.id, r.data) for r in sc.containers[0]]
    img = overlay.image_bytes(recs)
    with open(os.path.join(tmp, "img.bin"), "wb") as fh:
        fh.write(img)
    base = records.bases(recs)
    model = overlay.Model(ent, img)
    for rec in sc.containers[0]:
        start, stop = base[rec.id], base[rec.id] + len(rec.data)
        out = subprocess.run([exe, os.path.join(tmp, "img.bin"), str(ent.fid), "3", str(start), str(stop)],
                             cwd=tmp, capture_output=True, text=True, check=True).stdout.split()
        got = bytes.fromhex(out[0]) if not out[0].startswith("pc=") else b""
        assert got == model.walk(start, stop), "record %02X" % rec.id
        assert out[-1] == "pc=%d" % stop
    # a file the overlay does not know passes straight through
    out = subprocess.run([exe, os.path.join(tmp, "img.bin"), "0x1234", "3", str(base[2]), str(base[2] + 8)],
                         cwd=tmp, capture_output=True, text=True, check=True).stdout.split()
    assert bytes.fromhex(out[0]) == img[base[2]:base[2] + 8]
    # pace(): 60 ticks a second whether the clock is fine (1 ms) or coarse
    # (Windows' 15.6 ms default), and no burst of catch-up ticks after a stall
    def pace(granularity, total, stall_at=0, stall=0):
        out = subprocess.run([exe, "pace", str(granularity), str(total), str(stall_at), str(stall)],
                             cwd=tmp, capture_output=True, text=True, check=True).stdout.split()
        return dict(kv.split("=") for kv in out)
    for g in (1, 16):
        r = pace(g, 10000)
        assert abs(int(r["ticks"]) - 600) <= 2, (g, r)
    r = pace(1, 10000, 5000, 2000)
    assert abs(int(r["ticks"]) - 480) <= 3, r                # 8 s of running time
    assert int(r["after_stall"]) <= 3, r                     # ~2.4 ticks fit in 40 ms; no burst
    shutil.rmtree(tmp, ignore_errors=True)
