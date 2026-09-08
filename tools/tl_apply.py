"""Apply a translator's answers to the tables, refusing anything that would not build.

    python tools/tl_apply.py m/MS0002.BIN answers.tsv [--write]

Reads `rec<TAB>idx<TAB>english`, one row per line.  Without `--write` it only
reports; with `--write` it updates `build/tables_draft` and sets `status=draft`.

Every refusal here is a failure mode that `giten check` would either miss or
only catch much later.  The two token rules were both learned from the pilot,
in opposite directions:

* **an invented `{...}` token** -- a pool call the Japanese never had.  Refused.
* **a token kept whose pool entry is untranslated** -- the engine splices the
  pool's *Japanese* in, so the line ships as ``by 人間 strength``.  `check`
  cannot see this: the `en` column holds a token, not Japanese characters.  The
  MS0015 pilot had 14 such placements (ニュートン, 人間, 我々, こちら, 結界).
  Refused, with the Japanese quoted so the translator can write the meaning.
* **dropping a token is FINE** and is the corpus norm -- only 1,475 of the
  10,554 rows we have translated keep every token, because most calls
  substitute a Japanese grammatical fragment with no English counterpart.
  Dropping one that *does* resolve to translated text is a warning, not an
  error, since it loses a word the pool already has in English.
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

import collections
import io
import os
import re
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)

from giten import codec, paths, script, tables

#: `{08:24}` calls record 0x24 of m/MS7F07; `{01:xx}`..`{08:xx}` map to MS7F00..07.
_CALL = re.compile(r"^\{0([1-8]):([0-9A-Fa-f]{2})\}$")
_POOL_CACHE: "dict[str, tuple]" = {}


def _pool(token: str) -> tuple:
    """``(english, japanese)`` for a pool call, or ``("", "")`` if not one."""
    if not _POOL_CACHE:
        for p in tables.iter_tables(os.path.join(paths.BUILD_DIR, "tables_draft")):
            for r in tables.read(p):
                if r.file.startswith("m/MS7F"):
                    _POOL_CACHE.setdefault("%s|%s" % (r.file, r.rec),
                                           (r.en or "", r.jp or ""))
    m = _CALL.match(token)
    if not m:
        return ("", "")
    rel = "m/MS7F0%d.BIN" % (int(m.group(1)) - 1)
    return _POOL_CACHE.get("%s|0:%s" % (rel, m.group(2).upper()), ("", ""))


def pool_en(token: str) -> str:
    """The English a pool call resolves to, or "" if it has none.

    Dropping a token that resolves to `Hayasaka` loses a name; dropping one whose
    pool entry is an untranslated Japanese particle loses nothing.
    """
    return _pool(token)[0]


def pool_jp(token: str) -> str:
    """The Japanese a pool call would splice in if its entry is untranslated."""
    return _pool(token)[1]

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
    # A token may be DROPPED but never invented.  Dropping is the norm: across
    # the corpus only 1,475 of 10,554 rows we translated keep every token, and
    # 2,988 drop them all.  Most `{08:xx}` calls substitute a Japanese
    # grammatical fragment (いない, もう, なんて) that has no place in an English
    # sentence; writing the words out literally is correct and is what both our
    # own translations and v0.05 do.  Requiring equality here is what made the
    # first MS0002 pass emit `No one{08:24}{02:08} here...`.
    want = collections.Counter(codec.control_tokens(row.jp or ""))
    got = collections.Counter(codec.control_tokens(en))
    added = got - want
    if added:
        bad.append((ln, rec, idx, "invented token(s) the Japanese does not have: %s"
                    % " ".join(sorted(added.elements())))); continue
    # KEEPING a token whose pool entry has no English is worse than dropping
    # one: the engine splices the pool's *Japanese* in, so the line ships as
    # "by 人間 strength".  `giten check` cannot see it -- the `en` column holds a
    # token, not Japanese characters -- so it has to be refused here.  Found in
    # the MS0015 pilot, where 14 placements would have shipped ニュートン, 人間,
    # 我々, こちら and 結界 inside English sentences.
    untranslated = sorted({t for t in got.elements()
                           if pool_jp(t) and not pool_en(t).strip()})
    if untranslated:
        bad.append((ln, rec, idx,
                    "kept token(s) whose pool entry is untranslated, so the game "
                    "would render Japanese: %s -- drop them and write the meaning"
                    % " ".join("%s=%s" % (t, pool_jp(t)) for t in untranslated)))
        continue
    lost = want - got
    named = [t for t in lost.elements() if pool_en(t).strip()]
    if named:
        warn.append((ln, rec, idx, "dropped token(s) that resolve to translated text: %s"
                     % " ".join("%s=%r" % (t, pool_en(t)) for t in sorted(set(named)))))
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
for ln, rec, idx, why in bad:
    print("   REFUSED line %-4d %s[%d]: %s" % (ln, rec, idx, why))
for ln, rec, idx, why in warn[:40]:
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
