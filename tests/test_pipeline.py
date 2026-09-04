"""Tests for the Giten translation pipeline.

Runnable two ways::

    python -m tests.run          # no dependencies
    python -m pytest tests       # if pytest happens to be installed

Everything reads the game folder read-only; nothing here writes outside a
temporary directory.
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.giten import (build, check, container, dictionary, extract, files,
                         framing, spans, tables, tokens)


# --------------------------------------------------------------------------
# container
# --------------------------------------------------------------------------
def test_xor_roundtrip_all_files():
    """unxor/enxor and unpack/pack are byte-exact on every encoded file."""
    n = 0
    for rel in files.all_encoded():
        raw = files.read_source(rel)
        hdr, body = container.unpack(raw)
        assert container.pack(body, hdr) == raw, rel
        assert container.unxor(container.enxor(body)) == body, rel
        n += 1
    assert n == 844, "expected 844 encoded files, found %d" % n


def test_xor_is_self_inverse_on_synthetic_data():
    for payload in (b"", b"\x00", b"\xff" * 33, bytes(range(256))):
        assert container.unxor(container.enxor(payload)) == payload


def test_recompute_header_policy():
    # hdr == len(body): follow the new length.
    assert container.recompute_header("m/X.BIN", 10, b"a" * 10, b"a" * 12) == 12
    # hdr means something else: leave it alone.
    assert container.recompute_header("m/MS6007.BIN", 274, b"a" * 10, b"a" * 12) == 274


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------
def test_token_codec_roundtrip():
    cases = [
        b"Hello",
        b"Hello\x0aworld",
        b"Hi\x1e\x10\x01\x01",
        "こんにちは".encode("cp932"),
        b"\x01\x03" + "：".encode("cp932"),
        b"a{b}<c>\\d",
    ]
    for raw in cases:
        text = tokens.render(raw, None)
        assert tokens.encode(text, allow_dict_refs=True) == raw, (raw, text)


def test_token_escapes():
    assert tokens.render(b"{", None) == "\\{"
    assert tokens.render(b"<", None) == "\\<"
    assert tokens.render(b"\\", None) == "\\\\"
    assert tokens.encode("\\{\\<\\\\") == b"{<\\"
    assert tokens.render(b"\x0a", None) == "\\n"
    assert tokens.encode("\\n") == b"\x0a"
    assert tokens.render(tokens.WAIT_BYTES, None) == "<wait>"
    assert tokens.encode("<wait>") == tokens.WAIT_BYTES
    assert tokens.render(b"\x02", None) == "{02}"
    assert tokens.encode("{02}") == b"\x02"


def test_encode_rejects_bad_input():
    for bad in ("{DICT:41}", "a { b", "a < b", "trailing\\", "\\q"):
        try:
            tokens.encode(bad)
        except tokens.SpanEncodeError:
            continue
        raise AssertionError("encode accepted %r" % bad)
    try:
        tokens.encode("éЖ")          # Cyrillic Zh is not in cp932
    except tokens.SpanEncodeError:
        pass
    else:
        raise AssertionError("encode accepted a non-cp932 character")


def test_sjis_trail_bytes_are_not_read_as_controls():
    """A kanji whose trail byte looks like a control code stays one character.

    This is the bug the span detector has to avoid: cp932 trail bytes run
    0x40..0xFC, so the second half of a two-byte character can be any ASCII
    value.  Here 0x8F5B decodes to a single kanji even though 0x5B is '['.
    """
    raw = b"\x8f\x5b"
    assert tokens.render(raw, None) == raw.decode("cp932")
    assert len(tokens.render(raw, None)) == 1


def test_display_width_and_lines():
    assert tokens.display_width("abc") == 3
    assert tokens.display_width("会話") == 4
    assert tokens.display_width("{02}ab") == 2
    assert tokens.lines_of("a\\nb<wait>c") == ["a", "b", "c"]
    assert tokens.lines_of("a\\\\nb") == ["a\\\\nb"]   # escaped backslash, not a newline


def test_control_token_helpers():
    assert tokens.control_tokens("x{02}y{0B}z") == ["{02}", "{0B}"]
    assert tokens.control_tokens("{DICT:41}a") == ["{DICT:41}"]
    assert tokens.has_japanese("会話")
    assert not tokens.has_japanese("Sonoda: hello {02}")


# --------------------------------------------------------------------------
# dictionary
# --------------------------------------------------------------------------
def test_dictionary_loads_and_expands():
    dic = dictionary.load()
    assert len(dic) >= 140, "expected ~145 dictionary entries, got %d" % len(dic)
    # Every entry must render to something.
    for idx, raw in dic.items():
        assert tokens.render(raw, dic) != "" or raw == b""
    # 08 nn expands in place, and the expansion is the entry's own text.
    idx, raw = sorted(dic.items())[0]
    expanded = tokens.render(bytes([0x08, idx]), dic)
    assert expanded == tokens.render(raw, dic)
    # Without a dictionary the reference is preserved as a token.
    assert tokens.render(bytes([0x08, idx]), None) == "{DICT:%02X}" % idx


def test_no_dictionary_reference_survives_extraction():
    """Extracted `jp` must be fully expanded wherever the entry exists."""
    dic = dictionary.load()
    rel = "m/MS6007.BIN"
    rows = extract.rows_for(rel, files.read_source(rel), dic)
    assert rows, "MS6007 should yield negotiation lines"
    unresolved = [r for r in rows if "{DICT:" in r.jp]
    assert not unresolved, unresolved[:3]
    assert any("である" in r.jp or "御主" in r.jp or len(r.jp) > 8 for r in rows)


# --------------------------------------------------------------------------
# framing / spans
# --------------------------------------------------------------------------
def test_frames_tile_the_body():
    for rel in ("m/MS0000.BIN", "m/MS6007.BIN", "m/MS7F06.BIN", "et/ID0099.BIN",
                "m/MS6F00.BIN", "p/P2000.BIN"):
        _hdr, body = container.unpack(files.read_source(rel))
        frames = framing.parse(rel, body)
        cursor = 0
        for fr in frames:
            assert fr.data_start >= cursor, rel
            cursor = fr.data_end
        assert frames[0].data_start == 0, rel
        assert frames[-1].data_end == len(body), rel
        keys = [f.key for f in frames]
        assert len(keys) == len(set(keys)), "frame keys must be unique in " + rel


def test_record_pool_lengths_are_consistent():
    _hdr, body = container.unpack(files.read_source("m/MS7F06.BIN"))
    frames = framing.parse("m/MS7F06.BIN", body)
    recs = [f for f in frames if f.kind == "record"]
    assert len(recs) > 100
    for fr in recs:
        stored = int.from_bytes(body[fr.len_off:fr.len_off + 2], "little")
        assert stored == fr.data_end - fr.data_start
        assert body[fr.data_end - 1] == 0          # payload ends with the terminator


def test_binary_tables_yield_no_spans():
    """MS6F00 / MS6300 / MS6400 are lookup tables; they must stay untouched."""
    dic = dictionary.load()
    for rel in ("m/MS6F00.BIN", "m/MS6300.BIN", "m/MS6400.BIN"):
        _hdr, body = container.unpack(files.read_source(rel))
        _frames, found = spans.scan(rel, body, dic)
        assert found == [], "%s produced %d spans" % (rel, len(found))
        assert not os.path.exists(files.table_path(rel)) or \
            not tables.read_for(rel, files.table_path(rel))


def test_dictionary_file_is_not_extracted():
    assert "m/MS7F07.BIN" in files.EXCLUDE_FROM_TEXT


def test_spans_do_not_overlap_and_stay_in_bounds():
    dic = dictionary.load()
    for rel in ("m/MS0000.BIN", "m/MS6007.BIN", "et/ID0099.BIN", "m/MS0003.BIN"):
        _hdr, body = container.unpack(files.read_source(rel))
        _frames, found = spans.scan(rel, body, dic)
        last = -1
        for sp in found:
            assert 0 <= sp.start < sp.end <= len(body), rel
            assert sp.start >= last, "%s: spans overlap at %d" % (rel, sp.start)
            last = sp.end
            # A span must be exactly what the text grammar reaches from its
            # start.  Note 0x00 and 0x1F *can* occur inside a span, as the
            # operand byte of an 08 nn dictionary macro (53 spans in the corpus
            # contain an 08 00), which is why this is a grammar check and not a
            # "no control bytes present" check.
            assert spans._span_end(body, sp.start, len(body)) >= sp.end, rel


def test_known_lines_are_found():
    dic = dictionary.load()
    _hdr, body = container.unpack(files.read_source("m/MS0000.BIN"))
    _frames, found = spans.scan("m/MS0000.BIN", body, dic)
    texts = [spans.span_text(body, s, dic) for s in found]
    assert "There's no one here...\\n<wait>" in texts
    assert "Yamase:" in texts
    tags = {s.tag for s in found}
    assert {"1FD0", "1FD2", "1FD3"} <= tags


def test_choice_options_are_found():
    dic = dictionary.load()
    _hdr, body = container.unpack(files.read_source("et/ID0099.BIN"))
    _frames, found = spans.scan("et/ID0099.BIN", body, dic)
    choices = [spans.span_text(body, s, dic) for s in found if s.tag == "1FB2"]
    assert "宝石" in choices and "他の物" in choices


def test_pname_span():
    _hdr, body = container.unpack(files.read_source("p/P2000.BIN"))
    _frames, found = spans.scan("p/P2000.BIN", body, dictionary.load())
    assert len(found) == 1 and found[0].tag == "NAME"
    assert found[0].fixed_len == spans.PNAME_LEN
    assert spans.span_text(body, found[0], None) == "Souma Yukihito"


# --------------------------------------------------------------------------
# build: identity and synthetic edits
# --------------------------------------------------------------------------
def test_identity_build_is_byte_exact():
    dic = dictionary.load()
    n = 0
    for rel in files.all_encoded():
        raw = files.read_source(rel)
        res = build.build_file(rel, raw, dic, {})
        assert res.raw == raw, "%s: identity build differs" % rel
        n += 1
    assert n == 844


def _rebuild(rel, edits):
    """Rebuild ``rel`` with ``{(rec, idx): english}`` substituted."""
    dic = dictionary.load()
    raw = files.read_source(rel)
    hdr, body = container.unpack(raw)
    frames, found = spans.scan(rel, body, dic)
    rowmap = {}
    for sp in found:
        key = (sp.rec, sp.idx)
        if key in edits:
            jp = spans.span_text(body, sp, dic)
            rowmap[key] = tables.Row(rel, sp.rec, sp.idx, sp.off, sp.tag,
                                     jp, edits[key])
    res = build.build_file(rel, raw, dic, rowmap)
    return body, frames, found, res


def test_lengthening_a_record_updates_len_and_keeps_tags_intact():
    """The core resize test, on a real record pool.

    Replace one negotiation line with a much longer English one and assert that
    (1) the record's stored length tracks the new payload, (2) the record still
    ends with its 0x00 terminator, (3) the record header and the neighbouring
    records are untouched, and (4) nothing outside the record moved in content.
    """
    rel = "m/MS6007.BIN"
    dic = dictionary.load()
    _hdr, body = container.unpack(files.read_source(rel))
    frames, found = spans.scan(rel, body, dic)
    recs = [f for f in frames if f.kind == "record"]
    assert recs

    # Pick a span that lives at the start of a record payload.
    target = next(s for s in found
                  if s.tag == spans.DATA_TAG and s.start == frames[s.frame_index].data_start)
    fr = frames[target.frame_index]
    old_payload = fr.data_end - fr.data_start
    new_text = "A considerably longer English replacement line.\\n<wait>"
    delta = len(tokens.encode(new_text)) - (target.end - target.start)
    assert delta > 0, "the test needs the replacement to be longer"

    _b, _f, _s, res = _rebuild(rel, {(target.rec, target.idx): new_text})
    assert res.changed == 1 and res.size_delta == delta
    assert res.unframed_resize == 0, "a record frame must absorb the resize"

    new_hdr, new_body = container.unpack(res.raw)
    assert len(new_body) == len(body) + delta

    # (1) stored length updated, (2) terminator still last byte of the record
    new_frames = framing.parse(rel, new_body)
    stored = int.from_bytes(new_body[fr.len_off:fr.len_off + 2], "little")
    assert stored == old_payload + delta
    assert new_body[fr.data_start + stored - 1] == 0

    # (3) the record id byte is unchanged; only the two length bytes moved
    assert new_body[fr.len_off - 1] == body[fr.len_off - 1]

    # (4) everything before the length field and everything after the record is
    #     byte-identical -- the edit is contained
    assert new_body[:fr.len_off] == body[:fr.len_off]
    assert new_body[fr.len_off + 2:fr.data_start] == body[fr.len_off + 2:fr.data_start]
    assert new_body[fr.data_start + stored:] == body[fr.data_end:]

    # (5) the file still parses into the same number of records, and re-reading
    #     the edited record gives back the English we asked for.
    assert len([f for f in new_frames if f.kind == "record"]) == len(recs)
    _nf, new_spans = spans.scan(rel, new_body, dic)
    edited = next(s for s in new_spans if s.start == target.start)
    assert spans.span_text(new_body, edited, dic) == new_text


def test_shortening_a_record_updates_len():
    rel = "m/MS7F06.BIN"
    dic = dictionary.load()
    _hdr, body = container.unpack(files.read_source(rel))
    frames, found = spans.scan(rel, body, dic)
    target = next(s for s in found if (s.end - s.start) > 8)
    fr = frames[target.frame_index]
    old = fr.data_end - fr.data_start
    _b, _f, _s, res = _rebuild(rel, {(target.rec, target.idx): "Hi"})
    _h, new_body = container.unpack(res.raw)
    stored = int.from_bytes(new_body[fr.len_off:fr.len_off + 2], "little")
    assert stored == old + res.size_delta
    assert res.size_delta < 0
    assert new_body[fr.data_start + stored - 1] == 0


def test_edit_in_a_flat_file_is_reported_as_unframed():
    """An event script has no known length field: the resize must be flagged."""
    rel = "m/MS0000.BIN"
    dic = dictionary.load()
    _hdr, body = container.unpack(files.read_source(rel))
    frames, found = spans.scan(rel, body, dic)
    assert all(f.len_off is None for f in frames)
    target = found[0]
    _b, _f, _s, res = _rebuild(rel, {(target.rec, target.idx): "Much longer replacement text here."})
    assert res.changed == 1
    assert res.unframed_resize == 1


def test_same_length_edit_touches_only_the_span():
    rel = "m/MS0000.BIN"
    dic = dictionary.load()
    _hdr, body = container.unpack(files.read_source(rel))
    _frames, found = spans.scan(rel, body, dic)
    target = next(s for s in found if s.tag == "1FD2" and s.end - s.start == 7)
    replacement = "Abcdefg"
    _b, _f, _s, res = _rebuild(rel, {(target.rec, target.idx): replacement})
    _h, new_body = container.unpack(res.raw)
    assert len(new_body) == len(body)
    assert new_body[target.start:target.end] == replacement.encode("cp932")
    assert new_body[:target.start] == body[:target.start]
    assert new_body[target.end:] == body[target.end:]
    # the 1F D2 tag immediately before the span survived
    assert new_body[target.start - 2:target.start] == b"\x1f\xd2"


def test_pname_is_padded_and_bounded():
    rel = "p/P2000.BIN"
    _b, _f, _s, res = _rebuild(rel, {("F0", 0): "Bob"})
    _h, new_body = container.unpack(res.raw)
    assert len(new_body) == len(_b)
    field = new_body[spans.PNAME_OFF:spans.PNAME_OFF + spans.PNAME_LEN]
    assert field == b"Bob" + b"\x00" * (spans.PNAME_LEN - 3)
    # too long: refused, and the source bytes are kept
    _b2, _f2, _s2, res2 = _rebuild(rel, {("F0", 0): "X" * 20})
    assert res2.errors and res2.changed == 0


def test_dictionary_reference_in_english_is_refused():
    rel = "m/MS6007.BIN"
    dic = dictionary.load()
    _hdr, body = container.unpack(files.read_source(rel))
    _frames, found = spans.scan(rel, body, dic)
    t = found[0]
    _b, _f, _s, res = _rebuild(rel, {(t.rec, t.idx): "text {DICT:41} here"})
    assert res.errors and "dictionary reference" in res.errors[0]
    assert res.changed == 0


# --------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------
def test_table_roundtrip():
    rows = [
        tables.Row("m/X.BIN", "F0", 0, 7, "1FD3", "a\\nb<wait>", "c{02}d", "note"),
        tables.Row("m/X.BIN", "R1:AA", 1, 9, "DATA", "会話", "", ""),
    ]
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "sub", "X.tsv")
        tables.write(p, rows)
        back = tables.read(p)
    assert [r.key for r in back] == [r.key for r in rows]
    assert [(r.jp, r.en, r.note) for r in back] == [(r.jp, r.en, r.note) for r in rows]
    assert back[0].edited and not back[1].edited


def test_row_edited_semantics():
    r = tables.Row("f", "F0", 0, 0, "1FD3", "hello", "hello")
    assert not r.edited, "en == jp is a no-op, not an edit"
    r.en = "hi"
    assert r.edited


def test_extraction_is_stable_and_merges():
    """Re-extracting keeps a translator's `en` and never changes the row keys."""
    dic = dictionary.load()
    rel = "et/ID0099.BIN"
    a = extract.rows_for(rel, files.read_source(rel), dic)
    b = extract.rows_for(rel, files.read_source(rel), dic)
    assert [r.key for r in a] == [r.key for r in b]
    assert [(r.jp, r.tag, r.off) for r in a] == [(r.jp, r.tag, r.off) for r in b]
    assert len({r.key for r in a}) == len(a), "row keys must be unique"

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.tsv")
        a[0].en = "Gems"
        tables.write(p, a)
        reread = tables.read(p)
        assert reread[0].en == "Gems"


def test_prefilled_english_rows_are_noops():
    """Every row the extractor pre-fills must rebuild to the original bytes."""
    dic = dictionary.load()
    for rel in ("m/MS0000.BIN", "m/MS0003.BIN", "p/P2000.BIN"):
        raw = files.read_source(rel)
        rows = extract.rows_for(rel, raw, dic)
        rowmap = {(r.rec, r.idx): r for r in rows}
        res = build.build_file(rel, raw, dic, rowmap)
        assert res.changed == 0, rel
        assert res.raw == raw, rel


# --------------------------------------------------------------------------
# validators
# --------------------------------------------------------------------------
def _row(jp, en, tag="1FD3", note=""):
    return tables.Row("m/X.BIN", "F0", 0, 0, tag, jp, en, note)


def _rules(rows, **kw):
    rep = check.Report()
    check.check_rows(rep, rows, **kw)
    return {f.rule for f in rep.findings}, rep


def test_validator_missing():
    rules, _ = _rules([_row("会話", "")])
    assert rules == {"missing"}
    rules, _ = _rules([_row("会話", "", note="@keep not shown in game")])
    assert rules == set()


def test_validator_dict_and_cp932():
    rules, _ = _rules([_row("会話", "hello {DICT:41}")])
    assert "dict" in rules
    # Cyrillic and circled digits *are* in cp932; the euro sign is not.
    rules, _ = _rules([_row("会話", "5€")])
    assert "cp932" in rules


def test_validator_format_specifiers():
    rules, _ = _rules([_row("%d会", "no specifier here")])
    assert "format" in rules
    rules, _ = _rules([_row("%5d and %-16.16s", "%5d and %-16.16s ok")])
    assert "format" not in rules


def test_validator_control_tokens():
    rules, _ = _rules([_row("{02}{0B}会", "dropped the inserts")])
    assert "tokens" in rules
    rules, _ = _rules([_row("{02}{0B}会", "{0B}{02} wrong order")])
    assert "tokens" in rules
    rules, _ = _rules([_row("{02}{0B}会", "{02} kept {0B} both")])
    assert "tokens" not in rules


def test_validator_width():
    # jp is 4 half-width units wide, so the budget at scale 1.0 is 4.
    rules, _ = _rules([_row("会話", "much too long for the box")])
    assert "width" in rules
    rules, _ = _rules([_row("会話", "四文字です")])
    assert "width" in rules
    rules, _ = _rules([_row("会話", "abcd")])
    assert "width" not in rules
    # choice options get their own rule name
    rules, _ = _rules([_row("会話", "far too long", tag="1FB2")])
    assert "width-choice" in rules
    # ... and the budget scales
    rules, _ = _rules([_row("会話", "abcdefgh")], width_scale=2.0)
    assert "width" not in rules
    # a hard cap overrides a generous budget
    rules, _ = _rules([_row("会話会話", "abcdefgh")],
                      max_line_width=4)
    assert "width" in rules


def test_validator_width_is_per_line():
    rules, _ = _rules([_row("会話", "ab\\ncd")])
    assert "width" not in rules, "each line is measured separately"


def test_validator_pname_length():
    rules, _ = _rules([_row("Souma", "X" * 16, tag=spans.PNAME_TAG)])
    assert "pname" in rules
    rules, _ = _rules([_row("Souma", "X" * 15, tag=spans.PNAME_TAG)])
    assert "pname" not in rules


def test_validator_identity_rule_passes_on_the_shipped_game():
    rep = check.Report()
    check.check_identity(rep)
    assert not rep.errors, rep.errors[:5]
    assert rep.counts["identity_files"] == 844
