"""A translated row may never be lost: the per-file floor only rises.

The translation pass fits Sneik's v0.05 English (``ref_en``) into this version
"with nothing lost".  Nothing in the pipeline enforced the *nothing lost* half:
a row that once carried an ``en`` could quietly go back to empty -- a bad merge,
a re-extract that dropped a frame, a script that rewrote the wrong column -- and
no check would say a word, because an empty ``en`` is a legal row (it means "use
the source bytes") and ``missing`` is only a warning, one of 26,000.

So this test records a floor instead.  ``tests/data/tl-floor.json`` holds, per
game file, the number of rows that were *edited* (``en`` set and different from
``jp``) when the file was last committed, and the assertion is one-directional:
the current count must be greater than or equal to the recorded one.  Adding
translations is always allowed and never needs the file touched; losing one
fails.  Whoever commits a table regenerates the entry, which is the only way the
floor moves, and it only ever moves up.

The count is keyed on the game file (``row.file``), not on the table's path, so
a table that holds several game files -- ``p/_P_NAMES.tsv`` -- gets one floor per
file rather than one for the table.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import paths, tables  # noqa: E402

FLOOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                     "tl-floor.json")


def translated_counts(text_dir=None) -> "dict[str, int]":
    """``{game file: rows with an en that changes something}``."""
    counts: "dict[str, int]" = {}
    for path in tables.iter_tables(text_dir or paths.TEXT_DIR):
        for row in tables.read(path):
            counts[row.file] = counts.get(row.file, 0) + (1 if row.edited else 0)
    return counts


def read_floor() -> "dict[str, int]":
    with open(FLOOR, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_translation_floor_no_file_has_lost_a_row():
    floor = read_floor()
    now = translated_counts()
    lost = []
    for rel, want in sorted(floor.items()):
        have = now.get(rel)
        if have is None:
            lost.append("%s: table gone (floor %d)" % (rel, want))
        elif have < want:
            lost.append("%s: %d translated rows, floor is %d (%d lost)"
                        % (rel, have, want, want - have))
    assert not lost, (
        "the translation floor only rises -- these files went backwards:\n  "
        + "\n  ".join(lost))


def test_translation_floor_covers_every_file_with_a_table():
    """A file missing from the floor has no protection at all, so say so."""
    missing = sorted(set(translated_counts()) - set(read_floor()))
    assert not missing, (
        "no floor recorded for %d file(s), starting with %s -- regenerate "
        "tests/data/tl-floor.json" % (len(missing), ", ".join(missing[:5])))
