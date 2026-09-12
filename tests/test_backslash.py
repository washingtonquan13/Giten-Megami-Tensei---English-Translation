"""A literal backslash in ``en`` is an error (rulebook detector 24).

v0.05 cells carried a backslash where a newline belonged; the table escapes a
real backslash as two characters, so the cell is legal to every other rule and
four such rows were shipping as ``checked`` on 2026-09-12.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import check_v2, findings, tables  # noqa: E402

BS = chr(92)


def _findings(en):
    row = tables.Row("m/MS0000.BIN", "0:00", 0, 0, "1FD3", "はい", en, "", "ours",
                     "draft", "@tl:new")
    rep = findings.Report()
    check_v2.check_rows(rep, [row], pools=None)
    return [f.rule for f in rep.findings]


def test_a_literal_backslash_is_an_error():
    assert "backslash" in _findings("Yes." + BS + BS + "<wait>")


def test_an_escaped_newline_is_not():
    assert "backslash" not in _findings("Yes." + BS + "n<wait>")
