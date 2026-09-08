"""Export one script file's untranslated / v0.05-occupied rows as a brief.

The retranslation replaces 16,769 rows whose English is byte-for-byte
Sneikkimies' v0.05 text (see `docs/todo.md` item 0).  A translator -- human or
agent -- needs three things per row that a raw TSV does not give them: the
record grouping (a line means nothing out of its scene), the *expanded* reading
of the macros, and the width budget it has to fit.

    python tools/tl_export.py m/MS0002.BIN [out.md]

Writes a Markdown brief and prints the row count.  Pair with `tl_apply.py`,
which reads the answers back and refuses anything that would not build.

**The `{08:24}` tokens, and the mistake this brief exists to prevent.**  `{enc:hex}`
is a real inline opcode (`giten/codec.py:op_token`), usually a macro-pool call:
the Japanese is stored *compressed*, with common words factored into pools, and
the engine splices the word back at runtime.

The first pass at this tool told translators to keep every token, and the first
agent to use it dutifully produced ``No one{08:24}{02:08} here...`` for
``誰も{08:24}{02:08}‥`` -- because `{08:24}` **is** the word ``いない``, and there is
nowhere in an English sentence to put it.

So the brief annotates every token with what it resolves to.  A token that
resolves to a name or a real word (``{08:00}`` = *Hayasaka*) is worth keeping and
placing; an untranslated Japanese fragment should be dropped and its meaning
written out.  Dropping is the corpus norm -- only 1,475 of the 10,554 rows we
have translated keep every token, and 2,988 drop them all.  `tl_apply` enforces
only the half that is mechanical: you may drop any token, never invent one.
"""
from __future__ import annotations

import io
import re
import os
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)

from giten import codec, paths, script, tables

DRAFT = os.path.join(paths.BUILD_DIR, "tables_draft")

_CALL = re.compile(r"^\{0([1-8]):([0-9A-Fa-f]{2})\}$")
_POOL: "dict[str, tuple]" = {}


def pool_of(token: str) -> tuple:
    """``(english, japanese)`` a pool call resolves to, or ``("", "")``.

    Showing this in the brief is the whole difference between a translator who
    keeps `{08:00}` because it is *Hayasaka* and one who keeps `{08:24}` because
    a rule told them to, and thereby writes `No one{08:24} here...`.
    """
    if not _POOL:
        for p in tables.iter_tables(DRAFT):
            for r in tables.read(p):
                if r.file.startswith("m/MS7F"):
                    _POOL["%s|%s" % (r.file, r.rec)] = (r.en or "", r.jp or "")
    m = _CALL.match(token)
    if not m:
        return ("", "")
    rel = "m/MS7F0%d.BIN" % (int(m.group(1)) - 1)
    return _POOL.get("%s|0:%s" % (rel, m.group(2).upper()), ("", ""))


REL = sys.argv[1] if len(sys.argv) > 1 else "m/MS0002.BIN"
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    R, "build", "tl", REL.split("/")[-1].replace(".BIN", "") + ".md")


def in_scope(r) -> bool:
    """A row this pass is meant to rewrite: v0.05's words, or nothing at all."""
    if script.NOEDIT_NOTE in (r.note or ""):
        return False
    if not (r.jp or "").strip():
        return False
    if not (r.en or "").strip():
        return True                                     # never translated
    return (r.edited and r.ref_en and r.en == r.ref_en
            and r.status != "reviewed"
            and (r.ref_src or "").strip() == "v005")


rows = [r for p in tables.iter_tables(DRAFT) for r in tables.read(p)
        if r.file == REL]
if not rows:
    raise SystemExit("no table rows for %s" % REL)
scope = [r for r in rows if in_scope(r)]
by_rec: "dict[str, list]" = {}
for r in rows:
    by_rec.setdefault(r.rec, []).append(r)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
out = io.open(OUT, "w", encoding="utf-8")
w = out.write

w("# Translation brief: `%s`\n\n" % REL)
w("%d rows to write, of %d in the file.  Rows marked KEEP are already ours --\n"
  "they are shown for context and voice only; do not submit them.\n\n"
  % (len(scope), len(rows)))
w("## How to answer\n\n"
  "Write a TSV with three columns and no header: `rec`, `idx`, `english`.\n"
  "One line per TODO row, tab-separated, in this file's order.  Nothing else.\n\n")
w("## The `{...}` tokens -- read this first, it is the easiest thing to get wrong\n\n"
  "A `{08:24}` is a **macro-pool call**: at runtime the engine splices in whatever\n"
  "word that pool entry holds.  The Japanese sentence is *stored compressed*, with\n"
  "common words factored out into pools.  Each token below is annotated with what\n"
  "it resolves to.\n\n"
  "* If a token resolves to a **name or a real word** (`{08:00}=Hayasaka`), **keep\n"
  "  it** and put it where that word belongs in the English sentence.\n"
  "* If a token is an untranslated Japanese grammatical fragment "
  "(`{08:24}` = `いない`, `{08:5C}` = `もう`), **drop it** and write the meaning out\n"
  "  in plain English.  These have no place in an English sentence.\n\n"
  "**Dropping is normal and expected.**  Across the corpus only 1,475 of 10,554\n"
  "already-translated rows keep every token; 2,988 drop them all.  Do NOT sprinkle\n"
  "tokens through the English to preserve a count -- that produces word salad like\n"
  "`No one{08:24}{02:08} here...`.  You may drop any token; you may never invent one\n"
  "the Japanese does not have.\n\n"
  "## Hard constraints -- these break the build, not just the prose\n\n"
  "1. **Never add a `{...}` token** the Japanese line does not contain, and never\n"
  "   alter one you keep.\n"
  "2. **`\\n` is a literal line break inside the message box.**  Keep the same\n"
  "   number as the Japanese unless the note says otherwise.\n"
  "3. **cp932 only.**  No curly quotes, no en/em dashes, no accented letters.\n"
  "   Use `'`, `\"`, `-`, `...`.  A single non-cp932 character fails the build.\n"
  "4. **Width**: a rendered line must fit **74 columns**; a menu option must fit\n"
  "   the width its menu declares (usually **20**).  The budget is shown per row.\n"
  "5. No literal tab or newline characters in the answer field.\n\n")
w("## Names and terms -- non-negotiable\n\n"
  "* `バエル` is **Bael** (the demon lord).  `バール` is **Baal** -- "
  "`バール教団` = **Baal Cult**, `バール兵` = **Baal Soldier**.  Never mix them.\n"
  "* **Murmur** is male.\n"
  "* **Ayato Katsuragi** is the official spelling of that name.\n"
  "* Follow `translation/glossary.tsv` and `translation/style-guide.md` for the rest.\n\n")
w("## Voice\n\n"
  "This is a 1997 Japanese CRPG: modern-day Tokyo, occult, often grim.  Match the\n"
  "register of the Japanese line -- terse where it is terse, crude where it is\n"
  "crude.  The v0.05 line is shown only so you can see what is being replaced; it\n"
  "took liberties and is **not** a model to follow.  Translate the Japanese.\n\n")
w("---\n\n")

n = 0
for rec, rs in by_rec.items():
    if not any(in_scope(r) for r in rs):
        continue
    w("## record `%s`\n\n" % rec)
    for r in rs:
        todo = in_scope(r)
        tok = codec.control_tokens(r.jp or "")
        budget = ""
        if (r.tag or "").upper() == "1FB1" or "choice" in (r.note or ""):
            budget = "  (menu option: keep it short)"
        line = "**TODO**" if todo else "keep"
        if todo:
            n += 1
        w("- [`%s`|`%d`] %s%s\n" % (r.rec, r.idx, line, budget))
        w("  - JP: `%s`\n" % (r.jp or ""))
        note = (r.note or "")
        if note.startswith("reads:") or "reads:" in note:
            w("  - reads: `%s`\n" % note.split("reads:", 1)[1].split(";")[0].strip())
        if tok:
            parts = []
            for t in dict.fromkeys(tok):
                en, jp = pool_of(t)
                if en:
                    parts.append("`%s` = **%s** (keep)" % (t, en))
                elif jp:
                    parts.append("`%s` = %s (untranslated fragment - drop it, "
                                 "write the meaning in English)" % (t, jp))
                else:
                    parts.append("`%s` (control code - keep)" % t)
            w("  - tokens: %s\n" % "; ".join(parts))
        if (r.en or "").strip():
            w("  - v0.05 (replace this): `%s`\n" % r.en)
    w("\n")
out.close()
print("%s: %d rows to write, %d total; brief -> %s" % (REL, len(scope), len(rows), OUT))
