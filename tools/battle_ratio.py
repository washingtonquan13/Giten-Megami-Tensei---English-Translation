"""Count party actions against enemy actions in a trace, reliably.

    python tools/battle_ratio.py <trace.bin> [--build DIR]

`docs/todo.md` records three attempts at this question from the glyph log that
returned 1 : 1.38, 1 : 1.75 and 1 : 6.56 -- on the same data. The reasons were
all the same shape: the log is *rendered text*, so the answer depended on
pattern-matching English prose that varies by weapon, merges across
back-to-back draws, and mixes in status results that belong to somebody else's
turn.

This counts something the engine decides instead. `m/MS00DE.BIN` is the
attack-announcement file, and several of its records carry **both directions of
the same attack as different alternates within the record**::

    r29[1]  slashed at the enemy!            <- the party swung
    r29[2]  came slashing at you!            <- the enemy swung

So the direction is a span index, chosen by the engine before a single glyph is
drawn. The trace records which span ran. Nothing here parses prose, and a
change to the English cannot move the numbers.

**Ambiguous alternates are not counted, deliberately.** `r04[5]`
("'s {04:02} opened fire") and `r03[5]` ("'s attack") are used by both sides,
so folding them in either direction would be an invention. They are reported
under "unattributed" instead -- a number you can see rather than one silently
folded into the answer. Same for the "confused" alternates (a charmed unit
attacking an ally or itself), which belong to neither side cleanly.

The trace is **truncated every time the game launches**, so run this against a
copy, not against `play/en/ddswin/trace.bin` while the game is open. Archive
anything worth keeping in `traces/`.
"""
from __future__ import annotations

import collections
import os
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)

from giten import paths, tables  # noqa: E402
from giten.trace import core  # noqa: E402

ANNOUNCE = "m/MS00DE.BIN"
RESULT = "m/MS00DD.BIN"

#: unambiguous outcome records in the battle-result file, for context
RESULTS = {(0x51, 0): "won through the battle",
           (0x4F, 0): "was defeated!",
           (0x4C, 0): "HP of damage"}

#: (record, span) the engine picks when a PARTY member attacks.  The English is
#: the current table text and is here to be read, not matched against.
PARTY = {
    (0x05, 4): "attacked the enemy!",
    (0x06, 4): "swung {04:01} down at the enemy!",
    (0x07, 4): "thrust at the enemy",
    (0x08, 4): "whips the enemy",
    (0x0C, 2): "cast at the enemy: {04:00}",
    (0x29, 1): "slashed at the enemy!",
    (0x2A, 1): "cut into the enemy!",
    (0x2B, 1): "bears down on the enemy",
}

#: ... and when an ENEMY attacks the party.
ENEMY = {
    (0x02, 10): "came at you, slashing with {04:01}",
    (0x05, 7): "lunged at you",
    (0x06, 7): "came swinging {04:01} at you",
    (0x0C, 4): "cast this way: {04:00}",
    (0x23, 2): "'s cold hand touched you",
    (0x26, 2): "bared its fangs and lunged at you",
    (0x27, 2): "came clawing at you",
    (0x29, 2): "came slashing at you!",
    (0x2A, 2): "cut into you!",
    (0x2B, 2): "bears down on you",
}


def _text():
    out = {}
    for p in tables.iter_tables(os.path.join(paths.REPO_ROOT, "tables")):
        for r in tables.read(p):
            if r.file == ANNOUNCE:
                out[(int(r.rec.split(":")[1], 16), r.idx)] = (r.en or r.jp or "").strip()
    return out


def count(trace_path: str, build: "str | None" = None):
    """``(party, enemy, unattributed)`` counters keyed by ``(rec, span)``.

    An *entry* is a token whose ``(file, record, span)`` differs from the one
    before it -- one per announcement, not one per glyph.
    """
    evs = core.decode(trace_path, build or paths.ORIGINAL_DDSWIN)
    party, enemy, other = collections.Counter(), collections.Counter(), collections.Counter()
    result = collections.Counter()
    prev = None
    for e in evs:
        key = (e.rel, e.rec, e.span)
        same, prev = key == prev, key
        if same or e.span is None:
            continue
        if e.rel == RESULT and (e.rec, e.span) in RESULTS:
            result[(e.rec, e.span)] += 1
        if e.rel != ANNOUNCE:
            continue
        k = (e.rec, e.span)
        (party if k in PARTY else enemy if k in ENEMY else other)[k] += 1
    return party, enemy, other, result


def main(argv):
    if not argv:
        raise SystemExit(__doc__.strip().splitlines()[2].strip())
    path = argv[0]
    build = argv[argv.index("--build") + 1] if "--build" in argv else None
    party, enemy, other, result = count(path, build)
    txt = _text()
    p, e = sum(party.values()), sum(enemy.values())

    print("%s\n" % os.path.basename(path))
    print("  party actions : %4d" % p)
    print("  enemy actions : %4d" % e)
    if p and e:
        print("  ratio         : 1 : %.2f  (enemy actions per party action)" % (e / float(p)))
    elif e:
        print("  ratio         : the party never acted")
    print()
    for name, c in (("party", party), ("enemy", enemy)):
        if not c:
            continue
        print("  %s:" % name)
        for (rec, span), n in c.most_common():
            print("     r%02X[%-2d] %4d  %s" % (rec, span, n, (PARTY | ENEMY)[(rec, span)]))
        print()
    if result:
        print("  outcome (unambiguous, either side):")
        for k, n in sorted(result.items()):
            print("     %-24s %4d" % (RESULTS[k], n))
        print()
    if other:
        print("  unattributed (both sides use these, or a charmed unit -- not counted):")
        for (rec, span), n in other.most_common(12):
            print("     r%02X[%-2d] %4d  %s"
                  % (rec, span, n, txt.get((rec, span), "?")[:52].replace("\\n", "")))


if __name__ == "__main__":
    main(sys.argv[1:])
