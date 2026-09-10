"""The district-name table, ``et/ET000D.BIN`` container 1.

The location strip was 60% and 92% of the Japanese still reaching the screen in
two recorded sessions (``docs/screen-audit.md``), so this file is the one that
turns that number off.  The tests pin what the extractor is allowed to assume.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import container, districts  # noqa: E402


def _raw():
    return districts.source()


def test_the_identity_build_is_byte_exact():
    raw = _raw()
    assert districts.build(raw, {}) == raw


def test_the_file_has_the_two_containers_the_loader_reads():
    """0x00412020 calls 0x00401C30 exactly twice; a third would be ignored."""
    cs = container.split(_raw())[0]
    assert len(cs) == districts.CONTAINERS == 2


def test_container_zero_is_carried_through_untouched():
    """It is the map -> district lookup, binary, and nothing here understands it."""
    raw = _raw()
    before = container.split(raw)[0][0].body
    after = container.split(districts.build(raw, {0: "Nagasaki"}))[0][0].body
    assert before == after


def test_the_string_table_is_the_shape_the_accessor_reads():
    """u16 count; u16 offset[count]; strings -- offset[0] lands past the table."""
    names = districts.parse(_raw())
    assert len(names) == 221
    assert names[52] == "新宿"          # 新宿, the one everybody sees


def test_english_survives_a_round_trip():
    raw = _raw()
    want = {1: "Nagasaki", 52: "Shinjuku", 220: "Hibiya Park"}
    names = districts.parse(districts.build(raw, want))
    for i, s in want.items():
        assert names[i] == s
    # and an untranslated row keeps its Japanese
    assert names[0] == districts.parse(raw)[0]


def test_an_over_budget_name_is_refused_not_truncated():
    raw = _raw()
    _names, findings = districts.plan(raw, {1: "A" * (districts.BUDGET + 1)})
    assert findings and "cells" in findings[0][1]


def test_a_name_that_is_not_cp932_is_refused():
    raw = _raw()
    _names, findings = districts.plan(raw, {1: "Naɡasaki"})   # latin small script g
    assert findings and "cp932" in findings[0][1]


def test_the_shipped_table_builds_and_every_name_fits():
    """The real tables/districts.tsv, not a fixture."""
    raw = _raw()
    english = districts.read_table()
    assert len(english) >= 200, "the district table is empty; run `giten districts --extract`"
    names, findings = districts.plan(raw, english)
    assert not findings, findings[:3]
    for s in names:
        assert districts.cells(s) <= districts.BUDGET
    blob = districts.build(raw, english)
    assert districts.parse(blob)[52] == english[52]
