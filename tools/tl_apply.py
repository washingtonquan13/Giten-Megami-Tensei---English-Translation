"""Apply a translator's answers to the tables, refusing anything that would not build.

    python tools/tl_apply.py m/MS0002.BIN answers.tsv [--write]

Reads `rec<TAB>idx<TAB>english`, one row per line.  Without `--write` it only
reports; with `--write` it updates `build/tables_draft` and sets `status=draft`.

Every refusal here is a failure mode that `giten check` would either miss or
only catch much later:

* **a dropped `{...}` token** -- `check`'s `encode` validator parses tokens that
  are present and malformed; it cannot know one is missing.  A missing macro
  call silently deletes a word or a name from the game.
* **a changed `\\n` count** -- the line still builds and then wraps wrongly in a
  box whose height the script already decided.
* **non-cp932 text** -- caught by `check`, but far cheaper to reject per row than
  to bisect a failing build.
* **an `@noedit` row** -- the builder would accept the edit and silently do
  nothing, which is the worst of the three outcomes.

The width check is a *warning*, not a refusal: `display_width` cannot know what a
pool call expands to, so it under-counts by design (`giten/pool.py` does that
separately) and a hard limit here would reject correct lines.
"""
from __future__ import annotations

import io
import os
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)

from giten import codec, paths, script, tables

REL = sys.argv[1]
ANS = sys.argv[2]
WRITE = "--write" in sys.argv[3:]
DRAFT = os.path.join(paths.BUILD_DIR, "tables_draft")
BOX_COLUMNS = 74

paths_by_file = {}
for p in tables.iter_tables(DRAFT):
    for r in tables.read(p):
        if r.file == REL:
            paths_by_file.setdefault(p, []).append(r)
if not paths_by_file:
    raise SystemExit("no table rows for %s" % REL)

index = {}
for p, rs in paths_by_file.items():
    for r in rs:
        index[(r.rec, r.idx)] = (p, r)

answers = []
for ln, line in enumerate(io.open(ANS, encoding="utf-8"), 1):
    line = line.rstrip("\n").rstrip("\r")
    if not line.strip():
        continue
    parts = line.split("\t")
    if len(parts) < 3:
        print("line %d: need 3 tab-separated fields, got %d" % (ln, len(parts)))
        continue
    rec, idx, en = parts[0].strip(), parts[1].strip(), "\t".join(parts[2:])
    answers.append((ln, rec, int(idx), en))

ok, bad, warn = [], [], []
for ln, rec, idx, en in answers:
    hit = index.get((rec, idx))
    if hit is None:
        bad.append((ln, rec, idx, "no such row in %s" % REL)); continue
    _p, row = hit
    if script.NOEDIT_NOTE in (row.note or ""):
        bad.append((ln, rec, idx, "row is @noedit; the builder would ignore it")); continue
    if not en.strip():
        bad.append((ln, rec, idx, "empty translation")); continue
    if "\t" in en or "\r" in en or "\n" in en:
        bad.append((ln, rec, idx, "literal tab/newline in the text")); continue
    try:
        en.encode("cp932")
    except UnicodeEncodeError as exc:
        chs = en[exc.start:exc.end]
        bad.append((ln, rec, idx, "not cp932-encodable: %r" % chs)); continue
    want = sorted(codec.control_tokens(row.jp or ""))
    got = sorted(codec.control_tokens(en))
    if want != got:
        bad.append((ln, rec, idx, "tokens changed: japanese has %s, answer has %s"
                    % (want or "none", got or "none"))); continue
    if (row.jp or "").count("\\n") != en.count("\\n"):
        bad.append((ln, rec, idx, "\\n count changed: %d -> %d"
                    % ((row.jp or "").count("\\n"), en.count("\\n")))); continue
    for seg in en.split("\\n"):
        wdt = codec.display_width(seg)
        if wdt > BOX_COLUMNS:
            warn.append((ln, rec, idx, "a line is %d columns, box is %d" % (wdt, BOX_COLUMNS)))
    ok.append((rec, idx, en))

print("%s: %d answers, %d accepted, %d refused, %d warnings"
      % (REL, len(answers), len(ok), len(bad), len(warn)))
for ln, rec, idx, why in bad[:40]:
    print("   REFUSED line %-4d %s[%d]: %s" % (ln, rec, idx, why))
for ln, rec, idx, why in warn[:15]:
    print("   warn    line %-4d %s[%d]: %s" % (ln, rec, idx, why))

if not WRITE:
    print("\n(dry run -- pass --write to apply)")
    raise SystemExit(1 if bad else 0)
if bad:
    raise SystemExit("refusing to write while %d answers are invalid" % len(bad))

applied = {(rec, idx): en for rec, idx, en in ok}
for p, rs in paths_by_file.items():
    all_rows = tables.read(p)
    touched = 0
    for r in all_rows:
        en = applied.get((r.rec, r.idx)) if r.file == REL else None
        if en is None:
            continue
        r.en = en
        r.status = "draft"
        touched += 1
    if touched:
        tables.write(p, all_rows)
        print("   wrote %d row(s) to %s" % (touched, os.path.relpath(p, R)))
print("done: %d rows now carry our own English" % len(applied))
