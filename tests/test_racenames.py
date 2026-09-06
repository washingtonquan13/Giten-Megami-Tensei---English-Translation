"""The race / lineage / title tables in et/ET0000.BIN.

The whole safety argument for rebuilding a data file instead of hooking the exe
is that the containers are self-sizing, so the tests that matter are: the
tables round-trip byte-exact when nothing is translated, the container count
and the binary containers survive, every container stays under the 16-bit
ceiling the accessor's mask imposes, and -- the adversarial one -- resolving a
name the way the *accessor* does gives back the English we put in.
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import container, racenames  # noqa: E402


def test_identity_rebuild_is_byte_exact():
    raw = racenames.source()
    assert racenames.build(raw, {}) == raw


def test_the_binary_containers_and_the_count_survive_translation():
    raw = racenames.source()
    out = racenames.build(raw, racenames.read_table())
    before, after = container.split(raw)[0], container.split(out)[0]
    assert len(after) == racenames.CONTAINERS == len(before)
    # containers 0 and 1 are binary; 1 is the race -> group map, and its length
    # must still equal the number of races or the mapping silently shifts
    for i in (0, 1):
        assert after[i].body == before[i].body, i
    assert len(after[1].body) == len(racenames.split_table(after[2].body))


def test_every_container_stays_under_the_accessors_16_bit_mask():
    out = racenames.build(racenames.source(), racenames.read_table())
    for i, c in enumerate(container.split(out)[0]):
        assert len(c.body) <= racenames.CONTAINER_MAX, (i, len(c.body))


def test_reading_a_name_back_the_way_the_accessor_does():
    """0x00410180: base + (u16 at base+2+index*2), masked to 16 bits."""
    english = racenames.read_table()
    assert english, "tables/racenames.tsv has no English"
    out = racenames.build(racenames.source(), english)
    cs = container.split(out)[0]
    checked = 0
    for ci, kind in sorted(racenames.KINDS.items()):
        body = cs[ci].body
        count = struct.unpack_from("<H", body, 0)[0]
        for idx in range(count):
            off = struct.unpack_from("<H", body, 2 + idx * 2)[0] & 0xFFFF
            got = body[off:body.index(b"\x00", off)].decode("cp932")
            assert got == english[(kind, idx)], (kind, idx, got)
            checked += 1
    assert checked == 97, checked


def test_human_is_still_where_the_reference_table_says():
    """The status screen's Race line for the protagonist: race 33 = 人."""
    tables = racenames.parse(racenames.source())
    assert tables[2][33] == "人"
    assert racenames.read_table()[("race", 33)] == "Human"
    assert tables[4][0] == "愚者"
    assert racenames.read_table()[("title", 0)] == "Fool"


def test_names_that_would_not_fit_or_encode_are_refused():
    raw = racenames.source()
    _rows, findings = racenames.plan(raw, {("title", 0): "A" * (racenames.BUDGET[4] + 1)})
    assert findings and "the field draws" in findings[0][2]

    _rows, findings = racenames.plan(raw, {("title", 0): "café naïve"})
    assert findings, "a non-cp932 name was accepted"

    _rows, findings = racenames.plan(raw, {("title", 0): "Fool"})
    assert not findings


def test_a_container_that_outgrew_the_u16_offsets_is_refused():
    try:
        racenames.join_table(["x" * 1000] * 100)
    except racenames.RaceNameError as exc:
        assert "u16 offsets stop at" in str(exc), exc
    else:
        raise AssertionError("a 100 KB container was accepted")


def test_split_and_join_are_inverses():
    for strings in racenames.parse(racenames.source()).values():
        assert racenames.split_table(racenames.join_table(strings)) == strings
