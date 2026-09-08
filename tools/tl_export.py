"""Export one script file's untranslated / v0.05-occupied rows as a brief.

The retranslation replaces 16,769 rows whose English is byte-for-byte
Sneikkimies' v0.05 text (see `docs/todo.md` item 0).  A translator -- human or
agent -- needs three things per row that a raw TSV does not give them: the
record grouping (a line means nothing out of its scene), the *expanded* reading
of the macros, and the width budget it has to fit.

    python tools/tl_export.py m/MS0002.BIN [out.md]

Writes a Markdown brief and prints the row count.  Pair with `tl_apply.py`,
which reads the answers back and refuses anything that would not build.

**Why the `{08:24}` tokens must survive.**  They are not formatting: `{enc:hex}`
is a real inline opcode (`giten/codec.py:op_token`), usually a macro-pool call
that substitutes a word or a name.  Dropping one silently deletes that word from
the game; moving one changes where it lands.  `tl_apply` compares the multiset
of tokens against the Japanese and refuses a mismatch, because `giten check`'s
`encode` validator only catches *malformed* tokens, not missing ones.
"""
from __future__ import annotations

import io
import os
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)

from giten import codec, paths, script, tables

REL = sys.argv[1] if len(sys.argv) > 1 else "m/MS0002.BIN"
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    R, "build", "tl", REL.split("/")[-1].replace(".BIN", "") + ".md")
DRAFT = os.path.join(paths.BUILD_DIR, "tables_draft")


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
w("## Hard constraints -- these break the build, not just the prose\n\n"
  "1. **Keep every `{...}` token**, unchanged and in a sensible place.  They are\n"
  "   inline opcodes (macro-pool calls that substitute a word or name), not\n"
  "   formatting.  Same tokens, same count, as the Japanese.\n"
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
            w("  - tokens that MUST survive: %s\n" % " ".join("`%s`" % t for t in tok))
        if (r.en or "").strip():
            w("  - v0.05 (replace this): `%s`\n" % r.en)
    w("\n")
out.close()
print("%s: %d rows to write, %d total; brief -> %s" % (REL, len(scope), len(rows), OUT))
