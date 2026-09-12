"""``checked``: a writer read Sneik's line against the Japanese and kept it.

Before this status existed the validator said "en equals ref_en; mark it
reviewed or change it", and ``reviewed`` is the project owner's word alone.  A
writer who found the inherited line correct therefore had no honest option and
reworded 156 good lines of m/MS003B to get past the rule (2026-09-11).  That is
the one loss the translation pass exists to prevent, so the rule now has a
third answer.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import check_v2, findings, tables  # noqa: E402


def _row(en, ref_en, status):
    return tables.Row("m/MS0000.BIN", "0:00", 0, 0, "1FD3", "はい", en, ref_en,
                      "v005", status, "")


def _status_findings(row):
    rep = findings.Report()
    check_v2.check_rows(rep, [row], pools=None)
    return [f for f in rep.findings if f.rule == "status"]


def test_a_kept_line_marked_checked_is_not_an_error():
    assert _status_findings(_row("Yes.", "Yes.", "checked")) == []


def test_a_kept_line_marked_draft_is_still_an_error():
    assert _status_findings(_row("Yes.", "Yes.", "draft"))


def test_a_changed_line_marked_draft_is_fine():
    assert _status_findings(_row("Yeah.", "Yes.", "draft")) == []


def test_reviewed_still_covers_a_kept_line():
    assert _status_findings(_row("Yes.", "Yes.", "reviewed")) == []


def test_a_changed_line_cannot_be_marked_checked():
    """`checked` means kept verbatim.  A reviewer found 22 reworded rows carrying
    it in one file (m/MS003D, 2026-09-12); the rule above could not see that
    direction."""
    assert _status_findings(_row("Yeah.", "Yes.", "checked"))


def test_a_line_with_no_reference_cannot_be_marked_checked():
    assert _status_findings(_row("Yes.", "", "checked"))
