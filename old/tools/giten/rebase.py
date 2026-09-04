"""``rebase``: carry translations from the v0.05-based tables onto tables
extracted from the Japanese original.

Why a separate tool from :mod:`.migrate`
----------------------------------------
``migrate`` was built for ``text -> text_v2``, two extractions of the *same*
game files, and its strongest key is the raw byte offset of a span.  A rebase
is different in kind: ``text_v2`` was extracted from Sneikkimies' v0.05 patch
and ``text_v3`` from the untouched original, so the same span lives at a
different offset in a file of a different length, and for 30 000 rows the v2
``jp`` column is not Japanese at all but his English.  Byte offsets mean
nothing across that gap; only the *position* of a span in its record does.

How rows are paired
-------------------
Not by span index.  v0.05 stripped ~3 200 ``1F01 nn``/``00`` idioms from the
original, and wherever one sat before a span, every later span in that record
moved down by one: v2 span *n* is a speaker name where v3 span *n* is the
speech line under it.  Measured, that misaligns a quarter of all rows.

A span's tag is the opcode that precedes it, so a record's tag sequence is a
fingerprint of its structure.  The two fingerprints are diffed
(:class:`difflib.SequenceMatcher`, no junk heuristic) and rows are paired inside
each equal block.  A *replace* block of equal length is paired too and marked
``@rebase-tagdiff`` -- that is the ``1F01`` case, the same span under a
different opener -- so it stays reviewable.  Anything else is unmatched.

What is carried, and from where
-------------------------------
For each paired row, in order:

* our own translation (v2 ``en`` set and different from v2 ``jp``) is carried
  and marked ``@from-ours``;
* otherwise, if v2 ``jp`` is English -- meaning v0.05 had translated that span
  and we left it -- that English is carried as the translation and marked
  ``@from-v005``.  For the first time it sits beside the real Japanese, so it
  can be reviewed.
* otherwise the row stays untranslated.

Nothing is guessed across a mismatch.  A v2 row whose tag differs, or that has
no v3 counterpart, is reported and -- when it held one of our translations --
that translation is kept verbatim in the v3 note as ``@rebase-unmatched``, so a
person can re-anchor it with the text in front of them.  Rows the original has
that v0.05 did not are marked ``@rebase-new``.

Only ``to_dir`` is written.  ``from_dir`` is never touched.
"""
from __future__ import annotations

import difflib
import os
import re

from . import files, paths, tables

FROM_OURS = "@from-ours"
FROM_V005 = "@from-v005"
UNMATCHED = "@rebase-unmatched"
NEW = "@rebase-new"
TAGDIFF = "@rebase-tagdiff"

_TOKEN = re.compile(r"\{[^}]*\}|<wait>|\\n|\\<|\\\\|\\\{")


def is_english(s: str) -> bool:
    """Is this rendered span English prose rather than Japanese?

    Control tokens are stripped first, so a line that is nothing but ``{08:12}``
    pool calls does not count as English, and neither does an all-punctuation
    line.  What is left must be pure ASCII and contain at least one letter.
    """
    bare = _TOKEN.sub("", s)
    return bool(bare.strip()) and all(ord(c) < 128 for c in bare) \
        and any(c.isalpha() for c in bare)


def _add(note: str, marker: str, once: bool = True) -> str:
    if once and marker in note:
        return note
    return (note + " " + marker).strip()


def _load(text_dir: str) -> "dict[tuple[str, str], list[tables.Row]]":
    """Rows grouped by ``(file, record)``, each group in span order."""
    groups = {}
    for path in tables.iter_tables(text_dir):
        for r in tables.read(path):
            groups.setdefault((r.file, r.rec), []).append(r)
    for g in groups.values():
        g.sort(key=lambda r: r.idx)
    return groups


def _pairs(old, new):
    """Align two records' spans by their tag sequences.

    Returns ``(pairs, old_left, new_left)``: ``pairs`` is ``(old, new, tagdiff)``
    for every aligned span; the leftovers are spans on either side that no
    block could account for.
    """
    sm = difflib.SequenceMatcher(None, [r.tag for r in old], [r.tag for r in new],
                                 autojunk=False)
    pairs, old_left, new_left = [], [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                pairs.append((old[i1 + k], new[j1 + k], op == "replace"))
        else:
            old_left += old[i1:i2]
            new_left += new[j1:j2]
    return pairs, old_left, new_left


def _carry(src, dst, tagdiff: bool, st: dict) -> bool:
    """Move one translation from a v2 row onto its paired v3 row."""
    ours = src.en if (src.en and src.en != src.jp) else None
    if "@untiled" in dst.note:
        st["untiled_skipped"] += 1
        if ours:
            dst.note = _add(dst.note, "%s en=%s" % (UNMATCHED, ours), once=False)
            return True
        return False
    if ours is not None and ours != dst.jp:
        dst.en = ours
        dst.note = _add(dst.note, FROM_OURS)
        st["from_ours"] += 1
    elif is_english(src.jp) and not is_english(dst.jp):
        dst.en = src.jp
        dst.note = _add(dst.note, FROM_V005)
        st["from_v005"] += 1
    elif is_english(dst.jp):
        st["identity"] += 1
        return False
    else:
        st["untranslated"] += 1
        return False
    if tagdiff:
        dst.note = _add(dst.note, TAGDIFF)
        st["tagdiff"] += 1
    return True


def run(from_dir: "str | None" = None, to_dir: "str | None" = None,
        quiet: bool = False, report: "str | None" = None) -> dict:
    from_dir = from_dir or os.path.join(paths.REPO_ROOT, "text_v2")
    to_dir = to_dir or os.path.join(paths.REPO_ROOT, "text_v3")
    report = report or os.path.join(paths.BUILD_DIR, "rebase-report.txt")

    v2 = _load(from_dir)
    st = {"rows": 0, "from_ours": 0, "from_v005": 0, "tagdiff": 0,
          "identity": 0, "untranslated": 0, "new": 0, "unmatched": 0,
          "untiled_skipped": 0}
    unmatched = []

    for path in tables.iter_tables(to_dir):
        rows = tables.read(path)
        by_rec = {}
        for r in rows:
            by_rec.setdefault((r.file, r.rec), []).append(r)
        changed = False
        for key, new in by_rec.items():
            new.sort(key=lambda r: r.idx)
            st["rows"] += len(new)
            old = v2.get(key)
            if old is None:
                for r in new:
                    r.note = _add(r.note, NEW)
                st["new"] += len(new)
                changed = True
                continue
            pairs, old_left, new_left = _pairs(old, new)
            for s, d, td in pairs:
                changed = _carry(s, d, td, st) or changed
            for r in new_left:
                r.note = _add(r.note, NEW)
                st["new"] += 1
                changed = True
            for s in old_left:
                st["unmatched"] += 1
                ours = s.en if (s.en and s.en != s.jp) else None
                if ours:
                    unmatched.append((s.file, s.rec, s.idx, s.tag, ours))
                    anchor = min(new, key=lambda r: abs(r.idx - s.idx))
                    anchor.note = _add(anchor.note, "%s idx%d en=%s"
                                       % (UNMATCHED, s.idx, ours), once=False)
                    changed = True
        if changed:
            tables.write(path, rows)

    os.makedirs(os.path.dirname(report), exist_ok=True)
    with open(report, "w", encoding="utf-8") as fh:
        fh.write("rebase %s -> %s\n\n" % (from_dir, to_dir))
        for k, v in st.items():
            fh.write("%-16s %d\n" % (k, v))
        fh.write("\nunmatched v2 rows that held one of our translations "
                 "(file, record, span, tag, en):\n")
        for row in unmatched:
            fh.write("  %s\t%s\t%d\t%s\t%s\n" % row)

    if not quiet:
        print("rebased %d rows in %s" % (st["rows"], to_dir))
        print("  %d carry our translation, %d carry v0.05\'s English beside the "
              "real Japanese (%d of all carries paired across a changed tag, "
              "marked %s), %d already English in the original"
              % (st["from_ours"], st["from_v005"], st["tagdiff"], TAGDIFF,
                 st["identity"]))
        print("  %d still untranslated, %d new to the original, %d untiled"
              % (st["untranslated"], st["new"], st["untiled_skipped"]))
        print("  %d v2 spans could not be aligned; %d of those held a translation "
              "of ours, kept in the nearest v3 note as %s (see %s)"
              % (st["unmatched"], len(unmatched), UNMATCHED, report))
    return st
