# Combat: what we have not read, and what to do about it

Written 2026-09-09, after a week of combat work that produced a correct account
of turn scheduling, the input gate, the target-list builder and the status tick.

Then somebody asked whether the whole combat loop had been investigated. It had
not, and the gap was much larger than it felt from inside:

    python tools/combat_coverage.py [--unnamed]

| region | functions | named at first measurement | named now |
|---|---|---|---|
| battle module (`0x0042A000`-`0x0042E000`) | 81 | 9 (11%) | 12 (15%) |
| enemy AI / actor (`0x0040DC00`-`0x00410000`) | 74 | 7 (9%) | 10 (14%) |
| unit state / status (`0x0043E000`-`0x00440000`) | 75 | 5 (7%) | 18 (24%) |
| battle command UI (`0x0041D000`-`0x0041E000`) | 13 | 1 (8%) | 1 (8%) |
| attack / damage (`0x00406000`-`0x0040C000`) | 142 | not measured | 31 (22%) |
| **total** | **385** | **22 of 243 (9%)** | **72 (19%)** |

The middle column is the first measurement; the last is after items 2, 3 and 4
were answered. One session on the two busiest unnamed functions moved the
unit-state region from 7% to 24%, which is the argument for picking targets by
call-site count rather than by curiosity.

**The last row was added on 2026-09-09 and is a correction, not progress.** The
attack, damage and accuracy routines live in a region the tool was not looking
at, so every figure above the line silently excluded the arithmetic centre of
combat. The denominator is 142 functions larger than it should always have been.
The total went *up* only because the same session that noticed the gap also
named 31 of them.

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
(`format-notes.md` §7). The damage formula, the accuracy roll and the eleven
battle outcomes (`combat-damage.md`).

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

### 3. ~~The damage formula~~ and ### 4. ~~To-hit, graze, "could not damage"~~ -- ANSWERED 2026-09-09

Done as one pass, because they share an entry point. Written up in
[`combat-damage.md`](combat-damage.md). The headline:

    damage = sqrt(max(atk - 0.2*def, 0)) * (atk/def + 2.2 or 1.0)
             * situational multipliers
             * weapon power% * cycle-row% * random 80..120%

`0x0040A270` is the physical damage formula and `0x00408B40` is its magic twin,
same constants and same shape. `0x0040A490` / `0x00408910` are the accuracy
rolls, and `0x0042AC90` is the action resolver that calls them -- which also
reloads the ATB gauge (`actor+0x17F = 0xFF`), independently confirming
`combat-pacing.md` section 1.

**The inference in the old item 4 was half right.** "Could not damage" *is* a
damage result of zero. A graze is **not**: it is a hit quality picked by the
accuracy roll before any damage exists, which then multiplies the damage by
0.25. It prints its number like any other hit, so the same swing can read
"grazed for 6" or "hit for 24".

The print path turned out to be script-side, which is why searching the exe for
it failed: `1F E8 03 nn <expr>` assigns to one of 26 script registers at
`0x004815E0`, expression node `0x4B` reads one of four battle-result globals,
and `1F 02` prints a register as full-width digits. `m/MS00DD` record `0x05` is
a plain switch from the outcome code `ds:0x00491994` onto eleven message
records.

**Left open by that pass** (details in `combat-damage.md` section 6): the three
actor/target relation tests `0x004085A0`, `0x00408610`, `0x004086D0` that gate
four multipliers, and outcomes 6..10. The outcome table *is* checked against a
recorded trace (section 7, and it caught an error there); the arithmetic is
not.

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

**Narrowed 2026-09-09.** There *is* a stat-scaling path, `0x0043DA90`, and it is
not this one: it is hardcoded at 50% and 150% and keyed on status flags `0x23`,
`0x24`, `0x25`, touching the four accuracy stats and the attack/defence pair
(`combat-damage.md` §5). Whatever the magnitude field feeds, it is somewhere
else. The four multiplier gates named in `combat-damage.md` §6
(`0x004085A0`, `0x00408610`, `0x004086D0`) are the next place to look.

### 8. The unit stat block

`unit+0x48`..`+0x58` is unidentified. `+0x5B` is compared against `rand()%100` at
`0x0042B5A1`, so at least one entry is a percentage. Speed is `unit+0x5E` /
`enemy+0x78` and is known; the rest is not.

Six further fields were named on 2026-09-09 (`combat-damage.md` §4): `+0x12A`
accuracy, `+0x12C` attack, `+0x12E` evade, `+0x130` defence, `+0x136` magic
accuracy, `+0x13A` magic evade, `+0x13C` magic defence. Also `+0x17F` the ATB
gauge, `+0x181` action kind, `+0x186` hit quality, `+0x187` pending HP delta,
`+0x18B` pending MP delta. **None of these is joined to the `p/` record yet** --
they are runtime fields, and finding what fills them is the natural next step
for this item.

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

It is the answer to "do we understand combat?", which is **no -- 19% of it** --
written down so that the next person to ask gets a number instead of a summary
of the parts that happen to be well understood. Read that 19% against the 9%
first measured only with care: the denominator changed on 2026-09-09 when the
attack and damage region was added, so the two numbers are not the same
measurement.
