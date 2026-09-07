"""Derive a *draft* table tree from ``tables/``: every reference promoted to ``en``.

The playable English build is not built from ``tables/``.  ``tables/`` holds only
what someone has actually written or reviewed -- 17,517 rows of 45,559 -- so a
build from it plays mostly in Japanese.  What makes the game readable end to end
is a tree where every ``ref_en`` candidate is also treated as English: 43,746
rows.  That is a legitimate way to play it, as long as nobody mistakes it for the
reviewed corpus.

Until now that tree was made ad hoc and left in ``build/tables_draft``, with
nothing in the repo able to reproduce it.  That is a trap, because **span
numbering is a property of the tokenizer**: it moves whenever the opcode model
improves, and a stale draft tree puts its English on neighbouring lines.  The
tree that shipped on 2026-09-06 was 45,311 rows against ``tables/``'s 45,559 and
predated that day's `0x152`-`0x155` fix, so it was already drifting.

So: always regenerate from the current ``tables/``, never rebuild an old tree.

    python tools/make_draft_tree.py            # -> build/tables_draft
    python -m giten overlay --text build/tables_draft --out build/overlay-draft.dat

``status`` is forced to ``draft`` on every row this promotes, whatever the
reference said.  These have not been read against the Japanese, and the one thing
this tree must never do is let an unread line look reviewed.
"""
from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import check_v2, codec, extract_v2, paths, tables      # noqa: E402

OUT = os.path.join(paths.BUILD_DIR, "tables_draft")


def _calls(text):
    """The pool calls in one line, as check_v2's name-macro rule counts them."""
    return {t for t in codec.control_tokens(text) if t.startswith("{0")}


def main(out: str = OUT) -> int:
    src = extract_v2.text_v2_dir()
    if os.path.isdir(out):
        shutil.rmtree(out)
    names = check_v2.name_macros(None)
    rows = promoted = kept = skipped = refused = 0
    for path in tables.iter_tables(src):
        table = tables.read(path)
        for r in table:
            rows += 1
            if r.en and r.en != r.jp:
                kept += 1
                continue
            if not r.ref_en:
                continue
            if r.tag == extract_v2.UNTILED_TAG:
                # no dependable span boundaries; the overlay refuses these anyway
                skipped += 1
                continue
            if names & _calls(r.jp) - _calls(r.ref_en):
                # The reference drops a macro that prints a runtime name, so the
                # line would appear with nobody in it.  Two v0.05 rows in
                # m/MS00DE do this, both over a pre-filled row whose `en` is
                # already the original bytes -- which are correct.  Leave them.
                refused += 1
                continue
            r.en = r.ref_en
            r.status = "draft"          # never "reviewed": nobody has read it
            promoted += 1
        rel = os.path.relpath(path, src)
        dst = os.path.join(out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tables.write(dst, table)
    print("%s: %d rows, %d already English, %d promoted from a reference, "
          "%d skipped (@untiled), %d refused (would drop a name macro)"
          % (out, rows, kept, promoted, skipped, refused))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else OUT))
