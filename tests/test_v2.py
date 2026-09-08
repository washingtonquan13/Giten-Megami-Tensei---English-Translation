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
    # 2026-09-04, switch tables (format-notes 2.12): 19 317 / 1 119 / 131 / 123
    # became 19 330 / 1 117 / 95 / 148.  36 records stopped dispatching to an
    # engine no-op (their switch table had been tiled as opcodes) and 25 records
    # that only *looked* tiled -- the walk was out of step before a switch, and a
    # 5-byte guess happened to resync -- are now refused, i.e. not editable.
    # 2026-09-06, prefix tiling (giten/partial.py): 19 330 / 1 117 / 95 / 148
    # became 19 330 / 1 117 / 100 / 143.  Exactly the five records of
    # m/MS0080.BIN -- the town's shopkeepers -- moved from `overrun` to
    # `unimpl`: they now tile to byte N via the opt-in prefix walk, and what
    # they reach is the 1F 00 engine no-op.  No record changed its tiling, and
    # `ok` and `stray` are untouched, so nothing that shipped before moved.
    # 2026-09-06: an attempt to drop the `expr` from 1F 0D/0E/0F moved these to
    # 19 476 / 1 006 / 106 / 102 and was REVERTED (tag pre-expr-model).  It fixed
    # 41 records and broke none, but its justification was wrong: objdump shows
    # 00430201 -> 00433490 -> 00437490 -> 00436B00 -> 00438FA0 -> 00438E50, i.e.
    # the handler does reach the expression reader.  The likely truth is that our
    # *expression* model is wrong -- 0x00436B00 dispatches on a selector through
    # tables at 0x437380 (selector -> kind) and 0x437288 (kind -> handler), and a
    # first reading of those disagrees with our nodes for 67 of 94 selectors.
    # Fix the root there, not by removing an operand that exists.
    # 2026-09-06, the name-print operand fix (0x17F-0x184 read ONE expression,
    # not two): 19 330 / 1 117 / 100 / 143 -> 19 394 / 1 081 / 99 / 116.
    # 27 records stopped overrunning and `stray` fell by 36 -- more records now
    # end on their terminator, which is what a correct walk does.  The stronger
    # evidence is elsewhere: garbage-prefix spans 118 -> 28, records carrying an
    # expression selector the engine would refuse 78 -> 50, and the NOT_A_BRANCH
    # re-derivation moving 0x182 to the branch side on its own.
    # 2026-09-06, two opcode fixes landed together: 19 394 / 1 081 / 99 / 116 ->
    # 19 398 / 1 084 / 97 / 111.
    #   0x117/0x118 were still typed `fixed_size 5, [u8][u8][u16][u8]` -- the exact
    #   stale mis-typing corrected for 0E/0F on 2026-09-04 and missed in that pass.
    #   Their handlers are two instructions (`push $mode; call 0x436610`) and the
    #   trampoline's only pre-switch call, 0x417990, is `movzbw 0x491566; ret` -- a
    #   global getter that touches no script bytes.  They take a bare switch table.
    #   26 occurrences now tile at 2 + 4N + 1 for N = 1..4, five records move out
    #   of `overrun`, and all 47 rel16 fields in those tables land on a legal
    #   instruction boundary.
    #   0x103/0x104 read `rel16` then an FF-terminated list of 2-byte terms, not
    #   four fixed u8 (handler 0x0042FEB0 loops over 0x004393E0, which reads the
    #   pair *before* testing for FF, so the terminator costs two bytes).  The old
    #   model equals rel16 + two terms + terminator, so it was right for the 562
    #   two-term sites and wrong for the 353 with three or more.
    # The acceptance evidence is the engine's own boundaries, not these counters:
    # against build/trace/jp*.bin, agreement rose 97.73% -> 97.84% (18 258 ->
    # 18 279 of 18 683 traced token PCs), and `impossible` fell 50 -> 46.  `stray`
    # rose by 3, which is why it is not the metric.
    # 2026-09-06, the 0x14C-0x151 family: 19 398 / 1 084 / 97 / 111 ->
    # 19 424 / 1 099 / 93 / 74.  All six push $1 into 0x004335E0, whose middle
    # call 0x004335C0 reads an expression ONLY when its argument is 0 -- so the
    # second `expr` in our model was never read, and the walk over-consumed 3-6
    # bytes at each of 404 sites.  37 records stopped overrunning.
    # Found by the tracer, not by a table: with pc0 (trace v2) every logged token
    # carries the engine's own length, and at 529 sites the engine took exactly 6
    # bytes where the model claimed 9-12.  Engine boundary agreement over 30 802
    # traced token PCs moved 93.33%% -> 96.83%%, and `impossible` 46 -> 43.
    # 2026-09-06, the last four of that same family: 19 424 / 1 099 / 93 / 74 ->
    # 19 425 / 1 099 / 93 / 73.  `0x152`-`0x155` push $1 into 0x004335E0 exactly
    # as `0x14C`-`0x151` do, and were left carrying the extra `expr` -- six of the
    # ten mode-1 entries had been fixed and the last four missed.  Found by
    # sweeping the dispatch table for every `push <imm8>; call <thunk>` that
    # forwards to that worker (all 22 of them, 11 per mode), which is what
    # `test_the_0x4335e0_family_splits_cleanly_into_mode_0_and_mode_1` now pins.
    # The counters barely move because the records still *tiled* before -- they
    # tiled wrongly.  The witness is `m/MS00DB` c0 r28: six iterations of one
    # block, identical but for a counter running 0x16 down to 0x11, exactly 25
    # bytes apart.  The old model spent 29 bytes an iteration and read the
    # counters themselves as opcodes 0x15, 0x14, 0x13, 0x12, 0x11.  rel16 landing
    # against the whole container image rose 92.52%% -> 92.60%%, unrelocatable
    # branches fell 14 -> 5, and `m/MS00D1` gained a record that never tiled.
    # The @straddle rule (2026-09-06) does NOT move these.  A straddling
    # record keeps `tokens` None so the byte builder, `_relocate` and `audit`
    # go on treating it exactly as untiled -- the build stays byte-identical,
    # which is checked by diffing it against a build with the rule disabled.
    # Its tokens live in `straddle_tokens` and reach only span resolution and
    # the overlay.  This counter measures tiling *in isolation*, so it is
    # right that it does not move.
    assert (ok, stray, unimpl, overrun) == (19425, 1099, 93, 73), (ok, stray, unimpl, overrun)


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
    # A floor, not a target.  The span count *falls* as the operand model gets
    # more correct: bytes that were over-consumed and mis-tiled used to surface
    # as spurious text spans, and every one of them is a line a translator could
    # have been asked to translate.  46 334 -> 45 609 (1F03/1F04) -> 44 810
    # (0x14C-0x151).  What this test actually asserts is the round-trip above,
    # for every span; the count only guarantees it checked a real corpus.
    assert n > 44000, n


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


def test_extract_re_anchors_on_japanese_when_span_numbering_moves():
    """A table is addressed by span index, and span numbering is a property of
    the tokenizer -- it moves whenever the opcode model improves.  Carrying `en`
    forward on the index alone puts a translation on a neighbouring line, with
    no error.  That nearly shipped with the 1F 0D/0E/0F fix (two records
    renumbered, five translations would have slid by one).
    """
    import os
    import tempfile

    from giten import extract_v2, tables

    d = tempfile.mkdtemp(prefix="giten-extract-")
    path = os.path.join(d, "m", "MS0000.BIN.tsv")
    os.makedirs(os.path.dirname(path))

    def row(idx, jp, en="", ref="", status=""):
        return tables.Row("m/MS0000.BIN", "0:01", idx, idx * 10, "1FD3", jp, en,
                          ref_en=ref, ref_src="v005" if ref else "", status=status)

    # what the table held before the model changed
    tables.write(path, [row(0, "あ", "A"), row(1, "い", "B", "b-draft", "draft"),
                        row(2, "う", "C")])

    # ...and what the tokenizer produces now: a new span appeared at idx 1, so
    # everything after it shifted up by one
    fresh = [row(0, "あ"), row(1, "NEW"), row(2, "い"), row(3, "う")]

    old_rows = tables.read(path)
    old = {r.key: r for r in old_rows}
    by_content = {}
    for o in old_rows:
        if o.en or o.ref_en or o.status:
            by_content.setdefault((o.rec, o.jp), []).append(o)
    moved = 0
    for r in fresh:
        prev = old.get(r.key)
        if prev is None or prev.jp != r.jp:
            c = by_content.get((r.rec, r.jp)) or []
            picked = c[0] if len(c) == 1 else None
            if prev is not None:
                moved += 1
            prev = picked
        if prev is None:
            continue
        if prev.en and prev.en != prev.jp:
            r.en = prev.en
        if prev.ref_en and not r.ref_en:
            r.ref_en, r.ref_src = prev.ref_en, prev.ref_src
        if prev.status and not r.status:
            r.status = prev.status

    got = {r.jp: (r.en, r.ref_en, r.status) for r in fresh}
    assert got["あ"] == ("A", "", ""), got["あ"]
    assert got["NEW"] == ("", "", ""), "the new span must not inherit anything"
    assert got["い"] == ("B", "b-draft", "draft"), got["い"]     # followed its jp
    assert got["う"] == ("C", "", ""), got["う"]
    assert moved == 2   # idx 1 and 2 had a row whose jp changed; idx 3 was new

    # the bug this replaces: index-only carry would have put "B" on the new span
    naive = {r.jp: old.get(r.key).en if old.get(r.key) else ""
             for r in [row(0, "あ"), row(1, "NEW"), row(2, "い"), row(3, "う")]}
    assert naive["NEW"] == "B", "the naive rule really did mis-anchor"


def test_extract_carries_the_reference_columns():
    """ref_en / ref_src / status were never carried, so every re-extract dropped
    35,000 reference translations on the floor."""
    import inspect

    from giten import extract_v2

    src = inspect.getsource(extract_v2.run)
    assert "prev.ref_en" in src and "prev.status" in src, \
        "extract must carry the reference columns forward"
    assert "by_content" in src and "prev.jp != r.jp" in src, \
        "extract must fingerprint on jp before trusting the span index"


def test_no_more_records_carry_an_impossible_expression_selector():
    """A selector above 0x5D is a smell, not a proof.  Corrected 2026-09-06.

    The docstring here used to say the engine "would refuse" such a selector,
    reading `cmp esi,0x5D ; ja <error>` in 0x00436B00 as an error path.  It is
    not one: `ja` goes to 0x0043727F, which is kind 61 -- the same nullary
    handler that selectors 0x08 and 0x32-0x37 legitimately use.  A byte above
    0x5D therefore behaves exactly like selector 0x08, and the MS0031 trace
    confirms it: the engine's own PC log makes the token at r01 offset 0x01F0
    eight bytes, which is only reachable if its innermost expression node is the
    byte `9f` -- above the bound.

    It stays as a tracked count because it is still a smell.  In that same
    confirmed case the byte consumed was the lead half of 泪 (`9f a3`), and the
    engine went on to render the trailing `a3` alone -- so a walk (the engine's
    or ours) that lands here is out of step with what the author wrote, even
    though every step of it is legal.

    43 records.  The @straddle rule does not change it: those records keep
    `tokens` None, so this walk still sees them as untiled.  Model work must not
    raise it.
    """
    import glob
    import os

    from giten import files, script, vmops

    tab = vmops.table()
    bad = []
    total = 0
    for p in sorted(glob.glob("original/ddswin/m/MS*.BIN")):
        rel = "m/" + os.path.basename(p)
        try:
            sc = script.parse(rel, files.read_source(rel))
        except Exception:
            continue
        if not sc.ok:
            continue
        for cont in sc.containers:
            for r in cont:
                if not r.data or r.untiled:
                    continue
                total += 1
                for t in r.tokens:
                    for o in t.ops:
                        if o.kind == "expr" and o.raw and o.raw[0] > 0x5D:
                            bad.append((rel, r.id, o.raw[0]))
                            break
                    else:
                        continue
                    break
    assert total > 20000, total
    # 2026-09-06: 78, then 50 once 0x17F-0x184 stopped reading a second
    # expression they never read, then 46 once 0x103/0x104 stopped reading four
    # fixed u8 in place of an FF-terminated term list, then 43 once 0x14C-0x151
    # stopped reading a second expression the engine never reads.  Must never rise.
    assert len(bad) <= 43, ("%d records now carry an out-of-range selector: %s"
                            % (len(bad), bad[:5]))


def test_expression_model_agrees_with_the_engine():
    """`docs/expr-nodes.json` is the engine's own answer; it must match ours.

    This exists because the first extraction claimed our model was wrong for 67
    of 94 selectors, which was itself wrong twice: the walker stepped over calls
    instead of following them (so any handler reading through a helper looked
    like a leaf), and it did not know the u32 reader at 0x00438FE0.  Both
    produced a confident, wrong table, and acting on it would have made the walk
    worse -- swapping it in raised `impossible` from 50 to 64.

    The model is complete: every selector 0x00..0x5D agrees.  0x4B and 0x4F were
    briefly thought context-dependent, but that was a third walker bug -- an
    indirect `jmp *0xTABLE(,%reg,4)` was followed as if the table address were
    code, decoding data into paths that consume bytes nothing consumes.  Both are
    plainly one `expr`; their callees dispatch on the value already read and take
    nothing from the stream.
    """
    import io
    import json
    import os

    from giten import paths

    nodes = json.load(io.open(os.path.join(paths.REPO_ROOT, "docs", "opcodes.json"),
                              encoding="utf-8"))["expressions"]["nodes"]
    doc = json.load(io.open(os.path.join(paths.REPO_ROOT, "docs", "expr-nodes.json"),
                            encoding="utf-8"))
    sel = doc["selectors"]
    assert len(sel) == 0x5E, len(sel)           # 0x00..0x5D, the engine's own bound

    ours = {int(k, 16): v for k, v in nodes.items()}
    undecidable, differ = [], []
    for key, v in sel.items():
        i = int(key, 16)
        if v["engine"] is None:
            undecidable.append(i)
        elif v["engine"] != ours.get(i):
            differ.append((key, ours.get(i), v["engine"]))

    assert not undecidable, sorted(undecidable)
    assert not differ, differ

    # the u32 reader, the finding that closed selector 0x02
    assert ours[0x02] == ["u32"], ours[0x02]
    # kind 0x0D, which delegates through 0x00438C40 = READ_U8 + READ_EXPR_DEREF
    for i in range(0x19, 0x24):
        assert ours[i] == ["u8", "expr"], (i, ours[i])


def test_a_branch_onto_a_trailing_escape_no_longer_blocks_the_edit():
    """Finished English was being withheld from the screen for no good reason.

    `_drop_branched_into` refuses an edit when a branch targets a byte strictly
    inside the span, because the replacement usually has no such byte.  But of
    322 such targets corpus-wide, 144 point at the span's own trailing `1E 10`
    page wait and 7 at a trailing `0A` -- "skip the words, go to the page break"
    -- and a translation keeps those escapes verbatim, because they are what
    ends the line.  When the last k bytes survive the edit unchanged the target
    still exists, k bytes from the end, and that is an honest anchor.

    Refusing them cost 37 lines that are written and were not shipping.
    """
    data = ("Hello".encode("cp932") + b"\x1e\x10\x01\x01"     # span: text + page wait
            + b"\x00")
    # the tail (the 1E10 page wait) is preserved by any sane translation
    old = data[:len(data) - 1]
    assert script.preserved_tail(old, "Goodbye".encode("cp932") + b"\x1e\x10\x01\x01", 4)
    # ... and is not preserved if the translator drops the page wait
    assert not script.preserved_tail(old, "Goodbye".encode("cp932"), 4)
    # a target in the middle of prose is still refused: the byte is gone
    assert not script.preserved_tail(b"abcdef", b"xyzdef", 6)
    assert script.preserved_tail(b"abcdef", b"xyzdef", 3)


def test_the_builder_still_relocates_every_branch_correctly():
    """The tail anchor must not buy shipped lines at the cost of a wrong jump.

    An anchor is a claim that some old byte lives at some new offset.  A wrong
    one silently points a branch into the middle of an English sentence, which
    is the exact corruption `_drop_branched_into` exists to prevent -- so the
    identity build is the check that matters: with no edits at all, every
    displacement must come out unchanged and every file byte-identical.
    """
    from giten import files, records

    n = 0
    for rel in list(files.iter_files(("ms",)))[:40]:
        raw = files.read_source(rel)
        sc = script.parse(rel, raw)
        if not sc.ok:
            continue
        out, rep = script.build(sc, {})           # no edits -> identity
        assert out == raw, "%s: identity build is not byte-exact" % rel
        assert rep.branched_into == 0, rel
        assert getattr(rep, "tail_anchored", 0) == 0, rel
        n += 1
    assert n > 20, n


def test_the_japanese_rule_reads_rows_the_way_the_engine_does():
    """`japanese` must expand pool calls with the ENGLISH column, not the Japanese.

    This is the whole point of the rule.  A row whose English is the bare call
    `{08:26}` is correct: the pool renders it "Yes".  Expanding with
    `pool.reading` -- the Japanese pool -- says はい and condemns 199 working
    Yes/No prompts.  Meanwhile a row that IS translated can still ship Japanese,
    because its own punctuation sits beside a call that renders English:
    `{08:03}：` shows "Emi：" with a full-width colon.
    """
    from giten import check_v2, findings, tables

    def row(**kw):
        r = tables.Row("m/MS0000.BIN", "0:00", 0, 0, kw.pop("tag", "1FD3"),
                       kw.pop("jp", "x"), kw.pop("en", ""))
        for k, v in kw.items():
            setattr(r, k, v)
        return r

    pools = [
        tables.Row("m/MS7F07.BIN", "0:26", 0, 0, "DATA", "はい", "Yes"),
        tables.Row("m/MS7F07.BIN", "0:03", 0, 0, "DATA", "英美", "Emi"),
        tables.Row("m/MS7F07.BIN", "0:72", 0, 0, "DATA", "‥‥", ""),   # untranslated
    ]
    ep = check_v2.english_pool(pools)
    assert check_v2.render_english("{08:26}", ep) == "Yes"
    assert check_v2.render_english("{08:03}：", ep) == "Emi："
    # an untranslated entry falls back to its Japanese, which is the point
    assert check_v2.render_english("{08:72}", ep) == "‥‥"

    def flagged(en, jp="x", tag="1FD3"):
        rep = findings.Report()
        check_v2.check_rows(rep, pools + [row(jp=jp, en=en, tag=tag, status="draft")])
        return [f for f in rep.errors + rep.warnings if f.rule == "japanese"]

    assert not flagged("{08:26}", jp="{08:26}"), "a bare call rendering English is fine"
    assert not flagged("Just plain English."), "ASCII must not be flagged"
    assert flagged("{08:03}：", jp="{08:03}："), "a full-width colon reaches the screen"
    assert flagged("{08:72}", jp="{08:72}"), "an untranslated pool entry reaches the screen"


def test_the_japanese_rule_sees_rows_whose_en_merely_copies_their_jp():
    """Those are the rows that ship Japanese, and they are not `edited`.

    `check_rows` skips a row that is not `edited`, and a row whose `en` equals
    its `jp` is not.  Running the rule after that gate found 1 problem in the
    whole corpus; running it before found 305.
    """
    from giten import check_v2, findings, tables

    pools = [tables.Row("m/MS7F07.BIN", "0:72", 0, 0, "DATA", "‥‥", "")]
    r = tables.Row("m/MS0000.BIN", "0:00", 0, 0, "1FD3", "{08:72}", "{08:72}")
    assert not r.edited, "a row whose en copies its jp is not edited"
    rep = findings.Report()
    check_v2.check_rows(rep, pools + [r])
    assert [f for f in rep.errors + rep.warnings if f.rule == "japanese"]


def test_1ec4_reads_one_expression_and_its_sibling_reads_two():
    """`1E C4` is mode 1 of a pair; only mode 0 reads a second expression.

    Found without a trace and without playing.  Of 25,346 rel16 targets in the
    corpus only 25 miss a token boundary, and one is in `m/MS00D8` r05 -- which
    the engine executed 187 times on the traced routes, so it is real code and
    the miss is ours.  `1E C4`'s trampoline is `push $1; call 0x00433860`, which
    forwards to `0x004335E0`: two u8 via `0x004335A0`, then `0x004335C0`, which
    reads an expression *only when its argument is 0*, then always one more.
    Mode 1 therefore takes `u8 u8 expr` and the token is 6 bytes -- 0x25 + 6 is
    0x2B, exactly the target that missed.

    `1E C3` is the control: identical shape, `push $0`, and it really does read
    both.  A model that gave them the same operands could not be right for both,
    and the corpus agrees -- one fewer boundary miss, and `ok`, `stray`,
    `unimpl`, `untiled` and `impossible` all unchanged.

    Kept as a tripwire because the two look interchangeable in a table.
    """
    import io
    import json
    import os

    from giten import paths

    ops = json.load(io.open(os.path.join(paths.REPO_ROOT, "docs", "opcodes.json"),
                            encoding="utf-8"))["opcodes"]
    c3 = [o["kind"] for o in ops["0x2C3"]["operands"]]
    c4 = [o["kind"] for o in ops["0x2C4"]["operands"]]
    assert c3 == ["u8", "u8", "expr", "expr"], c3
    assert c4 == ["u8", "u8", "expr"], c4


def test_the_name_buffer_is_not_counted_against_the_opcode_model():
    """`1F01` leaves the script; those PCs are not token boundaries at all.

    The engine prints a party-member name by reading it through the same byte
    fetch the tracer hooks, but out of a string buffer: the PC restarts at 0 and
    counts up in twos, one event per character.  No record holds those addresses,
    so scoring them against our tokenisation measured nothing about the model --
    and it is what held "engine boundary agreement" at 98.4%.

    On `jp2` + `jp-friends` this covers 252 events.  With them classified, the
    events our model actually gets wrong number **zero**; what is left is 29
    script-end events the v1 tracer could not place (it read the context after
    `exec_token` returned, and the engine had already cleared it -- v2's `pc0`
    is the fix) and 10 excursions that no `1F01` bounds, which stay
    disagreements because their cause is not proven.

    The classifier is deliberately strict: a run counts only when a `1F01` token
    sits on one side of it, the body is even PCs ascending from 2 whose bytes
    decode as cp932, and execution resumes inside a record.
    """
    import os

    from giten import paths
    from giten.trace import core

    d = os.path.join(paths.REPO_ROOT, "build", "trace")
    root = os.path.join(paths.REPO_ROOT, "original", "ddswin")
    if not (os.path.exists(os.path.join(d, "jp2.bin")) and os.path.exists(root)):
        return                                   # traces are not in the repo

    named = agree = total = 0
    for name in ("jp2.bin", "jp-friends.bin"):
        for e in core.decode(os.path.join(d, name), root):
            total += 1
            agree += 1 if e.ok else 0
            named += 1 if e.kind == core.NAME_KIND else 0
    assert (total, named) == (18683, 252), (total, named)
    assert agree == 18644, agree
    # every classified event must really be one the script cannot hold
    assert agree - named == 18392, agree - named


def test_dropping_a_pool_call_that_prints_a_name_is_an_error():
    """`{04:03}` is not decoration; it is the actor.

    m/MS7F03 r03 and r05 hold three `1F01` opcodes around a single ideographic
    space, so the engine prints a party-member name when the call is expanded.
    `pool.reading` shows only that space, which is how thirteen battle lines lost
    their actor to an English `" "` -- and lost it *silently*, because the line
    still reads, it just has nobody in it.

    Dropping an ordinary pool call stays correct and unreported: an English line
    spells the word out instead of splicing a Japanese macro.  Only the ten
    name-printing entries are protected.
    """
    from giten import check_v2, findings, paths
    from giten import tables as tbl

    root = paths.game_root()
    macros = check_v2.name_macros(root)
    assert "{04:03}" in macros and "{04:05}" in macros, sorted(macros)
    assert "{08:62}" not in macros            # は、 is a grammar fragment
    assert len(macros) == 10, sorted(macros)

    def row(jp, en):
        return tbl.Row(file="m/MS00DE.BIN", rec="0:21", idx=0, off=0, tag="DATA",
                       jp=jp, en=en, status="draft")

    rep = findings.Report()
    check_v2.check_rows(rep, [row("{04:03}{08:62}", " ")], root=root)
    kinds = [f.rule for f in rep.errors]
    assert "name-macro" in kinds, kinds

    rep = findings.Report()
    check_v2.check_rows(rep, [row("{04:03}{08:62}", "{04:03} spewed ")],
                        root=root)
    assert "name-macro" not in [f.rule for f in rep.errors]

    # the ordinary case: dropping a grammar fragment is fine
    rep = findings.Report()
    check_v2.check_rows(rep, [row("{08:62}", " ")], root=root)
    assert "name-macro" not in [f.rule for f in rep.errors]


def test_1d_1e_1f_are_ordinary_expression_selectors():
    """The "escape byte in an expression" detector was wrong; this is its grave.

    The retired rule said an `expr` whose first byte is `1D`/`1E`/`1F` proves a
    bad parse, because those three bytes are the opcode escapes.  They are --
    *in opcode position*.  The expression reader never looks at them that way:
    `0x00436B00` reads one raw byte and indexes the kind table at `0x00437380`,
    where selectors `0x1C` through `0x20` inclusive all map to **kind 13**,
    handler `0x00436C49`, `['u8', 'expr']`.  `1D` and `1E` are not
    distinguishable from `1C`, which the rule never objected to.

    The corpus agrees there is nothing to see.  Counting the top-level selector
    of all 65,315 expression operands, the neighbourhood reads

        0x19  5    0x1A 11    0x1B  9    0x1C 14
        0x1D 13    0x1E 13    0x1F 57    0x20  8    0x21 16    0x22 29

    -- `1D` and `1E` sit dead centre among their neighbours.  The rule's 83
    "impossible" expressions were exactly 13 + 13 + 57, i.e. every top-level use
    of the three, with no anomaly of any kind.

    Retiring it also retires the leads it manufactured: `1FE8` 34/1717, `1F53`
    10/20, `1F54` 4/20, `1F0D` 3/742, `1F0E` 1/160, and -- the loudest and most
    misleading -- `10` at 26/55, which sent the `1F 00` hunt down a false trail.

    What survives is one *specific* observation that was filed under the rule and
    does not depend on it: in `m/MS610D` rF4 a branch points at the byte where
    `1F0D`'s expression would end if it stopped after `1f e5`.  That is a
    branch-landing conflict, tracked separately in docs/limits.md.
    """
    import struct

    from giten.exe import patch
    from giten.exe.pe import PE

    img = patch.apply(open(patch.ORG, "rb").read(), "release")
    pe = PE(img, "o")

    kinds = {sel: img[pe.va2off(0x00437380 + sel)] for sel in range(0x1C, 0x21)}
    assert len(set(kinds.values())) == 1, kinds
    kind = kinds[0x1D]
    handler = struct.unpack_from("<I", img, pe.va2off(0x00437288 + kind * 4))[0]
    assert handler == 0x00436C49, hex(handler)

    import io
    import json
    import os

    from giten import paths

    nodes = json.load(io.open(os.path.join(paths.REPO_ROOT, "docs", "opcodes.json"),
                              encoding="utf-8"))["expressions"]["nodes"]
    for sel in range(0x1C, 0x21):
        assert nodes["0x%02x" % sel] == ["u8", "expr"], sel


def test_1f00_is_a_two_byte_no_op_because_the_dispatcher_says_so():
    """The `1F 00` conflict, closed from the dispatcher rather than by playing.

    `0x0042FF50` is the image's only reference to the opcode table at
    `0x004318B0`, and it indexes that table by the raw token value under
    `cmp $0x2fd; ja`.  Entries `1D`, `1E` and `1F` are the three escape
    prefixes: each reads exactly one more byte, adds `0x300`/`0x200`/`0x100`,
    re-checks the same bound and re-dispatches.  So `1F nn` is index `0x100+nn`
    and two bytes -- and index `0x100` is the shared no-op `0x004318AA`,
    `xor ax,ax; pop esi; ret`.

    `1D nn` can never be in range (`0x300` > `0x2FD`), which is why it reads as
    "eat one byte and do nothing".

    Kept because the alternative -- "`exec_token` consumes something extra
    around `1F 00`" -- was a live hypothesis for a week, and this is what
    retired it.  See docs/limits.md.
    """
    import struct

    from giten.exe import patch
    from giten.exe.pe import PE

    img = patch.apply(open(patch.ORG, "rb").read(), "release")
    pe = PE(img, "o")

    def handler(idx):
        return struct.unpack_from("<I", img, pe.va2off(0x004318B0 + idx * 4))[0]

    # the bound the dispatcher tests, twice: `cmp $0x2fd,%eax`
    for va in (0x0042FF63, 0x0042FFBB):
        assert img[pe.va2off(va):pe.va2off(va) + 5] == b"\x3d\xfd\x02\x00\x00"

    # the three escapes, by the immediate each one adds to the byte it reads
    for prefix, want in ((0x1D, 0x300), (0x1E, 0x200), (0x1F, 0x100)):
        stub = handler(prefix)
        off = pe.va2off(stub)
        assert img[off:off + 1] == b"\xe8", "escape %02X does not start with a call" % prefix
        assert img[off + 9:off + 11] == b"\x81\xc6", "no `add esi,imm32` in escape %02X" % prefix
        got = struct.unpack_from("<I", img, off + 11)[0]
        assert got == want, "escape %02X adds 0x%X, expected 0x%X" % (prefix, got, want)

    # `1F 00` -> index 0x100 -> the shared no-op, which consumes nothing
    assert handler(0x100) == 0x004318AA
    off = pe.va2off(0x004318AA)
    assert img[off:off + 5] == b"\x66\x33\xc0\x5e\xc3"      # xor ax,ax; pop esi; ret

    # and the sentinel that makes a shorter reading of `10` impossible: opcode
    # `00` returns 0xFFFF, which the interpreter loop tests with `test ax,ax; jge`
    off = pe.va2off(handler(0x000))
    assert img[off:off + 6] == b"\x66\x0d\xff\xff\x5e\xc3"  # or ax,0xffff; pop esi; ret


def test_the_expression_table_is_the_engines_own_two_tables():
    """94 of 94 selectors, derived from the image, not inferred from the corpus.

    `0x00436B00` reads a u8 selector, maps it through `0x00437380`
    (selector -> kind) and jumps through `0x00437288` (kind -> handler).  Both
    tables are in the image, so every selector's shape is a fact: walk the 62
    handlers and count the reads on each path.

    The first attempt at this disagreed with `docs/opcodes.json` for 67 of 94
    and was recorded as "NOT yet trustworthy" -- it was walking past real
    function boundaries.  With `tools/opcode_operands.py`'s control-flow walk
    the two agree everywhere, which is what settles selector `0x0F` as a `u16`
    (kind 12, handler `0x00436C33`, one `call 0x00438FC0`) and so keeps `10`'s
    six-byte framing honest even though the text at those sites argues against
    it.  See docs/limits.md.
    """
    import io
    import json
    import os
    import struct
    import sys

    from giten import paths

    sys.path.insert(0, os.path.join(paths.REPO_ROOT, "tools"))
    import opcode_operands as oo                                  # noqa: E402

    nodes = json.load(io.open(os.path.join(paths.REPO_ROOT, "docs", "opcodes.json"),
                              encoding="utf-8"))["expressions"]["nodes"]
    assert len(nodes) == 94, len(nodes)

    kind_tab, handler_tab = 0x00437380, 0x00437288
    disagree = []
    for sel in range(0x5E):
        k = oo.IMG[oo.PEO.va2off(kind_tab + sel)]
        h = struct.unpack_from("<I", oo.IMG, oo.PEO.va2off(handler_tab + k * 4))[0]
        shapes = oo.reads(h)
        assert len(shapes) == 1, "selector 0x%02X is context-dependent" % sel
        engine = oo.spec(next(iter(shapes)))
        ours = nodes.get("0x%02x" % sel)
        if ours != engine:
            disagree.append((sel, ours, engine))
    assert not disagree, disagree

    # the one that matters: 0x0F reads a u16, exactly like 0x01
    assert nodes["0x0f"] == ["u16"] == nodes["0x01"]


def test_the_0x4335e0_family_splits_cleanly_into_mode_0_and_mode_1():
    """22 opcodes share one worker; the mode immediate decides the operand list.

    `0x004335E0` reads two u8 via `0x004335A0`, then `0x004335C0` -- which reads
    an expression **only when its argument is 0** -- then always one more.  So
    mode 0 is `u8 u8 expr expr` and mode 1 is `u8 u8 expr`, and every entry
    reaching it is `push <mode>; call <thunk>` with the mode as a literal.

    `1E C4` (0x2C4) was corrected this way earlier.  Sweeping the whole dispatch
    table for the same shape then found `0x152`-`0x155` still carrying the extra
    expression -- six of the ten mode-1 entries had been fixed and the last four
    missed, which no counter noticed because the records still tiled.

    The corpus witness is `m/MS00DB` c0 r28: six iterations of one block, byte
    for byte identical except a counter running 0x16 down to 0x11, **exactly 25
    bytes apart**.  The tokens of one iteration must sum to 25, and they do only
    when `0x153` is six bytes -- with the old model the walk drifted and read the
    loop counters themselves as opcodes 0x15, 0x14, 0x13, 0x12, 0x11.

    Kept as a tripwire because the ten mode-1 entries look interchangeable in a
    table and six of them were already right.
    """
    import io
    import json
    import os
    import struct

    from giten import paths
    from giten.exe import patch
    from giten.exe.pe import PE

    img = patch.apply(open(patch.ORG, "rb").read(), "release")
    pe = PE(img, "o")
    worker = 0x004335E0

    def rel32(va, off):
        return va + off + 5 + struct.unpack_from("<i", img, pe.va2off(va) + off + 1)[0]

    def forwards(fn):
        b = img[pe.va2off(fn):pe.va2off(fn) + 24]
        return any(b[k] == 0xE8 and rel32(fn, k) == worker for k in range(16))

    ops = json.load(io.open(os.path.join(paths.REPO_ROOT, "docs", "opcodes.json"),
                            encoding="utf-8"))["opcodes"]
    found = {}
    for idx in range(0x2FE):
        h = struct.unpack_from("<I", img, pe.va2off(0x004318B0 + idx * 4))[0]
        b = img[pe.va2off(h):pe.va2off(h) + 16]
        if b[0] != 0x6A or b[2] != 0xE8:          # push imm8 ; call
            continue
        if not forwards(rel32(h, 2)):
            continue
        found[idx] = b[1]

    assert len(found) == 22, sorted("0x%03X" % i for i in found)
    assert sorted(found.values()) == [0] * 11 + [1] * 11, found

    for idx, mode in sorted(found.items()):
        want = ["u8", "u8", "expr"] if mode else ["u8", "u8", "expr", "expr"]
        got = [o["kind"] for o in ops["0x%03X" % idx]["operands"]]
        assert got == want, ("0x%03X" % idx, mode, got, want)


def test_the_ms0031_trace_confirms_10_and_expression_kind_13():
    """The two open model questions, closed by the engine's own PC log.

    Both were engine-vs-corpus conflicts that static analysis could not settle:
    opcode `10` (whose fall-through text reads `ん、健康そのものだね`, impossible
    as a sentence) and expression kind 13 (`u8 + expr` by unconditional
    disassembly, `u8` by 41 records that would otherwise not tile).

    `tools/make_warp.py` put `0C 31 01` -- goto `m/MS0031` record 0x01 -- at the
    start of `m/MS0017` r01, the record every trace reaches once the opening has
    initialised, so the scene could be traced with no save and no playthrough.

    Of 148 logged tokens in that record, 145 lengths match this model exactly and
    no engine token start falls off one of our boundaries.  The 3 that differ are
    branches (`0x104`, `0x011`, `0x018`) whose logged PC is the branch target,
    and all three targets are token boundaries.  The disputed sites agree byte
    for byte, and `@01F0` is the one that settles kind 13: 8 bytes is only
    reachable if selector `0x1F` is `u8 + expr` nested twice.

    This test pins the *conclusions*, since the trace itself is not in the repo.
    """
    import io
    import json
    import os
    import struct

    from giten import files, paths, script, vmops
    from giten.exe import patch
    from giten.exe.pe import PE

    d = None
    sc = script.parse("m/MS0031.BIN", files.read_source("m/MS0031.BIN", paths.game_root()))
    for c in sc.containers:
        for rec in c:
            if rec.id == 0x01:
                d = rec.data
    assert d is not None
    sizes = {t.off: t.size for t in vmops.tokenize(d)}

    # what the engine's PC log measured, offset -> length
    observed = {0x01F0: 8, 0x0227: 6, 0x022F: 5, 0x02B9: 4}
    for off, ln in observed.items():
        assert sizes.get(off) == ln, (hex(off), sizes.get(off), ln)

    # @01F0 is 8 bytes only because kind 13 nests: 1f(u8 ba) -> 1f(u8 d2) -> 9f
    assert d[0x01F0:0x01F8] == b"\x10\x01\x01\x1f\xba\x1f\xd2\x9f"
    img = patch.apply(open(patch.ORG, "rb").read(), "release")
    pe = PE(img, "o")
    kind = img[pe.va2off(0x00437380 + 0x1F)]
    handler = struct.unpack_from("<I", img, pe.va2off(0x00437288 + kind * 4))[0]
    assert handler == 0x00436C49, hex(handler)
    nodes = json.load(io.open(os.path.join(paths.REPO_ROOT, "docs", "opcodes.json"),
                              encoding="utf-8"))["expressions"]["nodes"]
    assert nodes["0x1f"] == ["u8", "expr"], nodes["0x1f"]


def test_the_overlay_fingerprint_catches_a_wrong_duplicate_resolution():
    """Why the duplicate-id question is cosmetic, not a hazard.

    Ten containers hold two records with one id.  `records.bases`,
    `overlay.engine_index` and `overlay.image_bytes` all keep the **first**, and
    no trace has ever covered a duplicate-id file, so that is a model rather than
    an observation.  Four containers would be laid out differently under the
    other reading -- `m/MS6000` c8 shifts 247 of 256 bases by up to 136 bytes.

    It cannot go wrong silently.  `giten/exe/hook.c` computes
    `fnv1a(base, FP_BYTES)` over the **live** record index the engine built --
    `FP_BYTES` is 0x400, the whole 256-entry index -- and serves a container's
    spans only when that hash equals the one built from our model.  Resolve the
    duplicate the other way and the index differs, so the hash differs, so the
    hook declines and the text stays Japanese.  A wrong guess costs coverage,
    never an address.

    This test is the load-bearing half: it fails if the two readings ever hash
    the same, which is the only way the guard could be fooled.
    """
    import struct

    from giten import container, files, overlay, paths, records

    for rel, ci in (("m/MS6000.BIN", 8), ("m/MS6012.BIN", 4),
                    ("m/MS610B.BIN", 15), ("m/MS6800.BIN", 0)):
        conts, _ = container.split(files.read_source(rel, paths.ORIGINAL_DDSWIN))
        recs = [records.Record(r.id, r.data)
                for r in records.parse_body(conts[ci].body).records]
        assert records.layout_is_ambiguous(recs), rel

        first = overlay.engine_index(recs)
        have = {}
        for r in recs:
            have[r.id] = len(r.data)              # last wins
        off, last = records.INDEX_SIZE, bytearray()
        base = {}
        for i in range(256):
            base[i] = off
            off += have.get(i, records.ABSENT_LEN)
        for i in range(256):
            last += struct.pack("<HH", base[i], have.get(i, records.ABSENT_LEN))

        assert first != bytes(last), rel
        assert (overlay.fnv1a(first[:overlay.FP_BYTES])
                != overlay.fnv1a(bytes(last)[:overlay.FP_BYTES])), rel


#: Every in-place byte the release exe differs from ``dds_org.exe`` by, per pass.
#: The point of pinning these is not the totals themselves -- it is that a new
#: pass, or an existing one growing a site, cannot slip in unnoticed.  The two
#: entries flagged ``False`` are the only edits that are not there to show
#: English; ``docs/exe-patches.md`` argues for both, and that argument should be
#: revisited, not silently extended, if this list ever grows a third.
EXE_PASSES = [
    ("xp",        149, 0,    False),      # inherited from the XP patch
    ("locale",     15, 0,    True),
    # 2048 -> 1536 when overlay.dat v4 started storing each entry's served
    # length (the hook stopped deriving it, losing a flag, a min() and a local),
    # then back to 2048 for the fingerprint fallback and the out-of-bounds
    # guard, then 3072 for v5: two verification bitmaps (1 013 spans is the
    # largest entry, so 128 bytes each, twice for the two cache slots), the
    # per-span FNV check that fills them, and a second binary search for the
    # virtual side.  **The in-place count has never moved**: the cave is
    # appended, and only 38 bytes of the original are rewritten either way,
    # which is the number this test exists to hold still.
    ("ovl",        38, 3072, True),
    ("pace",       10, 0,    False),      # 60 Hz tick gate -- behaviour
    ("names",     117, 512,  True),
    ("menus",     596, 1536, True),
    ("database",   64, 512,  True),
    ("mapnames",   25, 3072, True),
    ("popup",       1, 0,    False),      # popup default 15 -> 60 -- behaviour
]


def _diff_runs(a, b):
    out, i, n = [], 0, min(len(a), len(b))
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and a[j] != b[j]:
                j += 1
            out.append((i, j - i))
            i = j
        else:
            i += 1
    return out


def test_the_exe_is_only_as_patched_as_the_documentation_says():
    """The release exe differs from the original by exactly the documented passes.

    "Have we been too liberal with the exe?" is answerable only if every changed
    byte has an owner.  This rebuilds the release image one pass at a time and
    checks each pass's own footprint, so an undocumented edit shows up as the
    pass it belongs to growing rather than as an unattributable total.
    """
    from giten.exe import (database, mapnames, menus, names, patch, timing,
                           tracer)
    from giten.exe.pe import PE

    def only(data, want):
        buf = bytearray(data)
        for pset, off, old, new, _note in patch.load():
            if pset != want:
                continue
            assert bytes(buf[off:off + len(old)]) == old, hex(off)
            buf[off:off + len(new)] = new
        return bytes(buf)

    org = open(patch.ORG, "rb").read()
    seen, cur = [], org

    def step(tag, nxt):
        runs = _diff_runs(cur, nxt)
        seen.append((tag, sum(n for _, n in runs), len(nxt) - len(cur)))
        return nxt

    cur = step("xp", only(cur, "xp"))
    cur = step("locale", only(cur, "locale"))

    pe = PE(cur, "audit")
    ovl_va = pe.imagebase + pe.sizeimage
    blob, syms = tracer.compile_hook_ex(ovl_va)
    img = bytearray(pe.append_section(".ovl", blob, tracer.TRC_CHARACTERISTICS))
    tracer._redirect(img, tracer.FETCH_SITES, tracer.FETCH, ovl_va)
    cur = step("ovl", bytes(img))

    img = bytearray(cur)
    tracer._pace(img, syms["pace"])
    cur = step("pace", bytes(img))

    for tag, fn in (("names", names.apply), ("menus", menus.apply),
                    ("database", database.apply), ("mapnames", mapnames.apply),
                    ("popup", timing.apply)):
        cur = step(tag, fn(cur))

    assert seen == [(t, n, g) for t, n, g, _ in EXE_PASSES], seen

    # ...and that chain is the exe we ship, not a parallel recipe.
    assert cur == open(tracer.build_release(), "rb").read()

    # The whole point: what is *not* translation stays a short, arguable list.
    behaviour = [t for t, _, _, is_text in EXE_PASSES if not is_text]
    assert behaviour == ["xp", "pace", "popup"], behaviour
    assert sum(n for t, n, _, is_text in EXE_PASSES
               if not is_text and t != "xp") == 11


def test_the_skill_and_map_label_databases_round_trip_byte_exactly():
    """``etdb`` parses ET0004/ET0101 and rebuilds them unchanged.

    Both are the ``u16 count + u16 offset[] + records`` shape ``itemdb``
    documents, but with a *fixed* header instead of a type byte, so the whole
    file must come back byte-for-byte before any English is substituted -- the
    same bar the item database had to clear.
    """
    from giten import container, etdb, paths

    for spec in etdb.SPECS.values():
        path = os.path.join(paths.ORIGINAL_DDSWIN, spec.rel.replace("/", os.sep))
        with open(path, "rb") as fh:
            original = fh.read()
        body = etdb.source(spec)
        recs = etdb.parse(spec, body)
        assert etdb.build(spec, recs) == body, spec.rel
        assert etdb.pack_file(spec, etdb.build(spec, recs)) == original, spec.rel

        # every record really does split into the declared number of strings
        for r in recs:
            assert len(r.strings) == spec.fields, (spec.rel, r.index)
            assert len(r.head) == spec.header, (spec.rel, r.index)

    # ...and substituting English changes only the strings, never the shape.
    spec = etdb.SKILLS
    recs = etdb.parse(spec, etdb.source(spec))
    body = etdb.build(spec, recs, {(0, 0): "No Attack"})
    again = etdb.parse(spec, body)
    assert len(again) == len(recs)
    assert again[0].text(0) == "No Attack"
    assert again[0].head == recs[0].head
    assert [r.text(1) for r in again] == [r.text(1) for r in recs]


def test_etdb_refuses_a_body_that_outgrows_the_u16_offset_table():
    """The offset table is ``u16``; a body past 64 KB would wrap, not truncate."""
    from giten import etdb

    spec = etdb.SKILLS
    recs = etdb.parse(spec, etdb.source(spec))
    huge = {(r.index, 1): "x" * 400 for r in recs}        # ~124 KB of description
    try:
        etdb.build(spec, recs, huge)
    except etdb.EtDbError as exc:
        assert "u16" in str(exc)
    else:
        raise AssertionError("etdb.build accepted a body past the u16 ceiling")


def test_the_skill_effect_marker_is_the_split_the_engine_actually_does():
    """The full-width ``＠`` in an ET0004 description splits it in two.

    Settled from the exe, not guessed: the copier at ``0x0040BC30`` compares
    each character against ``0x8197`` at ``0x0040BC55`` and either stops there
    or drops the marker and continues, on a flag the caller passes.  So the
    skill list shows the text *before* the first marker and something else
    shows the whole line with the marker removed.

    Two consequences this pins, because getting either wrong is invisible until
    someone reads the screen: the short form has to fit the 26-cell field, and
    the shipped English has to keep a short form wherever the Japanese had one
    (records 16 and 20 deliberately share theirs -- Agi and Maha Agi both read
    "a small ball of flame" in the list).
    """
    from giten import etdb

    AT = "\uff20"
    FIELD = 26

    def cells(s):
        return sum(1 if (ord(c) < 0x80 or 0xFF61 <= ord(c) <= 0xFF9F) else 2
                   for c in s)

    spec = etdb.SKILLS
    jp = etdb.parse(spec, etdb.source(spec))
    english = etdb.read_table(spec)
    body = etdb.build(spec, jp, english)
    en = etdb.parse(spec, body)
    assert len(en) == len(jp) == 309

    for r in en:
        short = r.text(1).split(AT)[0]
        assert cells(short) <= FIELD, (r.index, short, cells(short))
        assert AT not in r.text(0), r.index      # names never carry a marker

    # a description the Japanese split must still be split in English
    for i in (16, 20, 17, 19):
        assert AT in jp[i].text(1), i
        assert AT in en[i].text(1), i
    assert en[16].text(1).split(AT)[0] == en[20].text(1).split(AT)[0]

    # the marker is the cp932 byte pair the exe compares against
    assert AT.encode("cp932") == b"\x81\x97"


def test_no_span_we_serve_starts_a_token_the_engine_would_branch_on():
    """The overlay must not hand the interpreter a flow opcode.

    "The overlay cannot change flow" is usually argued from the script files
    being byte-identical, which is true and beside the point: the hook changes
    what the interpreter *reads*.  If English we serve began a token the engine
    dispatches -- ``0C`` goto-record, ``0D`` call-record, or a member of the
    ``10``-``18`` branch family -- flow would diverge from the Japanese run
    while every file on disk still matched.

    Serving those byte *values* is fine and unavoidable: they occur constantly
    as operands of inline opcodes (``{03:0E}`` is a pool call and its operand,
    and ``1E 10 01 02 14`` is a wait whose ``b == 2`` pulls a third byte).  What
    must never happen is one of them landing where the engine reads an opcode.
    So this walks each served span with the tokenizer and checks the *tokens*,
    not the bytes.
    """
    from giten import codec, tables, vmops

    BRANCHES = {0x0C, 0x0D} | set(range(0x10, 0x19))
    checked = flagged = 0
    for path in tables.iter_tables("build/tables_draft"):
        for r in tables.read(path):
            en = (r.en or "").strip()
            if not en or en == r.jp:
                continue
            try:
                raw = codec.encode(en, allow=codec.INLINE_OPS)
            except Exception:
                continue                    # check_v2 owns encodability
            checked += 1
            try:
                toks = vmops.tokenize(raw)
            except vmops.TileError:
                continue                    # a fragment need not tile alone
            for t in toks:
                op = getattr(t, "op", None)
                if op in BRANCHES:
                    flagged += 1
                    raise AssertionError(
                        "%s %s[%s] serves a flow opcode 0x%02X: %r"
                        % (r.file, r.rec, r.idx, op, en[:40]))
    assert checked > 20000, checked
    assert flagged == 0


def test_a_recorded_session_shows_the_overlay_did_not_change_flow():
    """A real trace, replayed against the overlay that produced it.

    ``test_no_span_we_serve_starts_a_token_the_engine_would_branch_on`` checks
    the *data* we would serve.  This checks what the engine actually did with
    it: 4,000 records cut from a play session, verified against the untouched
    script files and a frozen copy of that session's overlay.

    The two halves travel together on purpose.  A trace means nothing against a
    different overlay -- the served-byte reconstruction would miss and every
    English span would read as script corruption -- so pinning the trace alone
    would rot the moment the tables changed.  The overlay copy holds only the
    seven entries this slice touches.

    What it would catch that the static test cannot: the C hook serving the
    wrong bytes, or handing the program counter back to the wrong address.
    Both are invisible in the tables and would show here as a token that does
    not match the original file.
    """
    from giten import paths
    from giten.trace import core

    here = os.path.dirname(os.path.abspath(__file__))
    trace = os.path.join(here, "data", "verify-trace.gtrc")
    ovl = os.path.join(here, "data", "verify-overlay.gtov")
    stats, findings = core.verify(trace, paths.ORIGINAL_DDSWIN, ovl)

    assert findings == [], findings[:3]
    # both paths have to be exercised or this passes while checking nothing
    assert stats["served"] > 500, stats
    assert stats["from the file"] > 1500, stats
    assert stats["records"] == 4000, stats
    # and the placement rate must not quietly collapse into "unverified"
    placed = stats["served"] + stats["from the file"]
    assert placed / stats["records"] > 0.7, stats


def test_the_overlay_file_id_is_right_for_every_script_family():
    """``_fid`` must read the id, not a fixed slice of the path.

    It was ``int(rel[4:8], 16)``, which is correct for ``m/MS####`` and wrong
    for everything else: ``et/ID0099``, ``et/ID009B`` and ``et/ID009C`` all
    came out ``0xD009``.  Nothing was keyed on it because ``plan`` only ever
    passed ``m/`` files -- but extending the overlay to ``et/ID*`` is exactly
    the change that would have shipped three files sharing one id, and the
    fingerprint would then have decided which of them got served.
    """
    from giten import overlay, paths

    assert overlay._fid("m/MS0017.BIN") == 0x0017
    assert overlay._fid("m/MS7F07.BIN") == 0x7F07
    assert overlay._fid("et/ID0099.BIN") == 0x0099
    assert overlay._fid("et/ID014E.BIN") == 0x014E

    # and no two script files may now share one
    seen = {}
    for sub, prefix in (("m", "MS"), ("et", "ID")):
        d = os.path.join(paths.ORIGINAL_DDSWIN, sub)
        for name in os.listdir(d):
            if not (name.startswith(prefix) and name.endswith(".BIN")):
                continue
            rel = "%s/%s" % (sub, name)
            seen.setdefault(overlay._fid(rel), []).append(rel)
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    # m/MS00A2 and et/ID00A2 genuinely share id 0xA2, as do 0xA3; the overlay
    # tells them apart by fingerprint, which is what the fingerprint is for.
    assert sorted(dupes) == [0x00A2, 0x00A3], sorted(dupes)
    for k, v in dupes.items():
        assert len(v) == 2 and v[0].startswith("m/") != v[1].startswith("m/"), v


def test_rebuilt_p_files_touch_only_the_name_field():
    """The 432 ``p/`` files are direct edits, so prove they move nothing.

    ``p/`` is the one family the overlay deliberately does not cover -- the name
    is a fixed-width field, so it is written in place instead.  That was
    dismissed as harmless because every file keeps its length, which is not the
    same thing: a rebuild could still disturb bytes the engine indexes and no
    length check would notice.

    Checked in *body* coordinates, not file offsets.  A first pass at this used
    the file offset and reported 431 of 432 files differing outside the field,
    which was the arithmetic being wrong rather than the files.
    """
    from giten import container, paths, spans

    a_dir = os.path.join(paths.ORIGINAL_DDSWIN, "p")
    b_dir = os.path.join(os.path.dirname(paths.ORIGINAL_DDSWIN.rstrip(os.sep)),
                         "..", "play", "en", "ddswin", "p")
    b_dir = os.path.normpath(b_dir)
    if not os.path.isdir(b_dir):
        return                               # no installed build to compare against

    lo, hi = spans.PNAME_OFF, spans.PNAME_OFF + spans.PNAME_LEN
    checked = 0
    for name in sorted(os.listdir(a_dir)):
        with open(os.path.join(a_dir, name), "rb") as fh:
            a = fh.read()
        pb = os.path.join(b_dir, name)
        if not os.path.exists(pb):
            continue
        with open(pb, "rb") as fh:
            b = fh.read()
        checked += 1
        assert len(a) == len(b), name
        ca, ea = container.split(a)
        cb, eb = container.split(b)
        assert len(ca) == len(cb) and ea == eb, name
        for i, (x, y) in enumerate(zip(ca, cb)):
            differ = [k for k in range(len(x.body)) if x.body[k] != y.body[k]]
            if i == 0:
                differ = [k for k in differ if not (lo <= k < hi)]
            assert not differ, (name, i, differ[:4])
    assert checked > 400, checked


# ---------------------------------------------------------------------------
# Adversarial tests for the flow verifier.
#
# Everything the verifier had ever done was pass, which is not evidence that it
# works -- and it was demonstrably not evidence, because it passed on the trace
# of a session that ended in an infinite loop.  The loop was built from `01 xx`
# pool calls, a legal inline opcode, executed from an address belonging to
# nobody; "no flow opcode was served" stayed true throughout.
#
# So each check gets a mutation test: take the clean fixture, inject exactly the
# fault that check exists to find, and require it to fire.  A check that cannot
# be made to fail is not a check.
# ---------------------------------------------------------------------------

def _fixture_paths():
    here = os.path.dirname(os.path.abspath(__file__))
    return (os.path.join(here, "data", "verify-trace.gtrc"),
            os.path.join(here, "data", "verify-overlay.gtov"))


def _rewrite_record(blob, n, **fields):
    """Return `blob` with one trace record's fields replaced."""
    from giten.trace import core
    head, body = blob[:core.HEADER.size], bytearray(blob[core.HEADER.size:])
    off = n * core.RECORD_V2.size
    vals = list(core.RECORD_V2.unpack_from(body, off))
    order = ("file", "rec", "pc", "ch", "r", "capflag", "caplen",
             "idx_off", "idx_len", "pc0", "flags")
    for k, v in fields.items():
        vals[order.index(k)] = v
    core.RECORD_V2.pack_into(body, off, *vals)
    return head + bytes(body)


def _first_of(findings, needle):
    return [f for f in findings if needle in f[1]]


def test_the_verifier_catches_a_program_counter_that_belongs_to_nobody(tmpdir=None):
    """Inject the soft lock's signature and require it to be found.

    A PC above the file's image and outside every virtual range we declare
    means the engine is reading memory neither the script nor the translation
    owns.  That is the state the 2026-09-07 soft lock ran in for 228 records
    while every other check stayed green.
    """
    import tempfile
    from giten import paths
    from giten.trace import core

    trace, ovl = _fixture_paths()
    with open(trace, "rb") as fh:
        blob = fh.read()

    # control: unmutated, nothing found
    stats, findings = core.verify(trace, paths.ORIGINAL_DDSWIN, ovl)
    assert findings == [], findings[:2]
    assert stats["out of bounds"] == 0, stats

    # find a record the verifier currently places, and move its PC out of range
    n = next(i for i in range(200)
             if core.RECORD_V2.unpack_from(blob[core.HEADER.size:],
                                           i * core.RECORD_V2.size)[9])
    bad = _rewrite_record(blob, n, pc0=0xF000)
    d = tempfile.mkdtemp()
    p = os.path.join(d, "mutant.gtrc")
    with open(p, "wb") as fh:
        fh.write(bad)
    stats, findings = core.verify(p, paths.ORIGINAL_DDSWIN, ovl)
    hits = _first_of(findings, "outside the file")
    assert hits, "an out-of-range program counter was not reported"
    assert stats["out of bounds"] >= 1, stats
    assert hits[0][0].pc0 == 0xF000


def test_the_verifier_catches_a_byte_that_does_not_match_the_original():
    """Inject a token the original file does not have at that address."""
    import tempfile
    from giten import paths
    from giten.trace import core

    trace, ovl = _fixture_paths()
    with open(trace, "rb") as fh:
        blob = fh.read()

    # a record the verifier resolved against the file, whose ch we can corrupt
    base = core.verify(trace, paths.ORIGINAL_DDSWIN, ovl)
    assert base[1] == []

    n = next(i for i in range(400)
             if core.RECORD_V2.unpack_from(blob[core.HEADER.size:],
                                           i * core.RECORD_V2.size)[9])
    bad = _rewrite_record(blob, n, ch=0x5A5A)
    d = tempfile.mkdtemp()
    p = os.path.join(d, "mutant.gtrc")
    with open(p, "wb") as fh:
        fh.write(bad)
    _stats, findings = core.verify(p, paths.ORIGINAL_DDSWIN, ovl)
    assert findings, "a token that is not in the file was not reported"


def test_the_verifier_catches_a_branch_served_out_of_our_english():
    """Doctor the overlay so a served span contains a goto, and require a report.

    This is the check that was already there, and it had never been shown to
    fire.  The span keeps its length so `head` and `tail` stay valid -- only one
    byte of English becomes `0C`, and the trace is pointed at it.
    """
    import tempfile
    from giten import overlay, paths
    from giten.trace import core

    trace, ovl_path = _fixture_paths()
    with open(ovl_path, "rb") as fh:
        ents = overlay.parse(fh.read())

    # a span with plenty of in-place English to corrupt
    target = None
    for e in ents:
        for s in e.spans:
            if s.head > 8:
                target = (e, s)
                break
        if target:
            break
    assert target, "the fixture has no in-place span to doctor"
    e, s = target
    k = 4                                        # a byte inside the head
    s.data = s.data[:k] + bytes([0x0C]) + s.data[k + 1:]

    d = tempfile.mkdtemp()
    mut_ovl = os.path.join(d, "mutant.gtov")
    with open(mut_ovl, "wb") as fh:
        fh.write(overlay.build(ents))

    # one record whose PC is just past that byte, logging what we now serve.
    # The record id and the index entry have to be the real ones for that
    # address: since the verifier stopped trusting the file register on its
    # own, a finding is only made when the engine's own index entry says the
    # label describes the buffer -- so the mutation has to supply one.
    with open(trace, "rb") as fh:
        blob = fh.read()
    rel = core._rel_of(e.fid)
    with open(os.path.join(paths.ORIGINAL_DDSWIN, *rel.split("/")), "rb") as fh:
        img = core._Image(rel, fh.read(), ents)
    rec_id = max(i for i, b in img.base.items() if b <= s.start)
    off, ln = core._index_entry(img, rec_id)
    # pc0 is one past the dispatched byte -- the caller fetches it, and that
    # fetch is what moves the PC -- so a `0C` at s.start+k is logged with
    # pc0 == s.start+k+1.
    bad = _rewrite_record(blob, 1, file=e.fid, rec=rec_id, idx_off=off, idx_len=ln,
                          pc=s.start + k + 1, pc0=s.start + k + 1, ch=0x0C)
    p = os.path.join(d, "mutant.gtrc")
    with open(p, "wb") as fh:
        fh.write(bad)

    _stats, findings = core.verify(p, paths.ORIGINAL_DDSWIN, mut_ovl)
    assert _first_of(findings, "branch served"), \
        "a goto served out of our own English was not reported"


def test_the_clean_fixture_survives_every_mutation_being_reverted():
    """The negative control: none of the above passes by reporting everything."""
    from giten import paths
    from giten.trace import core

    trace, ovl = _fixture_paths()
    stats, findings = core.verify(trace, paths.ORIGINAL_DDSWIN, ovl)
    assert findings == [], findings[:3]
    assert stats["out of bounds"] == 0
    assert stats["served"] > 500 and stats["from the file"] > 1500
    # and the two gates below must not be passing by never engaging
    assert stats["virtual PCs"] > 100, stats
    assert stats["unpaired virtual PCs"] == 0, stats
    assert stats["label contradicted"] > 0, stats


# ---------------------------------------------------------------------------
# The two gates that were missing, and what they cost me to find.
#
# The soft-lock trace reported 228 program counters "outside the file and our
# overlay", in m/MS00DD record 0x4E.  Both halves of that sentence were wrong,
# for two different reasons, and each is now a gate with a mutation test.
#
#   * The file a record is labelled with comes from an engine global written
#     when a script is LOADED.  Several scripts are resident at once and the
#     interpreter runs whichever its context points at, so while it runs an
#     older one the global still names the file loaded most recently.  All 228
#     records carried an index entry -- read by trace.S out of the live buffer
#     -- that MS00DD cannot produce: (0x4BEF, 1), when MS00DD's whole index
#     stops at 0x1CC9.  They were judged against a file that was not running.
#
#   * A trace only means anything against the overlay that produced it, and
#     nothing enforced that.  Re-checking the 2026-09-06 trace against today's
#     overlay reported 891 out-of-bounds PCs in m/MS0017; every one was an
#     artifact of one span (record 6, span 7) whose English has since been
#     dropped from the table, which shifted every virtual address above it.
#     The giveaway was that the engine kept reading coherent English past the
#     end of the last tail -- "and a discarded DB blouson lying next to it" --
#     which memory past the script buffer cannot produce.
# ---------------------------------------------------------------------------

def test_a_stale_file_label_is_never_judged():
    """Corroboration must gate the bounds check, not decorate it.

    Same mutation as the out-of-bounds test -- a program counter moved out of
    range -- but with the engine's index entry changed too, so the label no
    longer describes the buffer.  The first mutation alone must be reported;
    the pair must not, because there is no longer any file to report it
    against.  Without this, `_corroborated` could return True unconditionally
    and every test here would still pass.
    """
    import tempfile
    from giten import paths
    from giten.trace import core

    trace, ovl = _fixture_paths()
    with open(trace, "rb") as fh:
        blob = fh.read()
    body = blob[core.HEADER.size:]

    n = next(i for i in range(400)
             if core.RECORD_V2.unpack_from(body, i * core.RECORD_V2.size)[9]
             and core.RECORD_V2.unpack_from(body, i * core.RECORD_V2.size)[7])
    d = tempfile.mkdtemp()

    # 1. out of range, label intact -> reported
    p = os.path.join(d, "labelled.gtrc")
    with open(p, "wb") as fh:
        fh.write(_rewrite_record(blob, n, pc0=0xF000))
    stats, findings = core.verify(p, paths.ORIGINAL_DDSWIN, ovl)
    assert _first_of(findings, "outside the file"), stats

    # 2. out of range, and the engine's own entry says this is not that file
    q = os.path.join(d, "stale.gtrc")
    with open(q, "wb") as fh:
        fh.write(_rewrite_record(blob, n, pc0=0xF000, idx_off=0x4BEF, idx_len=1))
    stats2, findings2 = core.verify(q, paths.ORIGINAL_DDSWIN, ovl)
    assert not _first_of(findings2, "outside the file"), \
        "a program counter was judged against a file the engine was not running"
    assert stats2["label contradicted"] == stats["label contradicted"] + 1, \
        (stats2["label contradicted"], stats["label contradicted"])


def test_a_trace_is_refused_against_an_overlay_that_did_not_produce_it():
    """Move one span's virtual address and require the pairing gate to fire.

    Dropping a span is what really happened, but it changes span *count* as
    well as addresses; moving one tail by a byte isolates the property being
    tested -- that virtual addresses are ours, so they can only agree with the
    overlay that assigned them.
    """
    import tempfile
    from giten import overlay, paths
    from giten.trace import core

    trace, ovl_path = _fixture_paths()
    with open(ovl_path, "rb") as fh:
        ents = overlay.parse(fh.read())

    # the file the fixture spends most of its virtual PCs in
    stats, _ = core.verify(trace, paths.ORIGINAL_DDSWIN, ovl_path)
    assert stats["virtual PCs"] > 100 and stats["unpaired virtual PCs"] == 0

    moved = 0
    for e in ents:
        for s in e.spans:
            if s.tail:
                s.virt += 1                 # every address above this one shifts
                moved += 1
    assert moved, "the fixture overlay has no tails to move"

    d = tempfile.mkdtemp()
    p = os.path.join(d, "shifted.gtov")
    with open(p, "wb") as fh:
        fh.write(overlay.build(ents))
    stats2, findings = core.verify(trace, paths.ORIGINAL_DDSWIN, p)
    assert _first_of(findings, "not the one that produced this trace"), \
        "a trace was checked against an overlay that could not have produced it"
    assert stats2["unpaired virtual PCs"] > 0, stats2


def test_the_pairing_gate_stops_the_verifier_rather_than_colouring_it():
    """A refused pairing must suppress the per-event findings, not add to them.

    Every address-based answer is wrong once the pairing is wrong, so reporting
    them alongside the refusal would be handing over conclusions drawn from the
    wrong text.  The report says REFUSED and stops.
    """
    import tempfile
    from giten import overlay, paths
    from giten.trace import core

    trace, ovl_path = _fixture_paths()
    with open(ovl_path, "rb") as fh:
        ents = overlay.parse(fh.read())
    for e in ents:
        for s in e.spans:
            if s.tail:
                s.virt += 1
    d = tempfile.mkdtemp()
    p = os.path.join(d, "shifted.gtov")
    with open(p, "wb") as fh:
        fh.write(overlay.build(ents))

    _stats, findings = core.verify(trace, paths.ORIGINAL_DDSWIN, p)
    assert len(findings) == 1, [f[1] for f in findings[:4]]
    text, rc = core.report_verify(trace, paths.ORIGINAL_DDSWIN, 20, p)
    assert rc == 1
    assert "REFUSED" in text
    assert "wrong build directory" not in text, text


def test_a_span_whose_japanese_carries_ff_is_never_overlaid():
    """0xFF is structural, and the menu rescanner scans for it through our hook.

    ``0x00435CF0`` saves the program counter, scans forward calling
    ``0x438FA0`` until it reads ``0xFF``, then restores the PC at
    ``0x00435D23``.  ``0x438FA0`` calls ``0x438E50``, and ``0x438FAD`` is one of
    the five fetch sites the overlay hooks -- so that scan reads English wherever
    we serve it, and English is ASCII.  A scan that enters a span whose Japanese
    held the terminator cannot stop where the original did.

    ``0xFF`` is unassigned in cp932, so it is never a text byte: a span
    containing one was never pure text and serving it was unsound regardless.
    """
    from giten import overlay

    assert overlay.STRUCTURAL_BYTE == 0xFF
    # it cannot be produced by encoding any text, which is why English loses it
    import giten.codec as codec
    for probe in ("A", "test", "\u3042"):
        assert 0xFF not in codec.encode(probe, allow=codec.INLINE_OPS)


def test_the_ff_refusal_actually_fires_on_a_span_that_has_one():
    """Adversarial: hand plan() a row over Japanese containing 0xFF."""
    from giten import overlay, paths, records, script

    # find a real span whose Japanese carries the byte
    target = None
    for rel in ("m/MS6001.BIN", "m/MS6012.BIN", "m/MS610D.BIN"):
        p = os.path.join(paths.ORIGINAL_DDSWIN, *rel.split("/"))
        if not os.path.exists(p):
            continue
        with open(p, "rb") as fh:
            sc = script.parse(rel, fh.read())
        if not sc.ok:
            continue
        for ci, cont in enumerate(sc.containers):
            for rec in cont:
                if rec.span_tokens is None:
                    continue
                for sp in rec.spans:
                    if 0xFF in rec.data[sp.off:sp.end]:
                        target = (rel, ci, rec.id, sp.idx,
                                  script.span_text(rec, sp))
                        break
                if target:
                    break
            if target:
                break
        if target:
            break
    assert target, "no span in the corpus carries 0xFF -- the rule has nothing to guard"

    rel, ci, rec_id, idx, jp = target
    row = type("Row", (), {})()
    row.file, row.rec, row.idx = rel, "%d:%02X" % (ci, rec_id), idx
    # jp must be the span's real text or stale_rows rejects the row before the
    # 0xFF rule is ever reached -- which is itself the staleness guard working
    row.en, row.jp, row.ref_en, row.status = "Plain English", jp, "", "draft"
    row.edited, row.tag = True, "TEXT"

    entries, findings = overlay.plan([row], paths.ORIGINAL_DDSWIN)
    assert any("0xFF" in why for _where, why in findings), findings
    # ...and it is refused rather than quietly served
    served = [s for e in entries for s in e.spans]
    assert not served, served[:2]


# ---------------------------------------------------------------------------
# 1EBE: the opcode whose operands depend on their own first byte.
#
# The table said three u8, unconditionally, because the static walker followed
# the `jne`-not-taken arm of the handler and never the other one -- the
# documented fall-through failure mode, and the reason 269 opcodes are typed as
# consuming nothing.  Here it was not academic: half the corpus's 1EBE sites
# take the arm we got wrong, and each one made the walk resume early, so every
# token after it in that record sat at the wrong offset.  Measured against the
# tables we ship: 442 spans of English written over bytes that were never text,
# and 2,868 more at the wrong address.
# ---------------------------------------------------------------------------

def test_1ebe_reads_six_expressions_when_its_mode_byte_is_zero():
    """The shape, straight from the handler, and the record that proves it.

    `docs/limits.md` recorded eleven bytes in `m/MS001F` r02 that nothing
    claimed, cause not named.  The model change was derived from
    `0x004324B0`, not fitted to that record -- and it consumes exactly those
    eleven bytes.  A fix that explains an anomaly it was not aimed at is the
    difference between a model and a curve fit.
    """
    import os
    from giten import paths, script, vmops

    tab = vmops.table()
    idx = next(i for i in range(0x400)
               if tab.encoding(i).replace(" ", "") == "1EBE")
    kinds = [s["kind"] for s in tab.operands(idx)]
    assert kinds == ["mode_1ebe"], kinds

    with open(os.path.join(paths.ORIGINAL_DDSWIN, "m", "MS001F.BIN"), "rb") as fh:
        sc = script.parse("m/MS001F.BIN", fh.read())
    rec = next(r for r in sc.containers[0] if r.id == 2)
    off = rec.data.find(bytes.fromhex("1ebe000172"))
    assert off > 0, "the mode-0 1EBE moved"
    tok = next(t for t in rec.tokens if t.off == off)
    assert tok.size == 16, ("mode 0 must swallow the eleven bytes that used to "
                            "be unclaimed, not 5", tok.size)
    assert rec.data[tok.off:tok.end].hex() == (
        "1ebe" "00"                        # the opcode, then mode 0
        "017201000000060000" "04ff0064")   # six expressions, thirteen bytes

    # ...and the very next one, mode 1, still takes the short arm
    nxt = next(t for t in rec.tokens if t.off == tok.end)
    assert rec.data[nxt.off:nxt.off + 3].hex() == "1ebe01"
    assert nxt.size == 5, nxt.size


def test_both_1ebe_arms_are_exercised_by_the_corpus():
    """Neither arm may be dead, or the test above proves nothing general."""
    import collections
    import os
    from giten import paths, script, vmops

    tab = vmops.table()
    seen = collections.Counter()
    d = os.path.join(paths.ORIGINAL_DDSWIN, "m")
    for name in sorted(os.listdir(d)):
        if not name.endswith(".BIN"):
            continue
        try:
            sc = script.parse("m/%s" % name, open(os.path.join(d, name), "rb").read())
        except Exception:
            continue
        if not sc.ok:
            continue
        for cont in sc.containers:
            for r in cont:
                for t in r.tokens or ():
                    if t.kind == "op" and tab.encoding(t.idx).replace(" ", "") == "1EBE":
                        seen["mode 0" if t.ops[0].raw == b"\x00" else "mode n"] += 1
    assert seen["mode 0"] > 50, seen
    assert seen["mode n"] > 50, seen


def test_1fa7_reads_expressions_until_one_is_minus_one():
    """`1FA7`/`1FA8` are a rel16 plus a list, not a rel16 plus two expressions.

    Worker 0x00435620 loops on 0x00437490 while the value is not 0xFFFF.  The
    old model claimed the first two entries; `docs/limits.md` had the
    consequence already -- at `m/MS0007` r35 the remaining five became
    NUL-opcodes and one-byte "text", which is where the garbled half-width kana
    rows came from.  All five corpus sites end on `04 ff`.
    """
    import os
    from giten import paths, script, vmops

    tab = vmops.table()
    sites = [("m/MS0007.BIN", 0x35, 0x0192, 20),
             ("m/MS0018.BIN", 0x0E, 0x01CE, 18),
             ("m/MS003F.BIN", 0x00, 0x003A, 32),
             ("m/MS003F.BIN", 0x02, 0x0002, 32),
             ("m/MS0069.BIN", 0x02, 0x0C07, 18)]
    for rel, rid, off, size in sites:
        with open(os.path.join(paths.ORIGINAL_DDSWIN, *rel.split("/")), "rb") as fh:
            sc = script.parse(rel, fh.read())
        rec = next(r for r in sc.containers[0] if r.id == rid)
        tok = next((t for t in rec.tokens or () if t.off == off), None)
        assert tok is not None, "%s r%02X no longer tiles at 0x%04X" % (rel, rid, off)
        assert tab.encoding(tok.idx).replace(" ", "") in ("1FA7", "1FA8")
        assert tok.size == size, (rel, rid, tok.size, size)
        # the list must end on the terminator, not stop short of it
        assert rec.data[tok.end - 2:tok.end] == bytes([0x04, 0xFF]), rel
        # ...and no span may start inside it any more
        assert not [s for s in rec.spans if off < s.off < tok.end], \
            "%s r%02X still extracts text from inside the list" % (rel, rid)


def test_the_tracer_records_which_exec_token_call_site_fired():
    """The wrapper is shared by three call sites; the record must say which.

    `0x4390F0` -- "run this script until it blocks" -- is reached from the
    per-tick background script AND from `0x42F334`.  A soft loop was analysed
    at length on the assumption it was the first, and that assumption was never
    checkable from a trace.  The wrapper's own return address distinguishes
    them, and it goes in flags bits 8-15, which were spare -- so this is not a
    format change and every older trace still decodes, with `site` None.
    """
    import re
    from giten.trace import core
    from giten.exe import tracer

    # the three sites and the return-address bytes they produce must agree
    want = {(s + 5) & 0xFF: s for s in tracer.CALL_SITES}
    assert core.CALL_SITE_BY_RETURN == want, (core.CALL_SITE_BY_RETURN, want)
    assert len(want) == 3, "two call sites share a low byte; the map is ambiguous"

    # the asm has to actually capture it
    with open(tracer.TRACE_SOURCE if hasattr(tracer, "TRACE_SOURCE")
              else os.path.join(os.path.dirname(tracer.__file__), "trace.S")) as fh:
        asm = fh.read()
    assert re.search(r"mov\s+eax,\s*dword ptr \[ebp\+4\]", asm), \
        "trace.S no longer reads its own return address"

    # and a decoded record has to expose it, with the old bits intact
    ev = core.Event(0, 0, 0, 0, 0, 0, 0, 0,
                    flags=((0x439103 + 5) & 0xFF) << 8 | core.CTX_NULL_BEFORE)
    assert ev.site == 0x439103
    assert ev.flags & core.CTX_NULL_BEFORE
    assert core.Event(0, 0, 0, 0, 0, 0, 0, 0, flags=0).site is None
