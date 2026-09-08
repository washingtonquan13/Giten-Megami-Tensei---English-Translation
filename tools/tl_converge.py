"""Confirm v0.05-copied rows whose translation is *forced*, using our own evidence.

16,466 rows still carry Sneikkimies' v0.05 English verbatim.  Retranslating all
of them costs ~2,500 tokens each, and the pilot showed **35% come back
identical** -- because `男性：` has one sensible English and an LLM cannot improve
on `Man:`.  Paying to regenerate those is waste.

So: where we have *independently* rendered the identical Japanese somewhere else
and produced the identical English, the v0.05 row is confirmed, and marking it
`reviewed` is a statement of fact rather than an assumption.

    python tools/tl_converge.py            # report only
    python tools/tl_converge.py --write    # mark the confirmed rows reviewed

**The evidence base is the whole argument, so it is built narrowly.**

* **tier 1** -- the rows in `build/tl/*.tsv`, translated by agents that were
  handed the Japanese and told explicitly that the v0.05 line was being replaced
  and must not be followed.  These cannot be circular.
* **tier 2** -- rows carrying `ref_src = ours`, our own earlier work.  Weaker:
  that work is itself unreviewed.

Rows whose English came *from* v0.05 are excluded from the evidence entirely,
including the 2,803 with `ref_src = v005` that were merely edited rather than
copied -- a lightly-reworded v0.05 line is not independent evidence that v0.05
was right.

**RESULT, 2026-09-08: the cheap win is not there.**  Tier 1 confirms **zero**
rows.  The 35% convergence measured during the pilot was an artifact of measuring
*inside* the pilot files, where the rows we had just written and the v0.05 rows
left over share Japanese strings; corpus-wide our 469 rows cover only 194
distinct strings and none of them lands on a v0.05-copied row.  Tier 2 confirms
2,341, but that rests on our own unreviewed drafts -- defensible only because the
user's standard is "our drafts are good enough"; it is a judgement, not a proof.
**11,472 rows have no evidence either way and simply have to be translated.**

**So the valuable output is the disagreements, not the confirmations.**

* **427 real disagreements with v0.05** where the tokens match and the wording
  does not, so one side is wrong -- and it is usually v0.05: `猫じゃらしを振る` is
  "wave the cat teaser", not `Kitty Stone`; `ＭＡＧ` is MAG, not `Magnetite`.
  Only 7 of the 434 are mere convention differences (a spelled-out name against a
  kept `{08:xx}` call), so this list is almost pure signal.
* **430 Japanese strings we have rendered inconsistently *ourselves*** -- a defect
  in our own tables that nothing else was looking for.  `宝石` is both "Gemstone"
  and "Gem"; `魔石` is both "Magic Stone" and "Magic stone"; and `他の物` is
  rendered "Gemstone" in one place and "Other" in another, which is simply wrong.

Neither list is auto-fixed.  Both are worked by a human or an agent, and both are
far cheaper per row than retranslating blind.
"""
from __future__ import annotations

import collections
import glob
import io
import os
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)

from giten import paths, script, tables

DRAFT = os.path.join(paths.BUILD_DIR, "tables_draft")
WRITE = "--write" in sys.argv
#: note appended to a row this pass confirms, so the claim stays auditable
MARK = "@converged"


def is_v005_copy(r) -> bool:
    return (r.edited and r.ref_en and r.en == r.ref_en
            and r.status != "reviewed"
            and (r.ref_src or "").strip() == "v005")


# ---- tier 1: the exact rows our agents wrote, read back from the answer files
tier1_keys = set()
for path in glob.glob(os.path.join(paths.BUILD_DIR, "tl", "*.tsv")):
    if "badtokens" in os.path.basename(path):
        continue                                   # the rejected first pass
    rel = "m/%s.BIN" % os.path.basename(path).split(".")[0]
    for line in io.open(path, encoding="utf-8"):
        if not line.strip():
            continue
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3:
            tier1_keys.add((rel, p[0].strip(), int(p[1])))

rows = [r for p in tables.iter_tables(DRAFT) for r in tables.read(p)]
by_key = {(r.file, r.rec, r.idx): r for r in rows}

tier1 = collections.defaultdict(collections.Counter)
tier2 = collections.defaultdict(collections.Counter)
for r in rows:
    if not r.edited or not (r.jp or "").strip() or is_v005_copy(r):
        continue
    if (r.file, r.rec, r.idx) in tier1_keys:
        tier1[r.jp][r.en] += 1
    elif (r.ref_src or "").strip() == "ours":
        tier2[r.jp][r.en] += 1

targets = [r for r in rows
           if is_v005_copy(r) and script.NOEDIT_NOTE not in (r.note or "")]

confirmed, weak, conflict, unseen = [], [], [], []
for r in targets:
    if r.jp in tier1:
        (confirmed if r.en in tier1[r.jp] else conflict).append(r)
    elif r.jp in tier2:
        (weak if r.en in tier2[r.jp] else conflict).append(r)
    else:
        unseen.append(r)

print("v0.05-copied rows in scope            : %d" % len(targets))
print("  tier 1 evidence (this pilot's rows) : %d distinct Japanese strings" % len(tier1))
print("  tier 2 evidence (ref_src = ours)    : %d" % len(tier2))
print()
print("CONFIRMED by tier 1 -- safe to mark reviewed : %d" % len(confirmed))
print("confirmed by tier 2 only -- weaker           : %d" % len(weak))
print("CONFLICT: we rendered it differently         : %d" % len(conflict))
print("never rendered by us -- must be translated   : %d" % len(unseen))
print()

# our own renderings that disagree with each other: a defect nothing else checks
selfconf = {jp: c for jp, c in list(tier1.items()) + list(tier2.items()) if len(c) > 1}
print("Japanese strings WE have rendered inconsistently: %d" % len(selfconf))
for jp, c in list(selfconf.items())[:6]:
    print("   %-22s -> %s" % (jp[:22], ", ".join(repr(k[:26]) for k in list(c)[:3])))
print()
print("conflicts with v0.05 (v0.05 is usually the wrong one):")
seen = set()
for r in conflict:
    if r.jp in seen:
        continue
    seen.add(r.jp)
    alt = tier1.get(r.jp) or tier2.get(r.jp)
    print("   %-20s v005=%-26r ours=%s"
          % (r.jp[:20], r.en[:26], ", ".join(repr(k[:24]) for k in list(alt)[:2])))
    if len(seen) >= 10:
        break

if not WRITE:
    print("\n(report only -- pass --write to mark the %d confirmed rows reviewed)"
          % len(confirmed))
    raise SystemExit(0)

mark = {(r.file, r.rec, r.idx) for r in confirmed}
touched = 0
for p in tables.iter_tables(DRAFT):
    all_rows = tables.read(p)
    n = 0
    for r in all_rows:
        if (r.file, r.rec, r.idx) not in mark:
            continue
        r.status = "reviewed"
        note = (r.note or "").strip()
        if MARK not in note:
            r.note = (note + "; " if note else "") + MARK
        n += 1
    if n:
        tables.write(p, all_rows)
        touched += n
print("\nmarked %d rows reviewed (note %r)" % (touched, MARK))
