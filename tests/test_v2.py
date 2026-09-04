"""Tests for the v2 (opcode-aware) pipeline.

Runnable with ``python -m tests.run`` alongside the v1 suite.  Everything reads
the game folder read-only and writes nothing outside a temporary directory.

The load-bearing ones, in order of how much else depends on them:

* the container seed rule agrees with an independent transcription of the
  engine (:mod:`giten.refdecode`) -- including for a container whose
  length, and therefore whose cipher seed, has changed;
* the identity build is byte-exact on all 844 files;
* a lengthening edit relocates every ``rel16`` so it still lands on the same
  instruction.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import (codec, container, extract_v2, files, pool,
                         records, refdecode, script, tables, vmops, width)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _script(rel):
    raw = files.read_source(rel)
    sc = script.parse(rel, raw)
    assert sc.ok, "%s: %s" % (rel, sc.error)
    return raw, sc


def branch_map(sc, ci=0):
    """``{branch identity: the instruction it lands on}``.

    A branch and its target are both named by **how many opcodes precede them in
    their record**, never by a byte offset or a raw token index.  Editing text
    changes the number of text tokens in a record, so a token index is not
    stable; the opcode sequence is exactly what must not move.  A target is
    described as ``(record id, opcodes before it, what it is)`` where "what it
    is" is the dispatch index for an opcode, ``"text"`` for a character, or
    ``"end"`` for the byte just past the record.

    Targets outside the container's runtime image are recorded as
    ``("?", absolute)`` and skipped when comparing: nothing can be said about
    where they ought to move.
    """
    recs = sc.containers[ci]
    first = {}
    for pos, r in enumerate(recs):
        first.setdefault(r.id, pos)
    base, off = {}, records.INDEX_SIZE
    for i in range(256):
        base[i] = off
        off += len(recs[first[i]].data) if i in first else records.ABSENT_LEN

    where = {}
    ordinal = {}
    for r in recs:
        if r.untiled:
            continue
        nops = 0
        for k, t in enumerate(r.tokens):
            where[base[r.id] + t.off] = (r.id, nops,
                                         t.idx if t.kind == "op" else "text")
            ordinal[(r.id, k)] = nops
            # Only structural opcodes count: a pool call, newline or page wait
            # lives inside a span and an edit may add or drop it, which would
            # shift every later ordinal without any branch having moved.
            if t.kind == "op" and t.idx not in codec.INLINE_OPS:
                nops += 1
        where[base[r.id] + len(r.data)] = (r.id, nops, "end")

    out = {}
    for r in recs:
        if r.untiled:
            continue
        for k, t in enumerate(r.tokens):
            for o in t.ops:
                if o.kind == "rel16":
                    tgt = vmops.rel16_target(base[r.id], t, o)
                    out[(r.id, ordinal[(r.id, k)])] = where.get(tgt, ("?", tgt))
    return out



def _first_editable_span(sc, want_id=None):
    for rec in sc.iter_records():
        if rec.untiled or rec.blocked or (want_id is not None and rec.id != want_id):
            continue
        for sp in rec.spans:
            txt = script.span_text(rec, sp)
            if codec.strip_tokens(txt).strip():
                return rec, sp, txt
    raise AssertionError("no editable span found")


# --------------------------------------------------------------------------
# container: the seed rule
# --------------------------------------------------------------------------
def test_seed_is_derived_from_the_header_word():
    # 0x401B20: prev = (hdr >> 8) ^ (hdr & 0xFF)
    assert container.seed_of(0x0000) == 0x00
    assert container.seed_of(0x1234) == 0x12 ^ 0x34
    assert container.seed_of(0xFFFF) == 0x00
    body = bytes(range(64))
    for hdr in (0, 1, 0x1234, 0xABCD, 0xFFFF):
        s = container.seed_of(hdr)
        assert container.unxor(container.enxor(body, s), s) == body


def test_container_chain_lands_on_eof_for_every_pipeline_file():
    """All 844 files the pipeline handles are container chains.

    ``docs/format-notes.md`` §0 reports 842 of 844 over a slightly different file
    set -- one that includes ``et/A0000`` and ``et/A0001``.  Those two are the
    only non-chains in the whole game folder, and neither is in the pipeline's
    families (``et`` means ``et/ET*``), so here the figure is 844 of 844.
    """
    bad = [rel for rel in files.all_encoded()
           if not container.is_container_chain(files.read_source(rel))]
    assert bad == [], bad

    import os
    from giten import paths
    for name in ("A0000.BIN", "A0001.BIN"):
        p = os.path.join(paths.game_root(), "et", name)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                assert not container.is_container_chain(fh.read()), name


def test_split_join_is_byte_exact_on_every_chain_file():
    n = 0
    for rel in files.all_encoded():
        raw = files.read_source(rel)
        conts, end = container.split(raw)
        assert conts and end == len(raw) and not any(c.short for c in conts), rel
        assert container.join([c.body for c in conts]) == raw, rel
        n += 1
    assert n == 844, n


def test_split_agrees_with_the_reference_decoder():
    """The pipeline's containers are the ones the engine would read."""
    n = 0
    for rel in files.iter_files(("ms", "id")):
        raw = files.read_source(rel)
        sc = script.parse(rel, raw)
        if not sc.ok:
            continue
        ref = refdecode.decode_file(raw)
        # The reference decoder stops at the first container whose record loop
        # does not land on the container's own end -- the four files whose count
        # word overstates its body.  Compare everything it did read.
        for ci, recs in enumerate(sc.containers[:len(ref)]):
            got = [(r.id, r.data) for r in recs]
            want = [(r.id, r.data) for r in ref[ci].records][:len(got)]
            assert got == want, "%s container %d" % (rel, ci)
        if len(ref) == len(sc.containers) and not any(c.error for c in ref):
            n += 1
    assert n >= 210, "only %d record files compared end to end" % n


def test_length_changed_container_decodes_under_the_engine_rule():
    """The bug the seed rule fixes: a container whose body grew or shrank.

    The old pipeline wrote the ciphertext with seed 0 while the engine seeds from
    the (now different) header word, so the first byte of the body -- the low half
    of the record count -- came back wrong.  Rebuilt properly, the reference
    decoder gets every record back.
    """
    for delta_text in (b"", b"X", b"XXXXXXXXXXXXXXXXX", b"Y" * 300):
        recs = [records.Record(0x00, b"Hello" + delta_text + b"\x00"),
                records.Record(0x07, b"Second record\x00"),
                records.Record(0x40, b"\x1f\xd3Third\x00")]
        raw = container.join([records.serialise(recs)])
        hdr = int.from_bytes(raw[:2], "little")
        assert hdr == len(raw) - 2
        assert container.seed_of(hdr) != 0 or hdr == 0, hdr

        got = refdecode.decode_records(raw)
        assert len(got) == 1
        assert [(r.id, r.data) for r in got[0]] == [(r.id, r.data) for r in recs]

        # ... and the naive seed-0 encoding does NOT survive, which is the point.
        naive = hdr.to_bytes(2, "little") + container.enxor(records.serialise(recs))
        if container.seed_of(hdr):
            assert naive != raw


def test_multi_container_round_trip_with_a_length_change():
    """Editing container 0 must not disturb containers 1..n."""
    bodies = [records.serialise([records.Record(i, b"body %d\x00" % i)])
              for i in range(4)]
    raw = container.join(bodies)
    assert refdecode.decode_records(raw) is not None

    bodies[0] = records.serialise([records.Record(0, b"a much longer body 0\x00")])
    raw2 = container.join(bodies)
    got = refdecode.decode_records(raw2)
    assert len(got) == 4
    assert got[0][0].data == b"a much longer body 0\x00"
    for i in range(1, 4):
        assert got[i][0].data == b"body %d\x00" % i


def test_real_multi_container_file_round_trips_through_an_edit():
    rel = "m/MS6001.BIN"
    raw, sc = _script(rel)
    assert len(sc.containers) == 16, len(sc.containers)
    # Edit inside the *last* container that has an editable span; every other
    # container must come back byte for byte.
    ci, rec, sp, txt = None, None, None, None
    for k in reversed(range(len(sc.containers))):
        for r in sc.containers[k]:
            if r.untiled or r.blocked:
                continue
            for s in r.spans:
                if codec.strip_tokens(script.span_text(r, s)).strip():
                    ci, rec, sp, txt = k, r, s, script.span_text(r, s)
                    break
            if rec:
                break
        if rec:
            break
    assert rec is not None and ci is not None
    out, rep = script.build(sc, {(ci, rec.id, sp.idx): txt + "!!!!"})
    assert out != raw
    ref_before = refdecode.decode_records(raw)
    ref_after = refdecode.decode_records(out)
    assert len(ref_after) == len(ref_before) == 16
    for k in range(16):
        if k == ci:
            continue
        assert ([(r.id, r.data) for r in ref_after[k]]
                == [(r.id, r.data) for r in ref_before[k]]), "container %d moved" % k


# --------------------------------------------------------------------------
# records
# --------------------------------------------------------------------------
def test_record_layer_covers_ms_and_id_only():
    by_family = {}
    for rel in files.all_encoded():
        sc = script.parse(rel, files.read_source(rel))
        if sc.ok:
            by_family[files.family_of(rel)] = by_family.get(files.family_of(rel), 0) + 1
    assert by_family == {"ms": 200, "id": 17}, by_family


def test_runtime_bases_follow_id_order_with_one_byte_for_absent_ids():
    recs = [records.Record(0x02, b"ab"), records.Record(0x00, b"xyz")]
    b = records.bases(recs)
    assert b[0] == records.INDEX_SIZE                    # id 0 first, 3 bytes
    assert b[1] == records.INDEX_SIZE + 3                # id 1 absent, 1 byte
    assert b[2] == records.INDEX_SIZE + 4
    assert b[3] == records.INDEX_SIZE + 6


def test_serialise_body_keeps_a_bogus_count_verbatim():
    """m/MS600A container 4 declares 217 records in a body that holds 163."""
    body = records.Body(99, [records.Record(1, b"x\x00")], b"", True)
    out = records.serialise_body(body)
    assert out[:2] == (99).to_bytes(2, "little")
    again = records.parse_body(out)
    assert again.error is None
    assert again.count == 99 and again.short_count and not again.tail
    assert [r.data for r in again.records] == [b"x\x00"]
    assert records.serialise_body(again) == out


def test_serialise_body_keeps_trailing_bytes_verbatim():
    """m/MS610B container 15 has 4 158 bytes after its last record."""
    body = records.Body(1, [records.Record(1, b"x\x00")], b"\xde\xad\xbe\xef")
    out = records.serialise_body(body)
    assert out.endswith(b"\xde\xad\xbe\xef")
    again = records.parse_body(out)
    assert again.error is None
    assert again.count == 1 and again.tail == b"\xde\xad\xbe\xef"
    assert [r.data for r in again.records] == [b"x\x00"]
    assert records.serialise_body(again) == out


def test_a_body_that_is_not_a_record_list_is_rejected():
    """m/M0000.BIN: count word 0, then 6 006 bytes of map geometry."""
    geometry = records.Body(0, [], b"\x01\x02\x03" * 40)
    assert not records.is_record_layer([geometry])
    real = records.parse_body(records.serialise([records.Record(3, b"a\x00")]))
    assert records.is_record_layer([real])
    assert records.is_record_layer([real, records.Body(0, [], b"")])  # empty slot


# --------------------------------------------------------------------------
# tokenizer
# --------------------------------------------------------------------------
def test_tokenizer_reproduces_the_published_tiling_numbers():
    """Tiling census on the ORIGINAL data (re-baselined 2026-09-04).

    The v0.05-based figures were 19 207 / 1 088 / 130 / 123.  The original has
    more records ending in a clean ``00`` (v0.05 stripped ~3 240 ``1F01 nn``+``00``
    idioms, which is what moved the first two numbers) and one more record
    using an unimplemented opcode; the 123 untileable records are the same set.
    """
    tab = vmops.table()
    ok = stray = unimpl = overrun = 0
    for rel in files.iter_files(("ms", "id")):
        sc = script.parse(rel, files.read_source(rel))
        if not sc.ok:
            continue
        for rec in sc.iter_records():
            if not rec.data:
                continue
            if rec.untiled:
                overrun += 1
                continue
            if vmops.uses_unimplemented(rec.tokens, tab):
                unimpl += 1
                continue
            zeros = [t for t in rec.tokens if t.kind == "op" and t.idx == 0]
            if zeros and zeros[-1].off == len(rec.data) - 1:
                ok += 1
            else:
                stray += 1
    # The notes measured 18 913 / 1 060 / 130 / 123 over the 213 files their
    # strict record reading accepted.  The tolerant parser here accepts four
    # more files (m/MS600A, m/MS610B, et/ID00A2, et/ID00A3 -- see
    # records.is_record_layer), which contribute the extra ok/stray0 records and
    # not one extra failure: the 123 untileable records are exactly the same set.
    assert (ok, stray, unimpl, overrun) == (19317, 1119, 131, 123), (ok, stray, unimpl, overrun)


def test_operands_are_never_text():
    """``0B tt tt cc cc`` is one token; its condition byte cannot become a kana."""
    data = b"\x0b\x10\x00\x01\x02" + "あ".encode("cp932") + b"\x00"
    toks = vmops.tokenize(data)
    assert [t.kind for t in toks] == ["op", "text", "op"]
    assert toks[0].size == 5 and toks[0].idx == 0x00B
    assert [o.kind for o in toks[0].ops] == ["rel16", "u8", "u8"]
    assert codec.render(data, toks[1:2]) == "あ"


def test_wait_1e10_is_data_dependent():
    assert vmops.tokenize(b"\x1e\x10\x01\x01")[0].size == 4
    assert vmops.tokenize(b"\x1e\x10\x01\x00\x05")[0].size == 5
    assert vmops.tokenize(b"\x1e\x10\x01\x02\x05")[0].size == 5


def test_rel16_is_measured_from_the_byte_after_the_operand():
    # 18 tt tt at offset 0 in a record whose runtime base is 0x400:
    # pc_after = 0x400 + 3, target = pc_after + imm
    toks = vmops.tokenize(b"\x18\x09\x00" + b"A" * 9 + b"\x00")
    op = toks[0].ops[0]
    assert vmops.rel16_target(0x400, toks[0], op) == 0x400 + 3 + 9
    assert vmops.rel16_imm(0x400, op.off, op.size, 0x400 + 3 + 9) == 9


def test_ms0004_choice_record_tiles_exactly_as_the_notes_say():
    """§2.9's structural cross-check, as a regression test."""
    _raw, sc = _script("m/MS0004.BIN")
    rec = next(r for r in sc.iter_records() if r.id == 0x35 and r.ci == 0)
    assert len(rec.data) == 89                         # 93 in v0.05
    assert sum(t.size for t in rec.tokens) == 89
    jumps = [t for t in rec.tokens if t.idx == 0x018]
    assert len(jumps) == 3
    assert {vmops.rel16_target(0, t, t.ops[0]) for t in jumps} == {0x58}
    assert rec.data[0x58] == 0x00                      # the record terminator
    opts = [t for t in rec.tokens if t.idx == 0x212]
    assert len(opts) == 4
    for a, b in zip(opts, opts[1:]):
        assert vmops.rel16_target(0, a, a.ops[0]) == b.off


# --------------------------------------------------------------------------
# codec
# --------------------------------------------------------------------------
def test_codec_round_trips_every_span_in_the_corpus():
    n = 0
    for rel in files.iter_files(("ms", "id")):
        raw = files.read_source(rel)
        sc = script.parse(rel, raw)
        if not sc.ok:
            continue
        for rec, sp in sc.iter_spans():
            txt = script.span_text(rec, sp)
            assert codec.encode(txt) == rec.data[sp.off:sp.end], \
                "%s %s[%d]: %r" % (rel, sp.rec_key, sp.idx, txt)
            n += 1
    assert n > 45000, n


def test_pool_calls_fold_their_operand_into_one_token():
    data = b"\x08\x1f\x01\x03" + "：".encode("cp932")
    toks = vmops.tokenize(data)
    assert codec.render(data, toks) == "{08:1F}{01:03}："
    assert codec.encode("{08:1F}{01:03}：") == data


def test_wait_and_newline_render_readably():
    data = b"A\x0aB\x1e\x10\x01\x01C"
    assert codec.render(data, vmops.tokenize(data)) == "A\\nB<wait>C"
    assert codec.encode("A\\nB<wait>C") == data
    odd = b"\x1e\x10\x01\x00\x05"
    assert codec.render(odd, vmops.tokenize(odd)) == "{1E10:010005}"
    assert codec.encode("{1E10:010005}") == odd


def test_codec_escapes_are_total():
    for s in ("a\\\\b", "\\{x}", "\\<wait>", "{08:1F}", "100%", "{=E9}{=00}"):
        assert isinstance(codec.encode(s), bytes)
    assert codec.encode("\\{") == b"{"
    assert codec.encode("\\<") == b"<"
    assert codec.encode("\\\\") == b"\\"


def test_codec_refuses_what_would_corrupt_the_stream():
    def bad(s, allow=None):
        try:
            codec.encode(s) if allow is None else codec.encode(s, allow)
        except codec.CodecError:
            return True
        return False

    assert bad("{18:0900}")            # a branch may not live inside a span
    assert bad("{08:1F2F}")            # too many operand bytes for opcode 08
    assert bad("{08}")                 # too few
    assert bad("{E9}")                 # a raw byte must be written {=E9}
    assert bad("stray { brace")
    assert bad("stray < angle")
    assert bad("trailing \\")
    assert bad("☃")               # not encodable in cp932
    assert bad("a\tb")
    assert bad("<wait>", frozenset())


def test_no_dict_artefact_can_be_produced():
    """``{DICT:nn}`` was a resync error; the v2 grammar has no such token."""
    for rel in files.iter_files(("ms", "id")):
        sc = script.parse(rel, files.read_source(rel))
        if not sc.ok:
            continue
        for rec, sp in sc.iter_spans():
            assert "{DICT" not in script.span_text(rec, sp)


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------
def test_v2_identity_build_is_byte_exact_on_all_844_files():
    from giten import build_v2

    n = 0
    for rel in files.all_encoded():
        raw = files.read_source(rel)
        res = build_v2.build_file(rel, raw, [])
        assert not res.errors, res.errors
        assert res.raw == raw, rel
        n += 1
    assert n == 844, n


def test_identity_build_relocates_nothing():
    for rel in ("m/MS0003.BIN", "m/MS6000.BIN", "et/ID0099.BIN"):
        raw, sc = _script(rel)
        out, rep = script.build(sc, {})
        assert out == raw and rep.relocated == 0 and not rep.errors


# --------------------------------------------------------------------------
# relocation
# --------------------------------------------------------------------------
def test_rel16_relocation_on_a_lengthening_edit_in_ms0003():
    """Every branch must still land on the same instruction after the edit."""
    rel = "m/MS0003.BIN"
    raw, sc = _script(rel)
    before = branch_map(sc, 0)
    assert before, "no branches to relocate"

    rec, sp, txt = _first_editable_span(sc)
    assert rec.ci == 0
    longer = txt + " and then some more words to make this line much longer"
    out, rep = script.build(sc, {(rec.ci, rec.id, sp.idx): longer})
    assert out != raw
    assert rep.size_delta == len(codec.encode(longer)) - (sp.end - sp.off)
    assert not rep.errors

    sc2 = script.parse(rel, out)
    assert sc2.ok, sc2.error
    after = branch_map(sc2, 0)

    checked = 0
    for key, tgt in before.items():
        if tgt[0] == "?":
            continue                      # target outside the image: nothing to say
        assert key in after, "branch %s disappeared" % (key,)
        assert after[key] == tgt, "branch %s: %s -> %s" % (key, tgt, after[key])
        checked += 1
    assert checked > 20, checked
    # ...and the edit really did move things: at least one displacement changed.
    assert rep.relocated > 0, "nothing was relocated, so nothing was proved"


def test_relocation_survives_a_shortening_edit_too():
    rel = "m/MS0003.BIN"
    raw, sc = _script(rel)
    before = branch_map(sc, 0)
    rec, sp, txt = _first_editable_span(sc)
    shorter = codec.strip_tokens(txt)[:1] or "x"
    out, rep = script.build(sc, {(rec.ci, rec.id, sp.idx): shorter})
    assert len(out) < len(raw)
    sc2 = script.parse(rel, out)
    after = branch_map(sc2, 0)
    for key, tgt in before.items():
        if tgt[0] != "?":
            assert after.get(key) == tgt, key


def test_choice_list_jumps_still_chain_after_a_longer_edit():
    """§2.9's ``1E 12`` chain: each option jumps to the next one."""
    rel = "m/MS0004.BIN"
    raw, sc = _script(rel)
    rec = next(r for r in sc.iter_records() if r.id == 0x35 and r.ci == 0)
    sp = rec.spans[0]
    txt = script.span_text(rec, sp)

    # Lengthen the choice record itself *and* a lower-id record, so the record's
    # own bytes move and its runtime base moves as well.
    lower, lsp, ltxt = None, None, None
    for r in sc.containers[0]:
        if r.id < 0x35 and not r.untiled and not r.blocked and r.spans:
            for s in r.spans:
                if codec.strip_tokens(script.span_text(r, s)).strip():
                    lower, lsp, ltxt = r, s, script.span_text(r, s)
                    break
        if lower:
            break
    assert lower is not None

    edits = {(0, rec.id, sp.idx): txt.replace("<wait>", " -- a longer line.<wait>"),
             (0, lower.id, lsp.idx): ltxt + " (padded out a good deal further)"}
    out, rep = script.build(sc, edits)
    assert not rep.errors and out != raw

    sc2 = script.parse(rel, out)
    rec2 = next(r for r in sc2.iter_records() if r.id == 0x35 and r.ci == 0)
    assert len(rec2.data) > len(rec.data)

    opts = [t for t in rec2.tokens if t.idx == 0x212]
    assert len(opts) == 4
    for a, b in zip(opts, opts[1:]):
        assert vmops.rel16_target(0, a, a.ops[0]) == b.off, \
            "1E 12 chain broken at 0x%X" % a.off
    jumps = [t for t in rec2.tokens if t.idx == 0x018]
    assert {vmops.rel16_target(0, t, t.ops[0]) for t in jumps} == {len(rec2.data) - 1}


def test_a_cross_record_branch_is_relocated():
    """Lengthening record k must fix branches from records with a lower id."""
    rel = "m/MS0000.BIN"
    raw, sc = _script(rel)
    before = branch_map(sc, 0)
    cross = {k: v for k, v in before.items() if v[0] not in ("?",) and v[0] != k[0]}
    if not cross:
        return                                   # nothing to prove in this file
    rec, sp, txt = _first_editable_span(sc)
    out, rep = script.build(sc, {(rec.ci, rec.id, sp.idx): txt + "0123456789"})
    after = branch_map(script.parse(rel, out), 0)
    for key, tgt in cross.items():
        assert after.get(key) == tgt, "cross-record branch %s: %s -> %s" % (
            key, tgt, after.get(key))


def test_untiled_records_are_copied_verbatim_and_refuse_edits():
    rel = None
    for cand in files.iter_files(("ms",)):
        sc = script.parse(cand, files.read_source(cand))
        if sc.ok and sc.untiled_records:
            rel = cand
            break
    assert rel is not None
    raw, sc = _script(rel)
    bad = sc.untiled_records[0]
    assert bad.blocked == script.UNTILED_NOTE
    out, rep = script.build(sc, {(bad.ci, bad.id, 0): "this must be ignored"})
    assert out == raw
    assert any(script.UNTILED_NOTE in e and "copied verbatim" in e
               for e in rep.errors), rep.errors


def test_every_record_still_tiles_after_a_corpus_wide_synthetic_edit():
    """Append a marker to the first span of every file and re-tile everything."""
    tab = vmops.table()
    files_done = regressions = 0
    for rel in files.iter_files(("ms", "id")):
        raw = files.read_source(rel)
        sc = script.parse(rel, raw)
        if not sc.ok:
            continue
        try:
            rec, sp, txt = _first_editable_span(sc)
        except AssertionError:
            continue
        out, rep = script.build(sc, {(rec.ci, rec.id, sp.idx): txt + "abc"})
        if rep.errors:
            continue
        sc2 = script.parse(rel, out)
        assert sc2.ok, "%s: %s" % (rel, sc2.error)
        was = {(r.ci, r.id, r.order) for r in sc.untiled_records}
        now = {(r.ci, r.id, r.order) for r in sc2.untiled_records}
        regressions += len(now - was)
        files_done += 1
    assert files_done > 200, files_done
    assert regressions == 0, regressions


# --------------------------------------------------------------------------
# width budgets
# --------------------------------------------------------------------------
def test_width_is_measured_in_columns():
    assert codec.display_width("abcd") == 4              # half width, 1 column
    assert codec.display_width("ああ") == 4              # full width, 2 columns
    assert codec.display_width("ｱｲｳ") == 3               # half-width katakana
    assert codec.display_width("{08:1F}<wait>\\n") == 0  # tokens draw nothing here


def test_width_budget_is_74_columns():
    assert width.LINE_COLUMNS == 74                      # 76 columns minus slack 2
    assert width.PAGE_ROWS == 4
    assert not width.findings("x" * 74)
    got = width.findings("x" * 75)
    assert [r for r, _m in got] == ["width"]
    assert "75 columns" in got[0][1]


def test_page_row_budget_counts_lines_between_waits():
    ok = "\\n".join(["line"] * 4)
    assert not width.findings(ok)
    assert [r for r, _m in width.findings("\\n".join(["line"] * 5))] == ["page-rows"]
    # a <wait> starts a new page, so 4 + 4 is fine
    assert not width.findings("\\n".join(["line"] * 4) + "<wait>"
                              + "\\n".join(["line"] * 4))


def test_choice_option_budget_is_the_declared_width():
    assert width.CHOICE_COLUMNS == 20
    assert not width.findings("x" * 20, is_choice=True)
    got = width.findings("x" * 21, is_choice=True)
    assert [r for r, _m in got] == ["width-choice"]
    assert not width.findings("x" * 21, is_choice=True, choice_width=30)
    # a full-width option: 10 characters is 20 columns
    assert not width.findings("あ" * 10, is_choice=True)
    assert width.findings("あ" * 11, is_choice=True)


def test_pages_split_on_wait_not_on_an_escaped_backslash():
    assert width.pages("a\\nb") == [["a", "b"]]
    assert width.pages("a<wait>b") == [["a"], ["b"]]
    assert width.pages("a\\\\nb") == [["a\\\\nb"]]


def test_declared_choice_width_is_read_from_1fb1():
    """1690 of 1752 menus declare 20; the rest must be read, not assumed."""
    seen = set()
    for rel in files.iter_files(("ms",)):
        sc = script.parse(rel, files.read_source(rel))
        if not sc.ok:
            continue
        for _rec, sp in sc.iter_spans():
            if sp.choice_width:
                seen.add(sp.choice_width)
    assert 20 in seen
    assert seen - {20}, "no menu with a non-default width was found: %s" % seen


# --------------------------------------------------------------------------
# tables, extraction, migration
# --------------------------------------------------------------------------
def test_extraction_rows_are_addressable_and_stable():
    rel = "m/MS0003.BIN"
    raw = files.read_source(rel)
    rows = extract_v2.rows_for(rel, raw, pool.load())
    assert rows
    keys = [(r.rec, r.idx) for r in rows]
    assert len(keys) == len(set(keys)), "row identities are not unique"
    for r in rows:
        assert r.rec.count(":") == 1 or r.rec == extract_v2.PNAME_REC
    assert rows == extract_v2.rows_for(rel, raw, pool.load())


def test_extracted_rows_rebuild_to_the_source_bytes():
    """Feeding every ``jp`` back in as ``en`` is a no-op."""
    from giten import build_v2

    for rel in ("m/MS0003.BIN", "et/ID0099.BIN", "m/MS0004.BIN"):
        raw = files.read_source(rel)
        rows = extract_v2.rows_for(rel, raw, pool.load())
        for r in rows:
            r.en = r.jp
        assert build_v2.build_file(rel, raw, rows).raw == raw, rel


def test_pname_field_is_fixed_width():
    from giten import build_v2

    rel = "p/P2000.BIN"
    raw = files.read_source(rel)
    rows = extract_v2.pname_rows(rel, raw)
    assert len(rows) == 1 and rows[0].rec == extract_v2.PNAME_REC
    rows[0].en = "Short"
    out = build_v2.build_file(rel, raw, rows)
    assert not out.errors and len(out.raw) == len(raw)
    rows[0].en = "X" * 40
    assert build_v2.build_file(rel, raw, rows).errors


def _row(jp, en, tag="1FD3", note=""):
    # a real edit needs a status now; "draft" keeps these legacy rows meaningful
    return tables.Row("m/X.BIN", "0:00", 0, 0, tag, jp, en, status="draft", note=note)


def test_validator_reports_encode_errors_as_errors():
    from giten import check_v2

    rep = check_v2.Report()
    check_v2.check_rows(rep, [_row("a", "{18:0000}"), _row("b", "☃")])
    assert [f.rule for f in rep.errors] == ["encode", "encode"]


def test_validator_refuses_an_edit_on_an_untiled_record():
    from giten import check_v2

    rep = check_v2.Report()
    check_v2.check_rows(rep, [_row("jp", "en",
                                   note="@noedit; @untiled; read-only")])
    assert [f.rule for f in rep.errors] == ["editable"]
    # ...and a row that is only *flagged* @dupid (no @noedit) stays editable
    rep = check_v2.Report()
    check_v2.check_rows(rep, [_row("jp", "en", note="@dupid; nothing branches")])
    assert not rep.errors


def test_validator_width_findings_are_warnings():
    from giten import check_v2

    rep = check_v2.Report()
    check_v2.check_rows(rep, [_row("x", "y" * 90)])
    assert not rep.errors
    assert [f.rule for f in rep.warnings] == ["width"]


def test_validator_uses_the_declared_choice_width_from_the_note():
    from giten import check_v2

    rep = check_v2.Report()
    check_v2.check_rows(rep, [_row("x", "y" * 25, tag="1FB2",
                                   note="menu option, declared width 30 columns")])
    assert not rep.warnings
    rep = check_v2.Report()
    check_v2.check_rows(rep, [_row("x", "y" * 25, tag="1FB2",
                                   note="menu option, declared width 20 columns")])
    assert [f.rule for f in rep.warnings] == ["width-choice"]


def test_not_a_branch_is_re_derived_from_the_game_files():
    """`script.NOT_A_BRANCH` must still match what the corpus says.

    A real branch displacement points at an instruction boundary.  Roughly 39%
    of byte offsets are an instruction boundary by chance, so a genuine branch
    opcode scores near 100% and a mistyped slot scores at or below chance.  This
    re-derives the split so that a change to `docs/opcodes.json` or the
    tokenizer shows up as a failing test rather than as silently different
    output.
    """
    from giten import audit

    hit = {}
    tot = {}
    boundary_frac = []
    for rel in files.iter_files(("ms", "id")):
        sc = script.parse(rel, files.read_source(rel))
        if not sc.ok:
            continue
        for recs in sc.containers:
            if not recs:
                continue
            base = audit._bases(recs)
            bounds = audit._boundaries(recs, base)
            end = max(base[r.id] + len(r.data) for r in recs)
            boundary_frac.append(len(bounds) / max(1, end - records.INDEX_SIZE))
            for r in recs:
                if r.tokens is None:
                    continue
                for t in r.tokens:
                    for o in t.ops:
                        if o.kind != "rel16":
                            continue
                        tot[t.idx] = tot.get(t.idx, 0) + 1
                        if vmops.rel16_target(base[r.id], t, o) in bounds:
                            hit[t.idx] = hit.get(t.idx, 0) + 1

    chance = sum(boundary_frac) / len(boundary_frac)
    assert 0.40 < chance < 0.60, "unexpected boundary density %.3f" % chance

    # Anything at or below chance, with enough observations to mean something.
    derived = {k for k, n in tot.items()
               if n >= 40 and hit.get(k, 0) / n <= chance * 1.05}
    assert derived == script.NOT_A_BRANCH, (
        "corpus says NOT_A_BRANCH should be %s, code says %s"
        % (sorted("%03X" % k for k in derived),
           sorted("%03X" % k for k in script.NOT_A_BRANCH)))

    # And every opcode the builder does relocate is convincingly a branch.
    for k, n in tot.items():
        if k in script.NOT_A_BRANCH or n < 40:
            continue
        # 017 sits in the grey zone on the original (48.7% vs chance 43%);
        # it keeps the benefit of the doubt -- see docs/limits.md.
        assert hit.get(k, 0) / n > chance * 1.1, (
            "op %03X is relocated but only %.1f%% of its targets are "
            "instructions" % (k, 100 * hit.get(k, 0) / n))


def test_a_not_a_branch_slot_is_never_rewritten():
    """No `NOT_A_BRANCH` slot may change value when a record is lengthened."""
    checked = 0
    for rel in files.iter_files(("ms", "id")):
        sc = script.parse(rel, files.read_source(rel))
        if not sc.ok or not sc.containers[0]:
            continue
        recs = sc.containers[0]
        if not any(t.idx in script.NOT_A_BRANCH
                   for r in recs if r.tokens for t in r.tokens):
            continue
        try:
            rec, sp, txt = _first_editable_span(sc)
        except Exception:
            continue
        out, _ = script.build(sc, {(rec.ci, rec.id, sp.idx): txt + "0123456789"})
        after = script.parse(rel, out)
        for r in recs:
            new = next((x for x in after.containers[0] if x.id == r.id), None)
            if (new is None or r.tokens is None or new.tokens is None
                    or len(r.tokens) != len(new.tokens)):
                continue
            for t, t2 in zip(r.tokens, new.tokens):
                if t.kind != "op" or t.idx != t2.idx:
                    continue
                if t.idx not in script.NOT_A_BRANCH:
                    continue
                for o, o2 in zip(t.ops, t2.ops):
                    if o.kind != "rel16":
                        continue
                    checked += 1
                    assert o.value == o2.value, (
                        "%s r%02X: rewrote a %03X slot, which is not a branch"
                        % (rel, r.id, t.idx))
        if checked > 300:
            break
    assert checked, "no NOT_A_BRANCH slot was exercised"
