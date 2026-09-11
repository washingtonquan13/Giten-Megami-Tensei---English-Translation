"""A pool fragment is shared, so a reference draft can never be right in it.

The eight macro pools ``m/MS7F00``..``m/MS7F07`` are not lines.  Each record is
a fragment the engine splices into every sentence that calls it -- ``m/MS7F07``
record 0x52 is reached from 3,931 places.  A reference translation was written
against at most one of those sentences, so it cannot be correct in the rest *by
construction*.  That is a statement about what the reference data can possibly
know, not a judgement about how good it is.

What shipped without this rule, seen on screen on 2026-09-07::

    AMS用マップDataが登録wasていnot

``データ`` -> "Data" is a real word, correctly translated by hand.  ``され``
(the passive auxiliary) had been promoted to "was" and ``ま{08:66}`` = ``ません``
(the negative ending) to "not", so English grammar words were spliced into a
Japanese sentence at 793 and 393 call sites respectively.

**No "is this grammar?" test is attempted, and these tests pin why.**  Two were
tried against the real data and both fail: "pure hiragana" flags ``はい`` and
``ありがとう``, which are words; "contains no pool call" misses ``ま{08:66}``,
which is not.  Whether a fragment is a word is not decidable from its
characters.  The line drawn instead is decidable: a person wrote it, or a
promotion did.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import paths, tables

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import make_draft_tree  # noqa: E402

NL = chr(92) + "n"

DRAFT = os.path.join(paths.BUILD_DIR, "tables_draft")
SRC = os.path.join(paths.REPO_ROOT, "tables")
POOL = frozenset("m/MS7F%02X.BIN" % i for i in range(8))

#: The two that reached the screen, kept by name so a regression is legible.
SHIPPED_DAMAGE = {
    ("m/MS7F02.BIN", "0:0C"): ("され", "was"),
    ("m/MS7F01.BIN", "0:0A"): ("ま{08:66}", "not"),
}


def _rows(tree):
    out = {}
    for p in tables.iter_tables(tree):
        for r in tables.read(p):
            out[(r.file, r.rec, r.idx)] = r
    return out


def test_promoted_pool_english_is_only_ever_a_whole_sentence():
    """The rule, as of 2026-09-11, is per row and not per file.

    A pool record that is a whole sentence cannot be spliced mid-clause by
    construction -- the engine has to call it where a sentence can start -- so
    refusing the entire family was wider than the argument supports.  What a
    promoted pool row must satisfy: its reading ends 。！？, or its bytes end
    the line (a trailing ``\\n`` or a ``{1E10:..}`` page wait); and the
    reference closes in English too.  Anything else is still a fragment and is
    still refused.
    """
    if not os.path.isdir(DRAFT):
        return                      # tree not generated in this checkout
    src, draft = _rows(SRC), _rows(DRAFT)
    promoted, bad = [], []
    for key, r in draft.items():
        if r.file not in POOL or not r.en.strip():
            continue
        s = src.get(key)
        if s is not None and s.en.strip():
            continue                # a person wrote it; untouched
        promoted.append(r)
        if s is None or not make_draft_tree._pool_row_is_a_whole_line(s):
            bad.append((r.file, r.rec, r.jp, r.en))
    assert not bad, (
        "%d promoted pool row(s) are not whole sentences: %s"
        % (len(bad), bad[:6]))
    # ...and the rule is not vacuous: it lets the battle lines through
    assert len(promoted) >= 50, "only %d pool rows promoted" % len(promoted)
    assert sum(1 for r in promoted if r.file == "m/MS7F06.BIN") >= 50


def test_the_fragments_are_still_refused_as_a_class():
    """The other side of the same rule: most of the pool is not a sentence and
    none of it may take a reference."""
    if not os.path.isdir(DRAFT):
        return
    src, draft = _rows(SRC), _rows(DRAFT)
    leaked = []
    for key, s in src.items():
        if s.file not in POOL or s.en.strip() or not s.ref_en.strip():
            continue
        if make_draft_tree._pool_row_is_a_whole_line(s):
            continue                # allowed by the rule above
        d = draft.get(key)
        if d is not None and d.en.strip():
            leaked.append((s.file, s.rec, s.jp, d.en))
    assert not leaked, (
        "%d pool fragment(s) took a reference translation: %s"
        % (len(leaked), leaked[:6]))


def test_the_row_rule_reads_the_expansion_not_the_bytes():
    """``{08:90}し{08:15}`` has no ``？`` in it; it *draws* どうしますか？.

    The rule has to ask the reading, which is the same correction the
    pre-fill needed.  Both halves are asserted, including the refusal of a
    reference that does not close in English.
    """
    class R:
        def __init__(self, jp, ref_en):
            self.jp, self.ref_en = jp, ref_en

    assert make_draft_tree._pool_row_is_a_whole_line(
        R("{08:90}し{08:15}", "What will you do?"))
    # same Japanese, an English fragment: refused
    assert not make_draft_tree._pool_row_is_a_whole_line(
        R("{08:90}し{08:15}", "what will you"))
    # the two that reached the screen: neither is a sentence
    assert not make_draft_tree._pool_row_is_a_whole_line(R("され", "was"))
    assert not make_draft_tree._pool_row_is_a_whole_line(R("ま{08:66}", "not"))
    # a name is not a sentence either
    assert not make_draft_tree._pool_row_is_a_whole_line(
        R("ニュートン", "Newton"))
    # the line-ending forms, whose reading does not end in 。！？
    assert make_draft_tree._pool_row_is_a_whole_line(
        R("逃げられ{08:19}！" + NL + "{1E10:010214}",
          "Failed to run away!" + NL + "{1E10:010214}"))


def test_the_two_fragments_that_reached_the_screen_are_gone():
    """Named rather than folded into the count above, because these are the
    evidence: a player saw both, in one sentence, in the same session."""
    if not os.path.isdir(DRAFT):
        return
    draft = _rows(DRAFT)
    for (rel, rec), (jp, bad) in SHIPPED_DAMAGE.items():
        hit = [r for (f, rc, _i), r in draft.items() if f == rel and rc == rec]
        assert hit, "%s %s no longer exists; the row ids moved" % (rel, rec)
        r = hit[0]
        assert r.jp == jp, "%s %s reads %r, expected %r" % (rel, rec, r.jp, jp)
        assert r.en.strip() != bad, "%s %s is back to %r" % (rel, rec, bad)


def test_hand_written_pool_english_is_untouched():
    """The rule must not cost the translations that make the game readable.

    The pool English worth having is names and nouns, and a person picked those
    deliberately in ``tables/``.  Holding back the promotions costs 202 rows;
    these are the ones it must not touch.

    The floor moved 100 -> 70 on 2026-09-11 and the reason is not a loss: 25 of
    the rows it was counting held ``en == jp`` on a span that is nothing but
    pool calls, a pre-fill the extractor wrote because the bytes contain no
    Japanese *characters*.  Deciding that on the pool-expanded reading instead
    empties them, and nothing changes on screen -- an unserved span draws its
    own bytes, which call the pool records the overlay does translate.
    """
    if not os.path.isdir(DRAFT):
        return
    src, draft = _rows(SRC), _rows(DRAFT)
    kept = 0
    for key, s in src.items():
        if s.file not in POOL or not s.en.strip():
            continue
        d = draft.get(key)
        assert d is not None and d.en == s.en, (
            "%s %s: tables/ says %r, the draft tree says %r"
            % (s.file, s.rec, s.en, d.en if d else None))
        kept += 1
    assert kept >= 70, "only %d hand-written pool rows survive" % kept


def test_neither_grammar_heuristic_would_have_worked():
    """Pinned so nobody re-invents them.

    ``はい`` -> "Yes" is pure hiragana and correct, so a hiragana test would
    refuse good English.  ``ま{08:66}`` -> "not" carries a pool call and is
    grammar, so a "has a macro means it is a word" test would let the damage
    through.  Both are read from the live tables rather than asserted from
    memory, so this fails if either row changes.
    """
    src = _rows(SRC)
    kana = re.compile(r"^[ぁ-ゟ]+$")
    macro = re.compile(r"\{[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\}")

    yes = [r for k, r in src.items() if r.file == "m/MS7F07.BIN" and r.jp == "はい"]
    assert yes and yes[0].en.strip() == "Yes", "はい -> Yes is no longer in tables/"
    assert kana.match(yes[0].jp), "はい is no longer pure hiragana"

    neg = [r for k, r in src.items()
           if r.file == "m/MS7F01.BIN" and r.rec == "0:0A"]
    assert neg and macro.search(neg[0].jp), (
        "m/MS7F01 0:0A no longer carries a pool call; the second heuristic's "
        "counter-example is gone and this test needs a new one")
