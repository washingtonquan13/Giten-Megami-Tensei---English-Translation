"""Tests for the restart: the original's manifest, the exe patches, the tracer,
the trace decoder, and the two new checker rules."""
from __future__ import annotations

import hashlib
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import check_v2, codec, files, findings, paths, records, script, tables  # noqa: E402
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


def test_dev_exe_redirects_exactly_the_three_calls():
    out = tempfile.mkdtemp()
    p = tracer.build_dev(out)
    d = open(p, "rb").read()
    pe = PE(d, "dev")
    sec = pe.section(".trc")
    assert sec is not None
    va = pe.imagebase + sec["vaddr"]
    assert d[sec["rawptr"]:sec["rawptr"] + sec["vsize"]] == tracer.assemble()
    for site in tracer.CALL_SITES:
        off = pe.va2off(site)
        assert d[off] == 0xE8
        assert (site + 5 + struct.unpack_from("<i", d, off + 1)[0]) & 0xFFFFFFFF == va
    # nothing else moved: the release image and the dev image agree everywhere
    # except the three rel32s and the appended section
    rel = patch.apply(open(patch.ORG, "rb").read(), "release")
    diffs = [i for i in range(len(rel)) if rel[i] != d[i]]
    assert set(diffs) <= {pe.va2off(s) + k for s in tracer.CALL_SITES for k in (1, 2, 3, 4)} | set(range(0x1F0, 0x290)) | set(range(0xC0, 0x120))


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
        fh.write(trace.RECORD.pack(fid, rec.id, pc, ch & 0xFFFF, 0, 0, 0))
    evs = trace.decode(tmp, paths.game_root())
    os.unlink(tmp)
    assert len(evs) == 1
    ev = evs[0]
    assert ev.rel == rel and ev.rec == rec.id
    assert ev.span == sp.idx, (ev.span, sp.idx, ev.kind)
    assert ev.ok, "self-check should pass for a record built from the real bytes"


def test_trace_normalise_collapses_text_runs():
    e = lambda k, n: trace.Event(n, 0x17, 0, 0, 0, 0, 0, 0, "m/MS0017.BIN", 1, 3, k)
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
