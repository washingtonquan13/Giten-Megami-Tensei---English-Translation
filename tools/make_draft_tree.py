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
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import (check_v2, codec, extract_v2, files, paths,  # noqa: E402
                   tables)

OUT = os.path.join(paths.BUILD_DIR, "tables_draft")


NL = chr(92) + "n"
JP_ENDERS = "。！？」』…‥）】　"
EN_ENDERS = ".!?\"'"


def _calls(text):
    """The pool calls in one line, as check_v2's name-macro rule counts them."""
    return {t for t in codec.control_tokens(text) if t.startswith("{0")}


def _vis(s):
    return codec.strip_tokens(s).replace(NL, "").strip()


#: a span that is exactly one pool call and the full-width colon: a speaker tag
#: whose name the engine looks up at run time
SPEAKER_TAG = re.compile(r"^(\{[0-9A-F]{2}:[0-9A-F]{2}\})\uff1a$")


def _pool_english(src):
    """``{08:04}`` -> ``"Nishino"``, from the pool tables' own English."""
    out = {}
    for fid in range(8):
        path = files.table_path("m/MS7F%02X.BIN" % fid, src)
        if not os.path.exists(path):
            continue
        for r in tables.read(path):
            if r.idx != 0:
                continue
            en = (r.en or r.ref_en or "").strip()
            if en:
                out["{08:%02X}" % int(r.rec.split(":")[1], 16)] = en
    return out


#: Files whose "text" is a data run the tokenizer renders as characters.  The
#: engine walks and prints them, so a reference translation here is not a
#: harmless unused string -- it goes on screen.  `m/MS7F05` holds one record,
#: the six bytes of the string the corpus's seven apparent `{06:xx}` pool calls
#: are really made of; `docs/limits.md` calls it a dead dictionary.
DEAD_DATA = frozenset({"m/MS7F05.BIN"})

#: The eight macro pools.  A record here is not a line, it is a fragment the
#: engine splices into every sentence that calls it -- `m/MS7F07` record 0x52 is
#: reached from 3,931 places.  A reference translation was written against at
#: most one of those sentences, so it cannot be right in the others *by
#: construction*; this is not a judgement about the reference's quality.
#:
#: Shipped proof, from the 2026-09-07 session: `m/MS7F02` 0:0C is され, the
#: passive auxiliary, promoted to "was" (793 call sites), and `m/MS7F01` 0:0A is
#: ま{08:66} = ません, the negative ending, promoted to "not" (393 sites).  On
#: screen that reads `AMS用マップDataが登録wasていnot` -- the noun translated
#: correctly and English grammar words spliced into a Japanese sentence.
#:
#: Refusing the whole class costs 298 rows worth 5,351 call sites.  The 76 pool
#: rows written by hand in `tables/` are untouched and carry 21,910 call sites,
#: four times the coverage -- because a person picked the ones that *are* words:
#: names, 悪魔, シェルター, はい, いいえ.
#:
#: There is deliberately no "is this grammar?" test.  Two were tried and both
#: fail on the real data: "pure hiragana" flags はい and ありがとう, and "has no
#: pool call" misses ま{08:66}.  Whether a fragment is a word is not decidable
#: from its characters, so the line drawn here is the one that is decidable --
#: did a person write it, or did a promotion.
POOL_FILES = frozenset("m/MS7F%02X.BIN" % i for i in range(8))


def _speaker_is_wrong(jp, en, poolen):
    """Does this reference name someone the engine will not name?

    A speaker tag like ``{08:04}\uff1a`` prints whatever the pool holds -- 西野 --
    so the only faithful English is the pool's own, "Nishino".  v0.05 sometimes
    wrote who it thought was *really* talking instead: Marduk for the man he is
    possessing, Kusaka for Emi, Murmur for three different people in the fight
    where he appears.  A Japanese player sees the pooled name in every one of
    those, and a reader of the English should too.

    Returns the correct English, or None if there is nothing to say.  Only
    proper nouns are corrected: several pool words do double duty as common
    nouns mid-sentence, so {08:0B} reads "demon" and a tag spelling it "Demon:"
    is better English than the pool's own lower-case copy.
    """
    m = SPEAKER_TAG.match(jp.strip())
    if not m:
        return None
    want = poolen.get(m.group(1))
    if not want or not want[:1].isupper():
        return None
    want += ":"
    return want if en.strip() != want else None


def _covers_the_whole_line(jp, en):
    """Is this reference a translation of the line, not of this span?

    v0.05 stripped the engine's runtime name prints, so a line the engine prints
    a name *inside* is one line there and two or three spans here.  ``carry``
    paired by tag sequence and put the whole English on the first fragment, and
    ``refalign`` -- whose rule for this is to leave such rows untranslated, "a
    draft that cannot be split back around the print is worse than an empty row"
    -- only touches rows that have no reference, so it never revisited them.

    The result renders twice: the fragment shows the whole line in English, then
    the next span shows its own translation of the rest.  That is the doubled
    Emi and Yuuka dialogue.

    A genuine fragment translation matches its fragment -- it ends open, on a
    comma, as the Japanese does.  A whole-line draft closes: a full stop, or a
    line break, or both.  Requiring 40 characters and 4x keeps short labels
    (`魔石` -> "Magic Stone") and open continuations ("So as not to get in the way
    of the two of them,") out of it.
    """
    j, e = _vis(jp), _vis(en)
    if len(j) < 2 or NL in jp:
        return False
    if not j or j[-1] in JP_ENDERS:
        return False
    if not e or not (NL in en or e[-1] in EN_ENDERS):
        return False
    return len(e) >= 40 and len(e) > len(j) * 4


def main(out: str = OUT) -> int:
    src = extract_v2.text_v2_dir()
    if os.path.isdir(out):
        shutil.rmtree(out)
    names = check_v2.name_macros(None)
    poolen = _pool_english(src)
    rows = promoted = kept = skipped = refused = split = renamed = dead = 0
    shared = 0
    for path in tables.iter_tables(src):
        table = tables.read(path)
        for r in table:
            rows += 1
            if r.en and r.en != r.jp:
                kept += 1
                continue
            if not r.ref_en:
                continue
            if r.file in DEAD_DATA:
                # Not text.  `tables/` deliberately leaves these blank; only
                # this promotion filled them, and the engine does execute them
                # -- m/MS7F05 record 0 is a data run the interpreter walks and
                # "prints", so the reference translation reached the screen as
                # "Dictionary 5" during a battle.  See docs/limits.md.
                dead += 1
                continue
            if r.file in POOL_FILES:
                # shared by every script that calls it; see POOL_FILES
                shared += 1
                continue
            if r.tag == extract_v2.UNTILED_TAG:
                # no dependable span boundaries; the overlay refuses these anyway
                skipped += 1
                continue
            fixed = _speaker_is_wrong(r.jp, r.ref_en, poolen)
            if fixed:
                r.en = fixed
                r.status = "draft"
                renamed += 1
                promoted += 1
                continue
            if _covers_the_whole_line(r.jp, r.ref_en):
                split += 1
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
          "%d dead data (never promoted), "
          "%d shared pool fragments (never promoted), "
          "%d skipped (@untiled), %d refused (would drop a name macro), "
          "%d refused (translates the whole line, not this span), "
          "%d speaker tags renamed to the pooled name"
          % (out, rows, kept, promoted, dead, shared, skipped, refused, split, renamed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else OUT))
