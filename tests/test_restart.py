"""Tests for the restart: the original's manifest, the exe patches, the tracer,
the trace decoder, and the two new checker rules."""
from __future__ import annotations

import hashlib
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import check_v2, codec, files, findings, paths, records, script, tables, vmops  # noqa: E402
from giten.exe import patch, tracer  # noqa: E402
from giten.exe.pe import PE  # noqa: E402
from giten.trace import core as trace  # noqa: E402


# --------------------------------------------------------------------------
# the original is what we say it is
# --------------------------------------------------------------------------
def test_original_matches_its_manifest():
    """Every file under original/ddswin has the SHA-256 the manifest records."""
    root = paths.ORIGINAL_DDSWIN
    manifest = os.path.join(os.path.dirname(root), "MANIFEST.sha256")
    want = {}
    for ln in open(manifest, encoding="utf-8"):
        h, rel = ln.rstrip("\n").split("  ", 1)
        want[rel] = h
    assert len(want) > 2000
    bad = []
    for rel, h in want.items():
        p = os.path.join(root, *rel.split("/"))
        if not os.path.exists(p) or hashlib.sha256(open(p, "rb").read()).hexdigest() != h:
            bad.append(rel)
    assert not bad, bad[:5]


def test_game_root_is_the_original_not_a_sibling_install():
    assert os.path.normcase(paths.game_root()) == os.path.normcase(paths.ORIGINAL_DDSWIN)


# --------------------------------------------------------------------------
# exe patches
# --------------------------------------------------------------------------
def test_patch_applier_asserts_old_bytes():
    org = open(patch.ORG, "rb").read()
    rel = patch.apply(org, "release")
    assert rel[0x509A9] == 0x80 and org[0x509A9] == 0x01
    assert rel[0x59DE0:0x59DE5] == bytes.fromhex("68a4030000")     # push 932
    try:
        patch.apply(rel, "release")                                  # applying twice must fail
    except ValueError:
        pass
    else:
        raise AssertionError("second application should have been refused")


def test_base_is_the_xp_patched_exe_outside_its_font_edits():
    org = open(patch.ORG, "rb").read()
    base = patch.apply(org, "base")
    xp = open(os.path.join(paths.ORIGINAL_DDSWIN, "dds.exe"), "rb").read()
    assert base[:0x69E30] == xp[:0x69E30]
    assert base[0x69E30:] == org[0x69E30:]                           # font untouched


# --------------------------------------------------------------------------
# tracer
# --------------------------------------------------------------------------
def test_cave_is_position_independent_and_small():
    blob = tracer.assemble()
    assert 100 < len(blob) < 0x400
    assert blob[:2] == b"\x55\x89"                                    # push ebp; mov ebp,esp
    i = blob.find(b"\x5e")                                            # pop esi
    assert blob[i + 1:i + 3] == b"\x81\xee"                           # sub esi, imm32
    assert struct.unpack_from("<I", blob, i + 3)[0] == i              # ... == the label's offset
    assert struct.pack("<I", tracer.EXEC_TOKEN) in blob               # mov eax, exec_token
    assert b"trace.bin\0" in blob


def _calls_go_to(d, pe, sites, va):
    for site in sites:
        off = pe.va2off(site)
        assert d[off] == 0xE8
        assert (site + 5 + struct.unpack_from("<i", d, off + 1)[0]) & 0xFFFFFFFF == va


def test_release_exe_carries_the_overlay_hook_and_dev_adds_the_tracer():
    out = tempfile.mkdtemp()
    rel = open(tracer.build_release(out), "rb").read()
    dev = open(tracer.build_dev(out), "rb").read()
    pe = PE(rel, "rel")
    sec = pe.section(".ovl")
    assert sec is not None
    va = pe.imagebase + sec["vaddr"]
    blob = tracer.compile_hook(va)
    assert rel[sec["rawptr"]:sec["rawptr"] + sec["vsize"]] == blob
    assert struct.pack("<I", tracer.FETCH) in blob                    # the passthrough call
    assert b"overlay.dat\0" in blob
    _calls_go_to(rel, pe, tracer.FETCH_SITES, va)
    # the plain locale patches are still there underneath
    assert rel[0x509A9] == 0x80 and rel[0x59DE0:0x59DE5] == bytes.fromhex("68a4030000")
    # dev = release + .trc + the three exec_token redirects, nothing else
    pe2 = PE(dev, "dev")
    sec2 = pe2.section(".trc")
    va2 = pe2.imagebase + sec2["vaddr"]
    assert dev[sec2["rawptr"]:sec2["rawptr"] + sec2["vsize"]] == tracer.assemble()
    _calls_go_to(dev, pe2, tracer.CALL_SITES, va2)
    _calls_go_to(dev, pe2, tracer.FETCH_SITES, va)
    diffs = [i for i in range(len(rel)) if rel[i] != dev[i]]
    assert set(diffs) <= {pe2.va2off(s) + k for s in tracer.CALL_SITES for k in (1, 2, 3, 4)} | set(range(0x1F0, 0x2C0)) | set(range(0xC0, 0x120))   # section headers incl. the 7th


def test_trace_decoder_maps_a_synthetic_record_back_to_its_span():
    """Fake one trace record for a real token and get the table row back."""
    rel = "m/MS0017.BIN"
    sc = script.parse(rel, files.read_source(rel))
    rec = next(r for r in sc.containers[0] if r.id == 0 and r.spans)
    sp = rec.spans[1]                                                 # "Open terminal" in v0.05; a 1FB2 option
    tok = rec.tokens[sp.tok_lo]
    base = records.bases([records.Record(r.id, r.data) for r in sc.containers[0]])
    # exec_token is handed one character: a byte, a Shift-JIS pair packed
    # big-endian, or -- for an opcode -- just the opcode byte (the handler reads
    # its own operands).  pc is the byte after the whole token (logged on return).
    if tok.kind == "op":
        ch, pc = rec.data[tok.off], base[rec.id] + tok.end
    else:
        ch, pc = int.from_bytes(rec.data[tok.off:tok.end], "big"), base[rec.id] + tok.end
    fid = int(rel[4:8], 16)
    tmp = tempfile.mktemp(suffix=".bin")
    with open(tmp, "wb") as fh:
        fh.write(trace.RECORD.pack(fid, rec.id, pc, ch & 0xFFFF, 0, 0, 0, 0, 0))
    evs = trace.decode(tmp, paths.game_root())
    os.unlink(tmp)
    assert len(evs) == 1
    ev = evs[0]
    assert ev.rel == rel and ev.rec == rec.id
    assert ev.span == sp.idx, (ev.span, sp.idx, ev.kind)
    assert ev.ok, "self-check should pass for a record built from the real bytes"


def test_trace_normalise_collapses_text_runs():
    e = lambda k, n: trace.Event(n, 0x17, 0, 0, 0, 0, 0, 0, rel="m/MS0017.BIN", span=1, anchor=3, kind=k)
    evs = [e("TEXT", 0), e("TEXT", 1), e("1FB2", 2), e("TEXT", 3)]
    assert [x.kind for x in trace.normalise(evs)] == ["TEXT", "1FB2", "TEXT"]


# --------------------------------------------------------------------------
# checker rules
# --------------------------------------------------------------------------
def _row(jp, en, ref_en="", status="", tag="1FD3"):
    return tables.Row("m/MS0000.BIN", "0:01", 0, 0, tag, jp, en, ref_en, "ours", status, "")


def test_status_is_required_for_a_real_edit_and_not_for_a_no_op():
    rep = findings.Report()
    check_v2.check_rows(rep, [_row("あ", "hello"), _row("x", "x"), _row("い", "hi", status="draft")])
    assert [f.where for f in rep.errors if f.rule == "status"] == ["m/MS0000.BIN 0:01[0]"]


def test_en_that_copies_ref_en_needs_review():
    rep = findings.Report()
    check_v2.check_rows(rep, [_row("あ", "hello", ref_en="hello", status="draft"),
                              _row("い", "hello", ref_en="hello", status="reviewed")])
    assert len([f for f in rep.errors if f.rule == "status"]) == 1


def test_capture_regions_are_bounded():
    """A real 1B..1C region from the original, then an English that overflows it."""
    found = None
    for rel in files.iter_files(("ms",)):
        sc = script.parse(rel, files.read_source(rel))
        if not sc.ok:
            continue
        for rec in sc.iter_records():
            if rec.tokens is None:
                continue
            ons = [t for t in rec.tokens if t.kind == "op" and t.idx == check_v2.CAPTURE_ON]
            offs = [t for t in rec.tokens if t.kind == "op" and t.idx == check_v2.CAPTURE_OFF]
            if ons and offs and any(sp.off >= ons[0].off and sp.end <= offs[0].off for sp in rec.spans):
                sp = next(sp for sp in rec.spans if sp.off >= ons[0].off and sp.end <= offs[0].off)
                found = (rel, rec, sp)
                break
        if found:
            break
    assert found, "no capture region with a span in it"
    rel, rec, sp = found
    key = "%d:%02X" % (rec.ci, rec.id)
    row = tables.Row(rel, key, sp.idx, sp.off, sp.tag, script.span_text(rec, sp), "x" * 300, "", "", "draft", "")
    rep = findings.Report()
    check_v2.check_capture(rep, [row])
    assert any(f.rule == "capture" for f in rep.errors), [str(f) for f in rep.findings]
    row.en = "ok"
    rep = findings.Report()
    check_v2.check_capture(rep, [row])
    assert not [f for f in rep.errors if f.rule == "capture"]


def test_record_size_is_bounded_by_the_loaders_signed_delta():
    """The BBS record (m/MS006A r00) is the original's largest at 28,291 bytes;
    4,477 more bytes of English and the loader's signed 16-bit delta goes
    negative.  ``check`` must predict that from the tables, ``audit`` must see
    it in a built file."""
    from giten import audit
    rel = "m/MS006A.BIN"
    src = files.read_source(rel)
    sc = script.parse(rel, src)
    rec = next(r for r in sc.iter_records() if r.id == 0)
    assert len(rec.data) == 28291
    assert audit.RECORD_LIMIT == check_v2.RECORD_LIMIT == 0x7FFF
    sp = rec.spans[0]
    room = check_v2.RECORD_LIMIT - len(rec.data) + (sp.end - sp.off)
    mk = lambda n: tables.Row(rel, "0:00", sp.idx, sp.off, sp.tag, script.span_text(rec, sp),
                              "x" * n, "", "", "draft", "")
    rep = findings.Report()
    check_v2.check_record_size(rep, [mk(room)])
    assert not [f for f in rep.errors if f.rule == "record-size"]      # exactly at the limit
    rep = findings.Report()
    check_v2.check_record_size(rep, [mk(room + 1)])
    assert [f.where for f in rep.errors if f.rule == "record-size"] == ["m/MS006A.BIN 0:00"]
    # the same record, actually built one byte too long, is an audit finding:
    # splice the record's bytes by hand and re-frame the container
    from giten import container, records
    recs = [records.Record(r.id, r.data) for r in sc.containers[0]]
    fat = rec.data[:sp.off] + b"x" * (room + 1) + rec.data[sp.end:]
    recs = [records.Record(r.id, fat if r.id == 0 else r.data) for r in recs]
    built = container.join([records.serialise(recs)])
    r = audit.Report()
    audit.audit_file(rel, src, built, r)
    assert any(f.startswith("record-size") for f in r.findings), r.findings


def _room_menu_switch(sc):
    """The ``0F`` right after the room menu's ``1E 08`` in m/MS0017 r02."""
    rec = next(r for r in sc.iter_records() if r.id == 2)
    i = rec.data.find(b"\x1e\x11\x1e\x08\x0f") + 4
    return rec, next(t for t in rec.tokens if t.off == i)


def test_switch_table_tokenizes_as_cases_with_rel16_targets():
    """m/MS0017 r02's room menu: three cases -- call file 6A (the BBS), jump +5
    (the "too focused on the exam" line), jump +783 (leave the room) -- then FF.
    The old model typed 0F as five plain bytes, ate the next opcode, and never
    relocated the +783; that was the "leave loops back to the exam" bug."""
    rel = "m/MS0017.BIN"
    sc = script.parse(rel, files.read_source(rel))
    rec, tok = _room_menu_switch(sc)
    assert tok.idx == 0x0F
    assert rec.data[tok.off:tok.end].hex() == "0f00006a000101050002010f03ff"
    assert [o.kind for o in tok.ops] == ["u8", "u8", "u8", "u8",
                                          "u8", "u8", "rel16",
                                          "u8", "u8", "rel16", "u8"]
    assert [o.value for o in tok.ops if o.kind == "rel16"] == [5, 0x30F]
    assert rec.tokens[rec.tokens.index(tok) + 1].idx == 0x1BA          # 1F BA follows the FF


def test_switch_targets_are_relocated_and_audited():
    """Lengthen text between the room-menu switch and its 'leave' target.  The
    builder must relocate the rel16 (same anchor after the edit); splicing the
    same text in by hand -- what the old model effectively did -- must be an
    audit finding naming opcode 00F."""
    from giten import audit, container, records
    rel = "m/MS0017.BIN"
    raw = files.read_source(rel)
    sc = script.parse(rel, raw)
    rec, tok = _room_menu_switch(sc)
    cont = sc.containers[0]
    base = records.bases([records.Record(r.id, r.data) for r in cont])
    leave = vmops.rel16_target(base[2], tok, tok.ops[-2]) - base[2]
    anchor = sum(1 for u in rec.tokens if u.kind == "op" and u.off < leave)
    sp = next(s for s in rec.spans if tok.end <= s.off and s.end <= leave)
    longer = script.span_text(rec, sp) + " plus a much longer English sentence than the source"

    built, rep = script.build(sc, {(0, 2, sp.idx): longer})
    assert not rep.errors and rep.relocated > 0
    sc2 = script.parse(rel, built)
    rec2, tok2 = _room_menu_switch(sc2)
    base2 = records.bases([records.Record(r.id, r.data) for r in sc2.containers[0]])
    leave2 = vmops.rel16_target(base2[2], tok2, tok2.ops[-2]) - base2[2]
    assert sum(1 for u in rec2.tokens if u.kind == "op" and u.off < leave2) == anchor
    r = audit.Report()
    audit.audit_file(rel, raw, built, r)
    assert not r.findings, r.findings

    spliced = rec.data[:sp.off] + codec.encode(longer) + rec.data[sp.end:]
    recs = [records.Record(q.id, spliced if q.id == 2 else q.data) for q in cont]
    bad = container.join([records.serialise(recs)])
    r = audit.Report()
    audit.audit_file(rel, raw, bad, r)
    assert any(f.startswith("branch-moved") and "(00F)" in f for f in r.findings), r.findings


def test_switch_kind_other_than_0_or_1_refuses_to_tile():
    assert vmops.tiles(bytes.fromhex("0f 00 01 05 00 ff 00"))
    assert vmops.tiles(bytes.fromhex("0f 00 00 6a 00 ff 00"))
    assert not vmops.tiles(bytes.fromhex("0f 00 02 05 00 ff 00"))
    assert not vmops.tiles(bytes.fromhex("0f 00 01 05 00"))                 # no FF


def test_a_row_whose_jp_no_longer_matches_its_span_is_refused():
    """Span numbering belongs to the tokenizer; a row carries its ``jp`` as the
    fingerprint of the span it was written against.  Both the checker and the
    builder must refuse a row whose fingerprint does not match."""
    from giten import build_v2
    rel = "m/MS0017.BIN"
    raw = files.read_source(rel)
    sc = script.parse(rel, raw)
    rec = next(r for r in sc.iter_records() if r.id == 2 and r.spans)
    good, bad = rec.spans[3], rec.spans[4]
    mk = lambda sp, jp: tables.Row(rel, "0:02", sp.idx, sp.off, sp.tag, jp, "english", "", "", "draft", "")
    rows = [mk(good, script.span_text(rec, good)),            # fingerprint matches
            mk(bad, script.span_text(rec, good))]             # row 4 carries span 3's text
    rep = findings.Report()
    check_v2.check_stale(rep, rows)
    assert [f.where for f in rep.errors if f.rule == "stale"] == ["m/MS0017.BIN 0:02[%d]" % bad.idx]
    res = build_v2.build_file(rel, raw, rows)
    assert res.changed_spans == 1
    assert len(res.errors) == 1 and "stale row" in res.errors[0]
    # ...and the bad row really was not applied: only the good span changed
    sc2 = script.parse(rel, res.raw)
    rec2 = next(r for r in sc2.iter_records() if r.id == 2)
    assert script.span_text(rec2, rec2.spans[good.idx]) == "english"
    assert script.span_text(rec2, rec2.spans[bad.idx]) == script.span_text(rec, bad)


def test_extraction_never_fills_the_reference_columns():
    """The extractor builds rows from the game alone: ref_en/ref_src/status must be
    empty and the note must be in the note column (a positional Row() with eight
    arguments once put every note into ref_en)."""
    import tempfile
    from giten import extract_v2
    d = tempfile.mkdtemp()
    extract_v2.run("ms", None, d, True)
    rows = [r for p in tables.iter_tables(d) for r in tables.read(p)]
    assert rows
    assert not any(r.ref_en or r.ref_src or r.status for r in rows)
    assert any(r.note for r in rows)
    assert not any(r.ref_en.startswith(("reads:", "record reaches", "@")) for r in rows)
