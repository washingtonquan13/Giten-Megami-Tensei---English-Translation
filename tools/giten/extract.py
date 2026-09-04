"""``extract``: game files -> editable text tables under ``text/``."""
from __future__ import annotations

import os

from . import container, dictionary, files, paths, spans, tables, tokens


def rows_for(rel: str, raw: bytes, dic) -> "list[tables.Row]":
    """Build the table rows for one source file."""
    _hdr, body = container.unpack(raw)
    _frames, found = spans.scan(rel, body, dic)
    rows = []
    for sp in found:
        jp = spans.span_text(body, sp, dic)
        notes = []
        # Pre-fill `en` when the span already reads as English.  A row whose `en`
        # equals its `jp` is a no-op on build, so pre-filling costs nothing and
        # tells a translator at a glance which lines are already done.
        en = "" if tokens.has_japanese(jp) else jp
        if spans.suspect(jp):
            notes.append("suspect: may be misread operand data, verify before editing")
        if "{DICT:" in jp:
            notes.append("unresolved dictionary reference")
        if any(t.startswith("{") and not t.startswith("{DICT")
               for t in tokens.control_tokens(jp)):
            notes.append("runtime inserts: reproduce every {XX} token, in order")
        rows.append(tables.Row(rel, sp.rec, sp.idx, sp.off, sp.tag, jp, en,
                               "; ".join(notes)))
    return rows


def run(family: str = "all", root: "str | None" = None,
        text_dir: "str | None" = None, quiet: bool = False) -> "dict":
    """Extract one or more families.  Existing ``en``/``note`` values are kept."""
    dic = dictionary.load(root)
    text_dir = text_dir or paths.TEXT_DIR
    fams = files.expand_family(family)

    # Group by output table so the shared p/ table is written once.
    by_table = {}
    order = []
    stats = {"files": 0, "spans": 0, "tables": 0, "skipped": 0}

    for rel in files.iter_files(fams, root):
        if rel in files.EXCLUDE_FROM_TEXT:
            stats["skipped"] += 1
            continue
        rows = rows_for(rel, files.read_source(rel, root), dic)
        stats["files"] += 1
        if not rows:
            continue
        stats["spans"] += len(rows)
        path = files.table_path(rel, text_dir)
        if path not in by_table:
            by_table[path] = []
            order.append(path)
        by_table[path].extend(rows)

    for path in order:
        rows = by_table[path]
        # Merge: keep any `en`/`note` a translator already wrote, matched on the
        # stable (file, rec, idx) identity.  `jp`/`off`/`tag` always come from the
        # game files, so a re-extraction can never silently drift.
        old = {r.key: r for r in tables.read(path)}
        for r in rows:
            prev = old.get(r.key)
            if prev is not None:
                if prev.en and prev.en != prev.jp:
                    r.en = prev.en          # a real translation survives
                elif prev.en:
                    r.en = r.jp             # was a pre-fill; refresh it
                if prev.note and prev.note != r.note:
                    r.note = prev.note if not r.note else prev.note + "; " + r.note
        tables.write(path, rows)
        stats["tables"] += 1
        if not quiet:
            print("%-40s %5d rows" % (os.path.relpath(path, paths.REPO_ROOT), len(rows)))

    if not quiet:
        print("\nextracted %d spans from %d files into %d tables (%d excluded)"
              % (stats["spans"], stats["files"], stats["tables"], stats["skipped"]))
    return stats
