# Combat: what we have not read, and what to do about it

Written 2026-09-09, after a week of combat work that produced a correct account
of turn scheduling, the input gate, the target-list builder and the status tick.

Then somebody asked whether the whole combat loop had been investigated. It had
not, and the gap was much larger than it felt from inside:

    python tools/combat_coverage.py [--unnamed]

| region | functions | named at first measurement | named now |
|---|---|---|---|
| battle module (`0x0042A000`-`0x0042E000`) | 81 | 9 (11%) | 10 (12%) |
| enemy AI / actor (`0x0040DC00`-`0x00410000`) | 74 | 7 (9%) | 10 (14%) |
| unit state / status (`0x0043E000`-`0x00440000`) | 75 | 5 (7%) | 18 (24%) |
| battle command UI (`0x0041D000`-`0x0041E000`) | 13 | 1 (8%) | 1 (8%) |
| **total** | **243** | **22 (9%)** | **39 (16%)** |

The second column is the same afternoon, after item 2 below was answered. One
session on the two busiest unnamed functions moved the whole module from 9% to
16%, and the unit-state region from 7% to 24% -- which is the argument for
picking targets by call-site count rather than by curiosity.

"Named" means *mentioned anywhere in `docs/*.md`*, which is a generous proxy for
understood. The real figure is no higher and probably lower.

**Nothing already documented is wrong because of this.** The threads that were
followed were followed properly, and `combat-pacing.md` §0 is a retraction for
the one that was not. But four narrow threads through a large module is not a
survey of it, and "we understand combat" would be an overstatement.

Re-run the tool after any session. If the count has not moved, that session
answered a question rather than mapping ground -- fine, but worth knowing.

---

## What is established

Turn order is an ATB gauge, not a scheduler (`combat-pacing.md` §1). An open
message window hard-disables the command UI (§2). `0x0042C740` builds a
multi-hit target list and is *not* a scheduler (§0, a retraction). Status slots
tick from a rate table that the port left alone (`pc98-comparison.md` §3b). The
demon and skill record layouts, including the affinity join
(`format-notes.md` §7).

Everything below is not.

---

## The list, in the order worth doing

### 1. Which state does a battle actually run in?

**Why it matters most:** states 11 and 34 tick the enemy gauge **every frame**;
state 16 ticks it **every fourth** (`combat-pacing.md` §1). So this single fact
decides whether enemies fill at 1x or 4x the party rate, and it is currently
unknown.

**How:** log `ds:0x0047BB70` once per frame during a fight. One instrumented
play-test; the tracer infrastructure already exists.

### 2. ~~The two hub functions nobody has named~~ -- ANSWERED 2026-09-09

    0x0043FE70   92 call sites
    0x0043FEB0   78 call sites

**They are the identity layer**, and naming them did exactly what was hoped:
`0x0043FE70(id)` resolves a unit id to its struct through a 32-entry roster at
`0x004910A0`, and `0x0043FEB0(id)` returns field 0 of that struct. Written up in
[`format-notes.md`](format-notes.md) §8, together with the 6-entry active-party
table at `0x00491092`, the registration setter `0x0043FED0`, and the universal
lookup `0x0042ABE0` that handles the negative-id party space as well.

That also explains the sign convention that had been noticed but not understood:
party members are negative ids, roster entries are `0..31`, and the two spaces
are disjoint.

**Still open from this thread:** what field 0 actually is. It is read 78 times
and compared against `0x20`; the low range appears to mean a human party member.
Worth its own pass.

Next tier, same reasoning: `0x0043EDD0` (38), `0x0043FF40` (37, party slot
lookup, partly known), `0x0042ABE0` (33, combatant by id, partly known),
`0x0043EE80` (31), `0x0043E080` (25), `0x0043EDF0` (24), `0x0043E6D0` (24),
`0x0040DEA0` (24).

### 3. The damage formula

**The centre of combat, and completely unread.** We know affinity scales it
(measured), weapon power feeds it (measured), and Tarunda cuts it -- Swallow
Blade went 22 -> 6 across one debuff in a logged fight. We have never read the
code that produces a number.

**Started 2026-09-09, not finished.** What is established so far:

* **The damage number is printed by the script, not the exe.** Only 20 sites
  call the record-runner `0x00439330` and none of them emits the damage line, so
  `m/MS00DD` runs as an ordinary script and the number arrives as a runtime
  substitution.
* `m/MS00DD` rec `0x4C` opens with two runtime-print tokens before any text:

        0x0000   1F E8 03 08 4B 00 01
        0x0007   1F 02 03 08
        0x000B   03 0D                  {03:0D} -- the "HP" pool fragment
        0x000D   のダメージを            (text)

  so the number comes out of the `1F E8` or `1F 02` token.
* The `1Fxx` family is "print a runtime value" -- `giten/vmops.py` documents
  `1F01` as *print a runtime string (a name, a number, ...)*, selector byte plus
  an expression.

**The next step, teed up:** resolve the handler for dispatch index `0x102`
(`1F 02`; `ESCAPE[0x1F] = 0x100` in `vmops.py`) and read which global it prints.
`exec_token` at `0x00439020` dispatches opcodes through `0x0042FF50`; expressions
evaluate at `0x00436B00` via the byte map at `0x00437380` into the jump table at
`0x00437288`. **Whatever writes that global is the tail of the damage formula**,
and everything upstream of it is arithmetic over fields already mapped.

### 4. To-hit, graze, and "could not damage"

Three distinct outcomes counted empirically in play logs -- clean hit, "was only
grazed" (`MS00DD` r0C), "It could not damage" (r0B), plus "dodged it" (r0A) --
and the code that chooses between them has never been read. Whether a graze is a
hit-quality roll or a damage result floored near zero is **inference**.

Pairs naturally with item 3 -- and the same entry point serves both, since
"could not damage" is what the damage routine emits when its result lands at
zero. Do them as one pass.

### 5. The enemy AI

`0x0040F890` gates one enemy's turn; `0x0040F9D5` then dispatches 11 ways on
`[esi+0x1E0]` through a table at `0x0040FCF4`. How an enemy picks a skill and a
target is unknown. Relevant to any future balance question and to the
`battle_ratio.py` gun-line attribution.

### 6. Resolve the `+0x0C` contradiction

`combat-pacing.md` §0 calls `ET0004 +0x0C` a packed hit-count nibble.
`format-notes.md` §7.1 calls it the element index, with ten values matching ten
affinity bytes and Salamander confirming independently. **Both cannot be right.**

Either `0x00423460` returns a record that is not the `ET0004` one, or the
argument mapping in the pacing doc is off by a field. Flagged in both documents;
cheap to settle by reading `0x00423460`.

### 7. What buff and debuff magnitude actually multiplies

The port moved Tarukaja `+0x0B` 8 -> 10 and Tarunda 8 -> 5. We do not know what
those numbers scale, so we cannot say how much the port's change is worth.

### 8. The unit stat block

`unit+0x48`..`+0x58` is unidentified. `+0x5B` is compared against `rand()%100` at
`0x0042B5A1`, so at least one entry is a percentage. Speed is `unit+0x5E` /
`enemy+0x78` and is known; the rest is not.

### 9. The rest of state 24

Sub-state 0 was read in detail, 1-6 were skimmed, **7 and 8 were never read**
(`0x0042BDEA`, `0x0042BE7C`). Also unread: the nine enqueue sites in
`0x0042C8xx`-`0x0042CBxx` that build the target pool, and `0x0042C9E0`, the
sub-effect the `m == 0xF` target mode calls.

### 10. Remaining record fields

`p/` demon record: `+0x02`, `+0x20` (0..33), `+0x22`..`+0x34` (ids outside the
`ET0004` range, possibly drops), `+0x63`..`+0x79`.
`ET0004`: `+0x02`, and **`+0x05` -- the single most-changed field in the port's
rebalance (25 records) and still unidentified.**
`et/ET0028`: 256 booleans, 16 flipped by the port, meaning unknown.

### 11. The PC-98 overlay map

`DDS98.EXE` routes most inter-module calls through **404 `INT 3Fh` overlay
thunks**, so direct call scans find leaf functions but never their callers. That
single obstacle blocks two open questions: whether the PC-98 has the same enemy
cadence divisor, and whether its status code indexes the rate table the same way
(`pc98-comparison.md` §3b).

Lowest priority -- it only serves comparison questions, not the patch -- but it
is the one blocker that unlocks more than one item.

---

## What this list is not

It is not a prerequisite for anything currently shipping. The ATB restoration is
measured and play-tested, the translation pipeline does not touch combat, and
none of the open items above casts doubt on a shipped claim.

It is the answer to "do we understand combat?", which is **no -- 16% of it, up
from 9%** -- written down so that the next person to ask gets a number instead of
a summary of the parts that happen to be well understood.
