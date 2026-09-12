"""No shipped English may call a pool record its Japanese span does not.

Found on 2026-09-11 from a play session: the shop line ``m/MS010A`` 0:06[1]
drew ``Saver V襲いかかっ, huh.`` -- the pool word 襲いかかっ ("attacked") in the
middle of an English sentence.  The overlay had served exactly the bytes the
table held: the v0.05 reference English was ``{03:07}, huh. This should do
it, right?``, and ``{03:07}`` is a real pool call.  It got there because v0.05
tokenised ``1F 01`` shorter than the engine does, so the operand bytes that
follow it (``03 07``) were read as a pool call and carried into the English.
Served, that English really does call the pool.

``giten check`` already reports this for ``en`` (the ``tokens`` rule) and the
tables carried none; the draft tree, which is what ships, promoted four such
references anyway.  ``tools/make_draft_tree.py`` now refuses them, and this
pins both trees.
"""
from __future__ import annotations

import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import paths, tables  # noqa: E402

CALL = re.compile(r"\{0([1-8]):([0-9A-Fa-f]{2})\}")
TABLES = os.path.join(paths.REPO_ROOT, "tables")
DRAFT = os.path.join(paths.REPO_ROOT, "build", "tables_draft")


def _calls(text):
    return collections.Counter(m.group(0).upper() for m in CALL.finditer(text or ""))


def _offenders(tree):
    out = []
    for path in tables.iter_tables(tree):
        for r in tables.read(path):
            if not r.en or r.en == r.jp:
                continue
            extra = _calls(r.en) - _calls(r.jp)
            if extra:
                out.append((r.file, r.rec, r.idx, sorted(extra)))
    return out


def test_no_english_in_the_tables_calls_a_pool_record_its_japanese_lacks():
    assert _offenders(TABLES) == []


def test_no_english_in_the_draft_tree_calls_a_pool_record_its_japanese_lacks():
    """The draft tree is what the install is built from, so the rule has to
    hold there too -- and it did not, until make_draft_tree refused the four
    references that carried one."""
    if not os.path.isdir(DRAFT):
        return
    assert _offenders(DRAFT) == []


def test_the_shop_line_that_drew_the_pool_word_is_written_from_the_japanese():
    row = next(r for r in tables.read(os.path.join(TABLES, "m", "MS010A.BIN.tsv"))
               if r.rec == "0:06" and r.idx == 1)
    assert row.en == ", huh. This should do it, right?\\n", row.en
    assert "{03:07}" not in row.en
    assert "@pool-call-dropped" in row.note
