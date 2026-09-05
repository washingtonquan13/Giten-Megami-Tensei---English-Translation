"""The item database ``et/ET0001.BIN``: that we can take it apart and put it
back together byte-for-byte, and that the header lengths we take apart with are
the ones the engine actually uses.

The second test is the important one.  ``giten/itemdb.py``'s ``HEADER_LEN`` came
out of the decoder's jump table (``docs/format-notes.md`` section 6), which is a
claim about code.  Here it is re-derived from the *data*: for each type, the
lengths at which every record of that type tiles exactly as
``header + name\\0 + desc\\0`` with no control byte inside either string.  The
two derivations are independent, so agreement is evidence for both.
"""
from __future__ import annotations

import collections
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import container, itemdb, paths  # noqa: E402

REL = ("et", "ET0001.BIN")


def _body():
    raw = open(os.path.join(paths.ORIGINAL_DDSWIN, *REL), "rb").read()
    return container.split(raw)[0][0].body


def test_item_database_round_trips_byte_exactly():
    body = _body()
    recs = itemdb.parse(body)
    assert len(recs) == 745, len(recs)
    translatable = [r for r in recs if r.translatable]
    assert len(translatable) == 744, len(translatable)
    # the one that is not is the 7-byte type-0 dummy at index 0
    opaque = [r for r in recs if not r.translatable]
    assert [(r.index, r.type, len(r.raw)) for r in opaque] == [(0, 0, 7)], opaque

    rebuilt = itemdb.build(recs)
    assert rebuilt == body, "rebuild differs from the original body"

    # and the strings are the ones we expect to be able to reach
    names = sum(len(r.name) for r in translatable)
    descs = sum(len(r.desc) for r in translatable)
    assert (names, descs) == (9022, 31826), (names, descs)


def test_header_lengths_agree_with_the_data():
    body = _body()
    count = struct.unpack_from("<H", body, 0)[0]
    offs = list(struct.unpack_from("<%dH" % count, body, 2))

    def rec(i):
        return body[offs[i]:offs[i + 1] if i + 1 < count else len(body)]

    def tiles(r, h):
        if h >= len(r):
            return False
        p = r.find(b"\x00", h)
        if p < 0:
            return False
        if r.find(b"\x00", p + 1) != len(r) - 1:
            return False
        name, desc = r[h:p], r[p + 1:len(r) - 1]
        if not name or any(x < 0x20 for x in name) or any(x < 0x20 for x in desc):
            return False
        try:
            name.decode("cp932")
            desc.decode("cp932")
        except UnicodeDecodeError:
            return False
        return True

    by_type = collections.defaultdict(list)
    for i in range(count):
        r = rec(i)
        if len(r) >= 6:
            by_type[r[4]].append(i)

    not_minimal = []
    for t, h in sorted(itemdb.HEADER_LEN.items()):
        idxs = by_type.get(t)
        assert idxs, "type %d has no records" % t
        ok = [c for c in range(64) if all(tiles(rec(i), c) for i in idxs)]
        assert h in ok, "type %d: code says %d, data allows %s" % (t, h, ok)
        if h != min(ok):
            not_minimal.append(t)

    # For 18 of the 19 types the code's length is also the *shortest* one the
    # data permits, so the two derivations pin each other exactly.  Type 19 is
    # the exception: its header ends "...\xdeB", and both of those are printable
    # cp932, so lengths 14 and 15 also tile -- they just swallow "\xdeB" or "B"
    # into the front of every name ("\xdeBアミュレット", "Bアミュレット" instead of
    # "アミュレット").  The data cannot rule that out; the decoder can, which is
    # why HEADER_LEN comes from the jump table and not from a heuristic.
    assert not_minimal == [19], not_minimal


def test_wide_table_is_needed_for_english_and_round_trips():
    body = _body()
    recs = itemdb.parse(body)

    # the original fits in the u16 table; a doubled-length body does not
    fat = {r.index: (r.name, r.desc + r.desc) for r in recs if r.translatable}
    try:
        itemdb.build(recs, fat)
    except itemdb.ItemDbError as exc:
        assert "u16 offset table caps it" in str(exc), exc
    else:
        raise AssertionError("oversized body was accepted by the u16 builder")

    wide = itemdb.build(recs, fat, wide=True)
    assert len(wide) > itemdb.U16_CEILING

    # the wide table is u32 and still points at the right records
    count = struct.unpack_from("<H", wide, 0)[0]
    assert count == len(recs)
    offs = list(struct.unpack_from("<%dI" % count, wide, 2))
    assert offs[0] == 2 + count * 4
    assert all(offs[i] <= offs[i + 1] for i in range(len(offs) - 1))
    first = wide[offs[1]:offs[2]]
    assert first == recs[1].pack(*fat[1])


def _engine_view(blob):
    """What the patched engine sees: chain concatenated, u32 table, no mask."""
    cs, end = container.split(blob)
    assert end == len(blob), "the chain does not land on EOF"
    base = b"".join(c.body for c in cs)
    count = struct.unpack_from("<H", base, 0)[0]

    def locate(i):                       # 0x00422D10 + the patched 0x00422D2B
        if i >= count or i < 0:          # the engine's clamp
            i = 1
        return struct.unpack_from("<I", base, 2 + i * 4)[0]

    return base, count, locate


def test_every_record_is_readable_through_the_engines_own_path():
    """End to end: build the file, then read it back the way the engine does.

    The other tests check the builder and the patches separately.  This one
    walks the container chain like the loader, indexes the u32 table like the
    patched locate, adds the offset without a mask like our resolver, and
    splits the record with HEADER_LEN -- then asserts every one of the 744
    records yields exactly the strings the table asked for.
    """
    recs = itemdb.parse(itemdb.source_body(paths.ORIGINAL_DDSWIN))
    table = os.path.join(paths.REPO_ROOT, "tables", "itemdb.tsv")
    strings, findings = itemdb.strings_from_table(table, recs)
    assert not findings, findings

    blob = itemdb.pack_file(recs, strings)
    base, count, locate = _engine_view(blob)
    assert count == len(recs)

    checked = 0
    for rec in recs:
        if not rec.translatable:
            continue
        off = locate(rec.index)
        rest = base[off + itemdb.HEADER_LEN[rec.type]:]
        p = rest.index(b"\x00")
        q = rest.index(b"\x00", p + 1)
        want_name, want_desc = strings.get(rec.index, (rec.name, rec.desc))
        assert rest[:p] == want_name, (rec.index, rest[:p], want_name)
        assert rest[p + 1:q] == want_desc, (rec.index, rest[p + 1:q], want_desc)
        checked += 1
    assert checked == 744, checked


def test_records_really_do_live_past_the_old_64k_ceiling():
    """If nothing sits above 0xFFFF the widening is untested by accident."""
    recs = itemdb.parse(itemdb.source_body(paths.ORIGINAL_DDSWIN))
    strings, _ = itemdb.strings_from_table(
        os.path.join(paths.REPO_ROOT, "tables", "itemdb.tsv"), recs)
    base, count, locate = _engine_view(itemdb.pack_file(recs, strings))

    above = [i for i in range(count) if locate(i) > 0xFFFF]
    assert above, "no record is past 0xFFFF -- the u32 table is not being exercised"

    # and the stock u16 load really would land somewhere else entirely
    i = above[0]
    stock = struct.unpack_from("<H", base, 2 + i * 2)[0]
    assert stock != locate(i)


def test_the_u16_builder_refuses_the_current_table_instead_of_truncating():
    """The English no longer fits the original format; that must be an error."""
    recs = itemdb.parse(itemdb.source_body(paths.ORIGINAL_DDSWIN))
    strings, _ = itemdb.strings_from_table(
        os.path.join(paths.REPO_ROOT, "tables", "itemdb.tsv"), recs)
    try:
        itemdb.build(recs, strings)          # wide=False, the original format
    except itemdb.ItemDbError as exc:
        assert "u16 offset table caps it" in str(exc), exc
    else:
        raise AssertionError("a body past 65,535 was accepted by the u16 builder")


def test_table_escaping_survives_a_round_trip():
    """A tab or a backslash in a name must not corrupt the TSV."""
    import tempfile

    recs = itemdb.parse(itemdb.source_body(paths.ORIGINAL_DDSWIN))
    nasty = {1: ("back\slash", "tab\there and a newline\nthere"),
             2: ("trailing space ", "")}
    tmp = os.path.join(tempfile.mkdtemp(), "t.tsv")
    itemdb.write_table(tmp, recs, {i: (n, d, "draft", "") for i, (n, d) in nasty.items()})
    back = itemdb.read_table(tmp)
    for i, (n, d) in nasty.items():
        assert back[i][0] == n, (i, back[i][0], n)
        assert back[i][1] == d, (i, back[i][1], d)
    # every row still has its eight columns
    for ln in open(tmp, encoding="utf-8"):
        if not ln.startswith("#") and ln.strip():
            assert len(ln.rstrip("\n").split("\t")) == 8, ln
