"""Make every byte-identical record carry one English line.

Overlay v6 keys a translated span on the **content** of the record it lives in
-- ``(record id, record length, FNV-1a of the record's bytes)`` -- because that
is the only thing about a running buffer that cannot go stale.  The price is a
single residual: two files holding a byte-identical record are one key, so they
get one translation.  Measured on the draft tree the day v6 was written, 253
keys in 46 files carried two or more: ``Man:`` against ``Male:``, three
renderings of ``There's no one here...``, two shopkeepers' greetings written a
month apart.

``giten overlay`` refuses to build while any remain and ``giten check`` lists
them.  This resolves them **in the tables**, which is where the disagreement
actually is -- the overlay is only what noticed.

The choice, in order:

1. a row whose ``status`` is ``reviewed`` -- somebody read that one against the
   Japanese, and no promotion did;
2. otherwise the text the most rows already carry;
3. otherwise the longest, which in practice is the one that did not get
   truncated.

Ties inside each rule break on ``(file, record, index)``, so a rerun is a no-op.

The text is written back into the field the row's English already lives in:
``en`` for a row that is edited, ``ref_en`` for a row that only has a candidate.
A row with neither is not in a group and is never touched -- this tool does not
translate anything, it only makes two existing translations agree.

    python tools/unify_duplicates.py --dry-run     # print, change nothing
    python tools/unify_duplicates.py               # rewrite tables/
"""
from __future__ import annotations

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import extract_v2, files, overlay, script, tables  # noqa: E402


def record_keys(rel: str, root=None):
    """``{(rec_key, span idx): (rec_id, record length, FNV-1a)}`` for one file.

    The same grouping ``overlay.plan`` does, and for the same reason: two spans
    share a key exactly when the overlay cannot tell their records apart.
    """
    out = {}
    sc = script.parse(rel, files.read_source(rel, root))
    if not sc.ok:
        return out
    for cont in sc.containers:
        seen = set()
        for rec in cont:
            if rec.id in seen or rec.span_tokens is None:
                continue
            seen.add(rec.id)
            key = (rec.id, len(rec.data), overlay.fnv1a(rec.data))
            for sp in rec.spans:
                out[(sp.rec_key, sp.idx)] = key
    return out


def _field(row):
    """Which column carries this row's English, and what it says."""
    if row.edited:
        return "en", row.en
    if row.ref_en:
        return "ref_en", row.ref_en
    return None, ""


def _winner(group):
    """The text every row in the group should carry, and the row it came from."""
    reviewed = [r for r in group if r.status == "reviewed" and _field(r)[1]]
    if reviewed:
        pick = sorted(reviewed, key=lambda r: (r.file, r.rec, r.idx))[0]
        return _field(pick)[1], pick, "reviewed"
    counts = collections.Counter(_field(r)[1] for r in group)
    best = max(counts.values())
    tied = sorted({t for t, n in counts.items() if n == best})
    if len(tied) == 1:
        text = tied[0]
        why = "most frequent (%d of %d)" % (best, len(group))
    else:
        text = max(sorted(tied), key=len)
        why = "longest of %d tied" % len(tied)
    pick = sorted((r for r in group if _field(r)[1] == text),
                  key=lambda r: (r.file, r.rec, r.idx))[0]
    return text, pick, why


def plan_changes(root=None, text_dir=None):
    """``(changes, keys that disagreed, {path: rows})``.

    A change is ``(path, row, column, before, after, winner row, why)``; the row
    objects are the ones in ``{path: rows}``, so applying a change and writing
    that list back is the whole edit.
    """
    text_dir = text_dir or extract_v2.text_v2_dir()
    by_path = {}
    groups = collections.defaultdict(list)
    keys = {}
    for path in tables.iter_tables(text_dir):
        rows = tables.read(path)
        by_path[path] = rows
        for r in rows:
            if not r.file.startswith("m/"):
                continue
            if r.tag == extract_v2.UNTILED_TAG or r.rec == extract_v2.PNAME_REC:
                continue
            if not _field(r)[1]:
                continue
            if r.file not in keys:
                keys[r.file] = record_keys(r.file, root)
            key = keys[r.file].get((r.rec, r.idx))
            if key is None:
                continue
            groups[(key, r.idx)].append((path, r))

    changes, clashed = [], 0
    for key in sorted(groups, key=lambda k: (k[0], k[1])):
        members = groups[key]
        texts = {_field(r)[1] for _p, r in members}
        if len(texts) < 2:
            continue
        clashed += 1
        text, pick, why = _winner([r for _p, r in members])
        for path, r in sorted(members, key=lambda pr: (pr[1].file, pr[1].rec, pr[1].idx)):
            col, had = _field(r)
            if had == text:
                continue
            changes.append((path, r, col, had, text, pick, why))
    return changes, clashed, by_path


def apply(changes) -> "set[str]":
    """Mutate the rows in place; returns the table files that changed."""
    touched = set()
    for path, row, col, _had, text, pick, _why in changes:
        setattr(row, col, text)
        note = "unified with %s %s[%d]" % (pick.file, pick.rec, pick.idx)
        if note not in row.note:
            row.note = note if not row.note else "%s; %s" % (row.note, note)
        touched.add(path)
    return touched


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--text-dir", default=None)
    ap.add_argument("--root", default=None)
    args = ap.parse_args(argv)
    try:                    # the report is the commit body; it has to survive
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    changes, clashed, by_path = plan_changes(args.root, args.text_dir)
    for path, row, col, had, text, pick, why in changes:
        print("%-18s %-8s [%d]  %-6s  %r -> %r   (%s, from %s %s[%d])"
              % (row.file, row.rec, row.idx, col, had, text, why,
                 pick.file, pick.rec, pick.idx))
    print("")
    print("%d record key(s) carried more than one English; %d row(s) rewritten "
          "across %d table file(s)"
          % (clashed, len(changes), len({c[0] for c in changes})))
    if args.dry_run or not changes:
        return 0
    for path in sorted(apply(changes)):
        tables.write(path, by_path[path])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
