"""``stats``: how much is translated, per file and per tag."""
from __future__ import annotations

import collections
import os

from . import files, paths, spans, tables, tokens


def collect(text_dir: "str | None" = None):
    text_dir = text_dir or paths.TEXT_DIR
    per_file = collections.OrderedDict()
    per_tag = collections.defaultdict(lambda: collections.Counter())
    totals = collections.Counter()

    for path in tables.iter_tables(text_dir):
        for r in tables.read(path):
            f = per_file.setdefault(r.file, collections.Counter())
            done = bool(r.en)
            state = "done" if done else "todo"
            if r.note and "suspect" in r.note:
                state = "suspect_" + state
            f[state] += 1
            f["total"] += 1
            per_tag[r.tag][state] += 1
            per_tag[r.tag]["total"] += 1
            totals[state] += 1
            totals["total"] += 1
    return per_file, per_tag, totals


def run(text_dir: "str | None" = None, per_file: bool = True,
        quiet: bool = False) -> dict:
    pf, pt, tot = collect(text_dir)
    if not tot["total"]:
        print("no text tables found under %s -- run `extract` first"
              % (text_dir or paths.TEXT_DIR))
        return {}

    def pct(a, b):
        return (100.0 * a / b) if b else 0.0

    lines = []
    if per_file:
        lines.append("%-22s %7s %7s %7s %7s" % ("file", "spans", "done", "todo", "%done"))
        lines.append("-" * 56)
        for name, c in pf.items():
            done = c["done"] + c["suspect_done"]
            todo = c["todo"] + c["suspect_todo"]
            lines.append("%-22s %7d %7d %7d %6.1f%%"
                         % (name, c["total"], done, todo, pct(done, c["total"])))
        lines.append("")

    lines.append("%-10s %7s %7s %7s %7s" % ("tag", "spans", "done", "todo", "%done"))
    lines.append("-" * 44)
    for tag in sorted(pt):
        c = pt[tag]
        done = c["done"] + c["suspect_done"]
        todo = c["todo"] + c["suspect_todo"]
        lines.append("%-10s %7d %7d %7d %6.1f%%"
                     % (tag, c["total"], done, todo, pct(done, c["total"])))

    done = tot["done"] + tot["suspect_done"]
    todo = tot["todo"] + tot["suspect_todo"]
    lines.append("-" * 44)
    lines.append("%-10s %7d %7d %7d %6.1f%%"
                 % ("TOTAL", tot["total"], done, todo, pct(done, tot["total"])))
    lines.append("")
    lines.append("of which flagged 'suspect' (likely misread operand data): "
                 "%d (%d still empty)"
                 % (tot["suspect_done"] + tot["suspect_todo"], tot["suspect_todo"]))
    lines.append("files with a text table: %d" % len(pf))

    text = "\n".join(lines)
    if not quiet:
        print(text)
    return {"per_file": pf, "per_tag": pt, "totals": tot, "text": text}
