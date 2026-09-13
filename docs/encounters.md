# Random encounters, and what a demon drops

Written 2026-09-12 to answer one question — *where do I farm Topaz and
Diamond?* — and the answer needed three tables and two corrections to what this
project already believed. House style as in `format-notes.md`: every claim
carries its evidence and a guess is labelled `[conjecture]`.

**The short version.** Encounters are not per map and not per step. They are
keyed on the player's **world position** in a single continuous Tokyo of 6 x 9
areas; one file per area holds a 9 x 5 grid of cells; each cell names an
encounter group and a chance byte. The *same* grid, in another file, holds the
district name the location strip draws — so "which demons" and "what the player
sees at the top of the screen" come out of one index. And a demon's drop is one
item at `p/P####.BIN` `+0x32` with its rate at `+0x67`; the block at
`+0x22`..`+0x31` this project had pencilled in as a drop list is the demon's
**equipment**, and `+0x34` is its **species id**, not an item.

Tool: `tools/encounters.py`.

---

## 1. The check **[VERIFIED by disassembly]**

`0x00419C70` — the field state handler — calls

    0x00411030(word ds:0x00468A48, word ds:0x00468A4C)      ; player world x, y

and that is the **only** call site of `0x00411030`, so this is the whole random
encounter path. In order:

| address | what |
|---|---|
| `0x00411036` | `0x0043FE70(0)` (roster slot 0) `+0x1C8`, then `0x0040B6D0(p, 0x22)`; **if bit 34 is set, no encounter** — the script's "encounters off" switch |
| `0x0041105C` | `0x00411130`: the clock gate (below). Fails → return |
| `0x0041107C` | `0x00411170(x, y)`: loads the area file, returns the cell index |
| `0x004110A5` | `0x00439420(cell+1)` — entry 0's condition; if false, `0x004110BC` tries `0x00439420(cell+7)`, entry 1; if that is false too, **no encounter** |
| `0x004110ED` | `0x00411220(cell+3 or +9)`: the chance roll |
| `0x0041111B` | `0x00411280(...)`: pick the demons and how many |

**The gate is the clock, not steps.** `0x00411130` compares `0x004179A0()`
against `ds:0x0047B0E8 + 0x78`. `0x004179A0` is
`minute + 60 * (hour + 24 * day)` — it reads `ds:0x00491560` (u32),
`ds:0x00491567` (u8) and `ds:0x00491568` (u8) and folds them with
`lea eax,[eax+eax*2]` / `lea eax,[ecx+eax*8]` / `*3 / *5 / *4`, which is
`0x491568 + 60*(0x491567 + 24*0x491560)`. So **one encounter check per 120
in-game minutes**, and `ds:0x0047B0E8` is the last-check timestamp.
**A second off-switch, in the same routine**: when `ds:0x004919EC & 0x10` is set
(`0x00411136`) the threshold is built from the clock read *now* plus 120, and the
very next read is then always below it — so the test can never pass and the
timestamp is never updated. That bit disables random encounters outright.

**`0x0040B6D0(base, bit)`** is a plain bit test: `byte[base + bit/8] & mask[bit&7]`
against the mask table at `0x00464280`, returning 0/1. The unit's 32-byte flag
block is at `unit+0x1C8` — the same block `0x004392B0` reaches as "bank 0xE",
and the same 32 bytes `0x00410761` zeroes when a combatant is built.

---

## 2. Addressing: world position → file and cell **[VERIFIED by disassembly]**

The world is one coordinate space. Two routines split it:

    0x0040CCF0(x, y)  = (x / 288) + 8 * (y / 200)         ; the AREA number
    0x0040CCC0(x, y)  = (x % 288, y % 200)                ; position inside it

and `0x00411170` uses both:

    ebx = 0x0040CCF0(x, y)
    ebx += 0x1000
    0x00401DD0(ebx, kind 12, 0)   ->  et\et%.4x.bin       ; 0x00411195..0x004111A5
    ...
    return (x % 288) / 32 + 9 * ((y % 200) / 40)          ; 0x004111EE..0x0041121A

So:

* **area number `a` → `et/ET1<aa>.BIN`**, `a = (x/288) + 8*(y/200)`;
* **cell = `cellx + 9 * celly`**, cells 32 wide and 40 tall, **9 across, 5 down,
  45 per area**.

Kind 12 is `et\et%.4x.bin`: the jump table at `0x00402208` sends kind 12 to
`0x004020BA`, which `sprintf`s the format string at `0x004682C4`. (`format-notes.md`
§4 lists kind 11 and not 12; both produce the same template, and kind 13 is
`gd%.4x.bin`, not `et\id%.4x.bin` — `0x004682D8`. That table needs the
correction.)

**The 54 files that exist are exactly the 54 grid squares `cx` 1..6, `cy` 1..9.**
`ET1009`..`ET100E`, `ET1011`..`ET1016`, … `ET1049`..`ET104E`. Columns 0 and 7
and row 0 have no file, and `0x00411170` has no NULL check, so the playable
world is bounded to those 54 areas — corroborated in §7: the district grid for
every area outside them is entirely blank.

`ET10FF.BIN` is not an area. It is 33 bytes = 11 rows of 3, indexed by the
cell's byte `+0` at `0x004114C0`, and its three bytes become the battle
**background**: `0x004114E7` calls `0x004144C0(0x5000 + row[0], row[1], row[2])`.

### 2.1 These files are stored in the clear

`0x00401D40` — the reader every table in this section goes through — reads the
u16 header and `fread`s the body straight into the buffer. It never calls
`0x00401B20` (seed) or `0x00401BA0` (decrypt), which `0x00401C30` does. So
`et/ET0021.BIN`, `et/ET10xx.BIN` and `et/ET0100.BIN` are **plaintext inside the
container framing**, and `giten.container.split` — which always decrypts —
returns garbage for them. `tools/encounters.py._plain` is the correct reader.
This is a property of the *loader*, not of the `et` family: `et/ET0001.BIN`
goes through `0x00401C30` and *is* encrypted.

This is why the 13-byte structure looked like "a repeating run of small values"
and never resolved: it was being read one XOR out of phase.

---

## 3. The 13-byte cell **[VERIFIED by disassembly]**

`0x004110CE`..`0x0041111B` reads, with `g` = 0 or 1 and the group block at
`1 + 6*g`:

| offset | size | what | evidence |
|---|---|---|---|
| `+0x00` | u8 | **battle background row** into `ET10FF` | `0x004110D1` → `ds:0x0047B0AC`, consumed at `0x004114C0` |
| `+0x01` / `+0x07` | u16 | **condition** for this entry | `0x004110A0`/`0x004110B2` → `0x00439420` |
| `+0x03` / `+0x09` | u8 | **encounter chance byte** (§3.2 — a bias, not a percentage) | `0x004110E4` → `0x00411220` |
| `+0x04` / `+0x0A` | u8 | **party-size bonus** | `0x00411100` → `0x00411280` arg 2 → `0x00411300` |
| `+0x05` / `+0x0B` | u8 | **weight profile**, index into `ET0021` record 1 | `0x0041110F` → `0x004113A0` arg 0 |
| `+0x06` / `+0x0C` | u8 | **encounter group**, index into `ET0021` record 0 | `0x00411114` → `0x004113A0` arg 1 |

`+0x02` and `+0x08` are the high halves of the condition words and are always 0
in the shipped data; nothing reads them separately.

### 3.1 The condition word, and why entry 1 is usually dead

`0x00439420(p)` reads `word[p]`, takes **bank = low byte & 0x7F**, **bit = high
byte**, treats `0xFF7F` as "always true", and otherwise calls
`0x004392B0(bank, bit)`:

    0x004392B0(bank, bit)   if (bank == 0 && bit == 0) return 0          ; hard-coded
                            if (bank == 0xE) return 0x0040B6D0(<player>+0x1C8, bit)
                            return 0x0040B6D0(0x004813A0 + bank*32, bit)

and then inverts: the result is **true when the flag is clear**, unless bit 7 of
the low byte is set, which flips it (`0x0043945D`..`0x0043946C`).

So a condition word of **0 is "no condition"** — bank 0 bit 0 is answered 0
unconditionally, and a clear flag is true. Entry 0 therefore wins outright in
every cell whose first word is 0, and **entry 1 is unreachable there**. In the
shipped data entry 1 is `group 1, chance 9, weights 1` in 47 of the 54 areas: a
template default that never runs. Seven areas (17, 25, 26, 33, 34, 41, 49) carry
real flag words — `0x1200`, `0x1300`, `0x0C00`, `0x0F00`, `0x1100`, `0x1180`,
`0x1400`, `0x1500`, `0x1800`, `0x1880`, `0xCF00` — every one of them **bank 0**
(the low byte is `0x00` or `0x80`, and `0x80` only sets the negate bit), with
bit numbers 0x0C..0xCF.  There the live entry depends on the save.

### 3.2 The chance byte is a bias, not a percentage

    0x00411220(rate)
        esi = rate + word ds:0x0047B0BC
        eax = 0x0040B960(1, 100, 2)               ; see below
        if (esi >= eax) { ds:0x0047B0BC = 0; return 1 }
        ds:0x0047B0BC += 1
        if (0x0043FFF0(4) != -1) ds:0x0047B0BC += 1
        return 0

**`0x0040B960(lo, hi, n)` is not a uniform roll.**  It sums `n + 1` calls to
`0x0040B940(hi - lo)` — each `rand() % (hi - lo + 1)` — and returns
`lo + sum / (n + 1)`.  With `n = 2` that is the mean of three rolls, so the
threshold this compares against clusters hard around 50 and a cell byte of 5
almost never fires on its own.

What makes encounters happen is therefore **`ds:0x0047B0BC`**, a global that
grows by one on every failed check and resets to zero on a success: the
effective threshold is `cell byte + failures`, so an area becomes dangerous after
a few dozen checks rather than at a fixed rate.  Calling the byte a percentage
is wrong; it is a head start.  It grows by **two** per failure when
`0x0043FFF0(4)` succeeds — that routine scans roster ids 0..31
for a combatant whose field 0 equals 4 (§6: field 0 is the species id), so
**carrying one particular demon doubles the pity accumulation**. The same test
adds 2 to the enemy count (`0x00411300`) and +10 to the group roll
(`0x004113C3`). Which demon species 4 is, is in the data;
`tools/demon.py`-style lookup on `+0x34` names it.

---

## 4. `et/ET0021.BIN` — the groups **[VERIFIED by disassembly + data]**

Two containers, both read plain (§2.1) by `0x00410FC0`:

| container | bytes | global | shape |
|---|---|---|---|
| 0 | 636 | `ds:0x0047B0C0` | **53 groups x 6 u16**, each `record id - 0x2000` |
| 1 | 50 | `ds:0x0047B0C4` | **8 weight profiles x 6 u8** |

The demon id is the file number minus `0x2000`: `0x00410A20` takes an index,
does `add eax,0x2000` and loads `p\p%.4x.bin` (kind 10). Every one of the 318
values in container 0 resolves to a `p/P####.BIN` that exists.

`0x004113A0(weights_index, group_index)` is the picker — and *its* roll,
`0x0040B960(1, 100, 0)`, **is** uniform 1..100, because `n = 0` sums one call:

    ebx  = body of ET0021 container 1
    edi  = 0x0040B960(1, 100, 0)                   ; 1..100
    if (0x0043FFF0(4) != -1) edi += 10
    ecx  = ebx + 6 * weights_index
    for si in 0..5:  eax += ecx[si];  if (edi < eax) break
    if (si < 6)  return word[ container0 + 12*group_index + 2*si ]
    else         return word[ container0 + 12*(group_index+1) ]

So the six weights are a cumulative distribution over the group's six slots, and
a roll past their sum falls through to **slot 0 of the next group** — which is
why profiles whose six bytes sum to less than 100 (rows 2,3,4,6 do) leak a
harder demon in. Row sums as shipped: 105, 147, 99, 99, 101, 117, 91, 115.

`0x00411280` calls the picker twice — the second call retries up to ten times
while the result equals the first (`0x004112C6`..`0x004112E4`) — and stores the
two ids at `ds:0x004788B8` and `ds:0x004788BA`. `0x00411440(n)` then writes
`n` bytes at `ds:0x004788C0`, each `rand(1..100) < 40`, which selects **which of
the two species each individual enemy is**. So an encounter is at most two
species, roughly 60/40.

**How many enemies**: `0x00411300(bonus)` = `bonus` `+2` if `0x0043FFF0(4)`
succeeds, `+ 0x00411330()`, capped at 16; `0x00411280` then takes
`rand(1 .. that)`. `0x00411330` averages `word[member+0xF4]` over the party
members whose field 0 is below 0x20, and returns `max(1, (50 - average) / 10)` —
so a weaker party meets more enemies. **Which statistic `+0xF4` is, is not
pinned** `[conjecture: a party-wide level or rank]`.

### 4.1 Groups are ordered by level, and 21 of 53 are unused

Mean level per group rises with the index — 4.7 at group 0, 14.3 at 14, 21.0
at 27, 28.7 at 36, 47.2 at 49 — with three deliberate-looking exceptions
(21 sits at 7.7 among the teens, and 50/51/52 restart at 15.2/20.7/24.8). **The cells of the 54 areas name only 32
group indices**: 0,1,2,3,5,6,9..14,17..36. Never named by any cell:
**4, 7, 8, 15, 16 and 37..52**, which includes every group above mean level 30.
Groups 50, 51, 52 are near-duplicates of 23, 25 and 30.

Consequence, and it is the one the farming question turned on: **the random
encounter table tops out around level 30.** Demons above that are reachable
only through scripted battles. This is a statement about the encounter path
only — it does not say those demons are unfightable, it says `0x00411030`
cannot produce them.

---

## 5. The drop **[VERIFIED by disassembly]**

`0x0042B562`..`0x0042B5B5`, in the enemy-death path (`di >= 0` is an enemy):

    edx = [esi+0x72] ; ds:0x0049154C += edx        ; cash
    eax = [esi+0x76] ; ds:0x00491988 += eax        ; magnetite
    ecx = [esi+0x6E] ; ds:0x00491990 += ecx        ; experience
    ax  = 0x0040B940(0x63)                          ; rand() % 100  -> 0..99
    dx  = byte [esi+0x5B]
    if (dx <= ax) goto done                         ; no drop
    ax  = word [esi+0x5C]
    0x00423C20(ax, 1)

`esi` is a combatant pointer **`struct + 0x1A`** — the convention `0x0043FE70`
hands out. That is fixed by three of its own fields: `0x00410470` writes the
record's `+0x00`, `+0x04` and `+0x08` to `struct+0x88`, `+0x8C` and `+0x90`
(`0x004104A7`, `0x004104B0`, `0x004104C8`), and `0x88/0x8C/0x90` minus `0x1A`
is exactly `0x6E/0x72/0x76`. §7 of `format-notes.md` already had `+0x04` as cash
and `+0x08` as Bio-Magnetite from the battle log, so the three accumulators
land on the three fields that were already verified. It also settles §8's open
`[conjecture]`: field 0 of a combatant is `struct+0x1A`, which `0x004104DA`
loads from **record `+0x34`**, and "below 0x20 means a human party member" is
then simply a low species id.

With that offset:

    [esi+0x5B] = struct+0x75 = record +0x67      the DROP RATE, percent
    [esi+0x5C] = struct+0x76 = record +0x32      the DROP ITEM, an ET0001 index

(`0x00410811`: `mov al,[ebx+0x67] ; mov [ebp+0x75],al`.
 `0x00410817`: `mov cx,[ebx+0x32] ; mov [ebp+0x76],cx`.)

The test is `rate > rand()%100`, so the rate **is** the percentage, and values
above 99 — 120, 180, 200, 255 occur — are guaranteed drops.

`0x00423C20(item, count)` files the item into a **16-slot battle-spoils table at
`ds:0x004919A0`** (`{u16 item, u16 count}` per slot), merging into a matching or
empty slot. **`0x0042B5B5` is its only call site in the image**, which is worth
stating plainly: *the `+0x32` / `+0x67` pair is the only way an item enters that
table, and killing the demon is the only way to fire it.* The table is drained
at `0x00435AB2` (a script opcode, which clears each slot to `0xFFFF`/0) and read
at `0x00437418`.

### 5.1 The data agrees

Across the 416 readable records: `+0x32` has 151 distinct values, **every
non-zero one a valid `et/ET0001.BIN` index**, 98 records zero. `+0x67` takes 30
distinct values, nearly all round percentages (0 x104, 10 x29, 20 x39, 50 x97,
…). Ten records disagree about which of the pair is zero — two carry a rate and
no item, eight an item and no rate — which is the expected level of authoring
noise, not a contradiction.

---

## 6. Correcting `+0x22`..`+0x34` **[VERIFIED by disassembly]**

`format-notes.md` §7 listed `+0x22`..`+0x34` as "ids outside the ET0004 range —
possibly drops". It is three separate fields and none of them is a drop list.

`0x004105FE`..`0x004106D5` copies **eight u16s** from record `+0x22`, `+0x24`,
… `+0x30` to `struct+0x1BC`, `+0x1C0`, … `+0x1D8` — stride 4 — each `OR`ed with
`0xF800`. `0x0043DCE0(stats, items)` then walks those eight slots, recovers the
index with `shl ax,5 ; sar ax,5` (so **the item index is the low 11 bits**) and
passes each to `0x00424BA0`, which applies that item's bonuses to the stat
block. **They are the demon's equipment.** The last two slots get extra
handling at `0x004106C4`..`0x00410752` — if slot `+0x2E` is empty both are
cleared, otherwise `0x00423460(index)` is consulted for `byte[+0x2F]` into
`struct+0x1DA` — the weapon/armour pair and an ammunition count.

`+0x32` is the drop (§5). **`+0x34` is the species id**: `0x004104DA` reads it
as a u16 into `struct+0x1A` — combatant field 0 — and also passes it to
`0x0040FFC0`; `0x004108EB` special-cases the value `0x117`; `0x0043FFF0` scans
the roster for it; and it is **distinct for all 416 records, range 0..431**.
`0x0040E820` writes `0xFFFF` over it in a negotiation slot as an "empty" marker.

**Why this matters practically.** Species ids and item indices share a numeric
range, so reading `+0x22`..`+0x34` as a drop list produces false hits from
`+0x34`. Two of them were in the list this investigation started from: Jinn
(`P20A7`) has species id 167 and drops **Sapphire** (170), not Topaz; Vile
(`P20AC`) has species id 172 and drops the **Fairy Dress** (561), not Diamond.

---

## 7. The district join — the name the player reads **[VERIFIED by disassembly]**

`0x004120B0(x, y)` resolves the same (area, cell) and reads a **second 45-byte
grid**:

    ebx = 0x0040CCF0(x, y)                      ; area
    (cellx, celly) from 0x0040CCC0(x, y) / 32 and / 40
    base = ET000D container 0
    p    = base + word[base + 4*area + 2]       ; offset table indexed at 2*area
    ax   = byte[p + cellx + 9*celly]            ; district index
    0x00412140(ax)                              ; -> container 1's string

`giten/districts.py` already documents container 1 (221 district names) and
said of container 0 only "a map -> district index lookup". It is the encounter
grid's twin, cell for cell.

Two consequences worth having:

* **`tools/encounters.py` can name every encounter area in the words on the
  player's screen** — `tables/districts.tsv`'s English column — with no guessing.
* It independently confirms §2's bound: every area outside `cx` 1..6 / `cy` 1..9
  has an all-zero (blank) district grid.

The `m/M####.BIN` map id (`tables/mapnames.tsv`, the bar at the top) is a
**different** thing and is not what the encounter table is keyed on: it lives in
`ds:0x00491087`, set by script opcode `1E 04` through `0x00412880`. World
position is set separately by opcode **`1E 05`** —
`0x00435DF0` reads three expressions and calls
`0x004197B0(area, dx, dy)`, which does `ds:0x0047BE68 = area` and
`0x0040CC60(area)` = `(288 * ((area/2) % 8), 200 * ((area/2) / 8))`, then adds
`dx, dy`. **The `1E 05` operand is twice the area number.** Corroboration from
the corpus: of the 75 `1E 05` sites, 73 name an even value whose half is one of
the 54 areas that have a file, and every `dx` is in 0..287 and every `dy` in
0..199, i.e. exactly one area. The two exceptions are `m/MS0041` r03 `(1, 2, 3)`
and `m/MS00AF` r08 `(14, 11, 12)`, which are placeholder triples.

---

## 8. Corroboration from play, and its limits

`build/traces/2026-09-11-roppongi-textout.bin` draws the district strip 1,280
times across 87 districts, and 60 "detailed analysis" screens (a demon name
followed by its `Race:Lineage`). Two of those screens are unambiguous field
encounters and both agree with the model:

| where the strip said | demon analysed | area | group | in that group? |
|---|---|---|---|---|
| Shimomeguro | Purski (Lv 29) | 74 | 35 | yes, slot 1 |
| Ebisu | Gyuuki (Lv 25) | 66 | 31 | yes, slot 0 |

**Honest about the rest.** The other 58 screens do not test anything: 33 are one
uninterrupted run in N.Shinagawa listing the player's own stocked demons, and
the remainder are indistinguishable from the player inspecting a party demon,
because the same screen serves both. One screen — Gorgon (Lv 38) at Otemachi —
would be a counter-example if it were an encounter, and it is not decidable from
the log; the strip stops being redrawn 4,000 calls before it, which is what
leaving the overworld looks like. So the traces are **weak corroboration, not
proof**, and the model's real support is the disassembly plus two structural
facts: the group index rises monotonically with level, and the lowest groups
(0, 1, 2) sit in area 49, which is Yoyogi Park — where the game starts.

---

## 9. What is **not** pinned

* **`+0xF4` on a party member**, the statistic `0x00411330` averages to size the
  enemy party. `[conjecture: a level or rank]`
* **Which demon species id 4 is**, and therefore what carrying it means
  in-fiction (it raises encounter pity, party size and the group roll).
* **`p/P####.BIN` `+0x02`** (0 or 1 across the corpus), **`+0x20`** (0..33; it
  reaches `struct+0x5F` and nothing in this pass reads that), **`+0x48`..`+0x58`**,
  **`+0x63`..`+0x66`** and **`+0x68`..`+0x79`**. `+0x63`..`+0x65` reach
  `struct+0x5C`..`+0x5E` — note that `struct+0x5C` is *not* the drop item
  (§5 fixes the pointer bias), and reading it as one is the trap this section
  exists to mark.
* **Whether any script-driven encounter path exists beside `0x00411030`.**
  Nothing else calls it, and nothing else writes `ds:0x004919A0`.
* ~~**Whether Topaz or Diamond can be bought or found in a chest.**~~ **Answered:
  §11 and §12.** ~~Which items each shop stocks~~ was the wrong question --
  there is no stock table because shops are hand-written scripts (§12.3), and
  `m/MS0039.BIN` r1A is not a purchase dispenser but the shopkeeper's **thank-you
  gift** (§12.5).  What is left open there is narrow and named in §12.6.
* **The condition-flag banks** other than 0 — `0xCF00` (bank 0x4F) and `0x1180`
  (bank 0, negated) occur and were not traced to a story event.

---

## 10. The answer this was written for

Drop rate is per enemy killed, rolled independently for each.  §11 covers every
*other* way an item can reach the player and sharpens the advice: there is
nothing to farm for Diamond, and the game spends two of each gem on one puzzle.

**Topaz (`et/ET0001.BIN` 167)** — four demons carry it; **one is farmable**:

| demon | Lv | rate | where |
|---|---|---|---|
| **Cassiel** `P2065` | 21 | **20%** | group 27, slot weight 17/100, in **Ginza / Shintomicho / Tsukiji / Akashicho / Tsukishima** (area 53), **S.Azabu / Mita / Shirokanedai / Takanawa** (area 67) and **Shiba / Kaigan / Shibaura** (area 68); and group 29, weight 17/100, in **Toyosu** (area 69). 5% encounter chance per check in every one |
| Celaeno `P208E` | 38 | 25% | only in groups 44 and 45, which no cell names (§4.1) |
| Dantalion `P2181` | 15 | 200% | in no group — scripted |
| Haagenti `P21A2` | 48 | 80% | in no group — scripted |

**Diamond (`et/ET0001.BIN` 172)** — six demons carry it, **none is farmable**:

| demon | Lv | rate | where |
|---|---|---|---|
| Naga Kanya `P2083` | 40 | 20% | only in groups 46 and 47, which no cell names |
| Demonic Pieta `P20F6` | 10 | 255% | in no group — scripted |
| Moloch `P2197` | 36 | 255% | in no group — scripted |
| Astarte `P219A` | 41 | 50% | in no group — scripted |
| Astarte `P21AC` | 45 | 200% | in no group — scripted |
| Ishtar `P219F` | 60 | 200% | in no group — scripted |

So Diamond has **no repeatable source through the encounter system**: every
carrier is either a one-off scripted fight or sits in one of the 21 groups the
area files never name. Topaz has exactly one, Cassiel, and the best places for
it are the four areas above.


---

## 11. Every other route to an item **[VERIFIED by disassembly; §11.4 is a negative result]**

Written 2026-09-12 as the follow-up to §9, because "farm it" is only good advice
if nothing else supplies it.

### 11.1 Gems are a separate 16-slot pouch, and they have prices

`0x004246B0(base)` writes `ds:0x00480100 = base` and initialises **sixteen
slots** at `ds:0x0047FE60`, stride 4, as `{u16 item = base + i, u8 count}`.
`base` is found at `0x00423358` by scanning `et/ET0001.BIN` upward for the first
record whose type byte (`0x004233C0`) is **9**, which is **157, Onyx**. So the
pouch is items **157..172**, and Topaz is slot 10, Diamond slot 15.

Ordinary add and remove route into it automatically: `0x004236E0` and
`0x00423780` both call `0x00424580(item)`, which returns `item - base` when the
item's type is 9 and `-1` otherwise, and then `0x004246F0` adjusts the slot.

`et/ET0001.BIN` `raw[0..3]` is a **u32 price** (§9's decoder puts it at
`struct+0x02`): Salve 30, Ceramic Blade 2500, and the sixteen gems run

    Onyx 500, Crystal 700, Aquamarine 900, Moonstone 1100, Amethyst 1200,
    Turquoise 1500, Rose Quartz 1800, Lapis Lazuli 2000, Garnet 3000,
    Opal 4000, Topaz 6000, Pearl 7000, Ruby 8000, Sapphire 9000,
    Emerald 10000, Diamond 12000

-- monotone, and in exactly the order the gift table below ranks them.

### 11.2 What gems are *for*: negotiation

`m/MS0017.BIN` r04, the tutorial quiz, says it outright -- 交渉に宝石を用いる事は
大変有効である, *using gems in negotiation is highly effective* -- and then asks
which gem is the most effective, with ダイアモンド among the answers. Gems are the
game's negotiation currency, and Diamond is the top of the ladder.

### 11.3 The demon-gift opcodes, and the gem they can give

Seven opcodes call `0x00432EA0(kind)`, a nine-way jump table at `0x00433134`
that ends by publishing its result in script variables 0x12 and 0x13
(`0x0043BF60`). Its subject is `[ds:0x00491160 + 2]`, the script context's
combatant -- the demon being talked to: one arm reads that unit's `+0x5C`
(record `+0x32`, its own drop item, §5) and another calls `0x0043FAA0` on its
species id to recruit it. **All 390 sites of these opcodes are in `m/MS60xx` /
`m/MS61xx`**, the negotiation family, which is what fixes the subject.

| opcode | uses | what it hands over |
|---|---|---|
| `1F 68` | 9 | 宝玉 Treasure Orb -- `et/ET0100.BIN` container 0 slot **0** |
| `1F 67` | 26 | 魔石 Magic Stone -- the same list, slot **1** |
| `1F 64` | 39 | the demon's own `+0x32` drop item |
| `1F 69` | 8 | **a gem, tier chosen by the demon's level** (below) |
| `1F 6B` | 263 | a weighted roll that can land on any of the above |
| `1F 6C` | 73 | a weighted roll that tops out at Magic Stone |
| `1F 65` / `1F 66` | 69 | `0x00433210` -- money / Magnetite, not an item |

**The gem tier**, `0x00432FA0`:

    value = 0x0040B960(0, 100, 100) + byte[demon + 0x6B]        ; the demon's level
    for t in 0..15:  if (value <= word[0x004646C8 + 2*t]) break
    gem = ds:0x00480100 + t                                      ; pouch base + t

`0x0040B960(0,100,100)` is the mean of **101** rolls of `rand()%101`, so the
first term is ~50 with a standard deviation near 3 -- it barely moves. The
sixteen thresholds are

    20 30 40 50 60 70 75 80 85 90 95 100 110 120 130 140

so the gem is essentially a function of the demon's level alone:

* **Topaz is tier 10** -- needs `90 < value <= 95`, i.e. **level ~41-45**.
* **Diamond is tier 15** -- needs `130 < value <= 140`, i.e. **level ~81-90**.

`p/P####.BIN` `+0x47` runs 0..**70** across the whole corpus (§7), so **no demon
in the game can give you a Diamond**, and Topaz needs a level 41-45 demon --
which §4.1's ceiling (no encounter group above mean level 30) means you will
never meet in a random encounter.

### 11.4 Scripts, chests and shops -- what the corpus does and does not hold

`1F 60` (`0x00435690`: one expression, then `0x004236E0(item, 1, -1)`) is the
plain **give-item** opcode; `1F 61` (`0x004356D0` -> `0x00423780`) removes one;
`1E F0` gives or takes a signed count. Scanning every `m/MS*.BIN`:

* **`1F 60`, 117 sites, 67 distinct items.** Every one of the sixteen gems
  appears **exactly once, and all sixteen are in `m/MS0039.BIN` r1A** -- the shop
  script (its spans are 店員： and …を入手, and r0C lists the equip categories
  格闘武器 / 射撃武器 / 弾丸 / …). r1A is a switch on the selection variable with
  one arm per item, i.e. the *purchase-completed* dispenser. **No chest, no NPC
  and no event hands out a gem.**
* **`1F 61`, 116 sites.** The only gem sites are `m/MS0015.BIN`: **the
  Five-Coloured Fudo puzzle** -- r0A Onyx, r0B Diamond, r0C Ruby, r0D Sapphire
  (Jukai supplies that one himself), r0E Topaz. Each record removes its gem
  **twice** (片方の瞳にもはめ -- *set it into the other eye too*) and r0B's guard is
  `op 22D [23, …, 172, 2, 0]`. So the game **consumes 2 Onyx, 2 Diamond, 2 Ruby
  and 2 Topaz**, and r14 is the refusal 適当な宝石を持っていない.
* **`1E F0`, 71 sites** -- never a gem.

**Where the shop stock is not.** Searched and empty: every `et/` container in
both readings for a u16 run containing 167 or 172 among plausible item indices
(only `ET0100`, `ET0021` and `ET0030` hit, all explained here); every `m/` and
`p/` container for four or more ids in 157..172 inside ten words; and `.rdata`
plus `.data` of `dds_org.exe` for the same, as u16 and as u8. Nothing --
**because there is no stock table at all**: §12.3 shows a shop is a hand-written
script with its price as a literal in a comparison. And the reading of
`m/MS0039.BIN` r1A above as a *purchase* dispenser is **wrong**; §12.5 decodes it
properly as the shopkeeper's thank-you gift, which is where gems come from.

### 11.5 Two tables that looked like the answer and are not

* **`et/ET0100.BIN`** is loaded at `0x004232E9` (kind 12) through
  `0x00401D40`, so §2.1 applies and it is plaintext. It is **two** containers,
  not one 24-entry list: the first u16 of the file is the container length 36,
  not an item. Container 0 is 18 words -- Treasure Orb, Magic Stone, then the
  sixteen gems -- and its **only** reader is `0x00423380(i)`, called from exactly
  one site, `0x00432F91`, with `i` in {0, 1}. Fourteen of its eighteen entries
  are read by nothing. Container 1 is **not a list but pairs**: `0x004234F0`
  walks it two words at a time, terminator `0xFFFF`, and returns the second of a
  matching pair -- `{9 Ration Pack -> 2 Ration}`, `{3 Salve Set -> 1 Salve}`. It
  is the "a pack breaks into units" map, consulted by `0x00423C20` when a
  dropped item is a pack. Not a shop list, not prices, not gifts.
* **`et/ET0030.BIN` / `et/ET0031.BIN`** are **skill** tables, not item tables.
  `0x0041C250` loads both plain; `0x0041C2B0` picks one of ET0030's thirteen
  `0xFFFF`-terminated lists by the unit's race group (`0x0043CDB0`, 1..12) or by
  a byte on the protagonist (keys -1, -3, -4); `0x004194C0` copies it to
  `ds:0x0047BB78`; `0x0041C330` picks an entry the unit does not already hold in
  its own 8-slot list at `unit+0x1F1` (`0x0042DCA0`), with ET0031 gating eight of
  them behind a flag word (`0x00439480`); and `0x004190AD` installs it and prints
  %sを会得した！ -- *learned %s!* -- with the name from `0x0042E410`, which is the
  **`et/ET0004.BIN` skill** accessor (`+0x14` past the 20-byte header,
  `format-notes.md` §7.2). The "172 = ダイアモンド" in key 8's list is a skill index
  colliding with an item index: the same trap as `+0x34` in §6.

### 11.6 What this means for farming

Farming is the only repeatable route to a gem, and it reaches exactly one of the
two:

| route | Topaz | Diamond |
|---|---|---|
| drop (§10) | **Cassiel, 20%, four areas** | none reachable |
| negotiation gem gift (§11.3) | needs a level 41-45 demon, above the encounter ceiling | **impossible at any level** |
| chest or event script (§11.4) | none | none |
| bought from a shop (§12.3) | **no** -- no shop script offers a gem | **no** |
| **shopkeeper's gift (§12.5)** | **0.096% per transaction** | **0.016% per transaction** |
| sold to a shop (§12.4) | yes, 6000 | yes, 12000 |
| consumed by (§11.4) | 2 for the Fudo puzzle | 2 for the Fudo puzzle |

So: **grind Cassiel for Topaz. For Diamond there is nothing to kill and nothing
to buy -- the only repeatable source in the game is the shopkeeper's thank-you
gift, at about one in six thousand transactions.**


---

## 12. Shops, and where a Diamond actually comes from **[VERIFIED by disassembly]**

§11.4 ended at "the buy list is assembled at run time from something this pass
did not identify". That was the wrong shape of question: **there is no stock
table because there are no table-driven shops.** Each shop is a hand-written
script, and the gems come from somewhere else entirely -- a gift.

### 12.1 `1E 70` installs a script file under another id

`0x00434000` reads two expressions (`edi = first & 0xFF`, `esi = second`) and its
default arm `0x0043458C` calls **`0x0043B7A0(key, file)`**, which walks the loaded
-buffer list at `ds:0x00481688` for a buffer whose id word is `key`, loads
`m/MS<file>.BIN` through `0x0043AD20` if there is none, and then
`mov WORD PTR [eax], di` -- **stamps `key` over the buffer's own id**. So the
file is *aliased*, and a later `0C key rr` / `0D key rr` runs records of whatever
was installed.

**This closes the open question in `limits.md`** that ends "its caller
`0x0043458E` supplies that id in `%edi` from a path not traced to immediates":
the id is the *second* operand of `1E 70`, and the first is the alias.

All 41 `1E 70` sites in the corpus use key **127 (0x7F)**:

| caller | installs | what it is |
|---|---|---|
| `m/MS0039.BIN` r00-r06 | `MS0100`..`MS0106` | seven **shopkeeper voices** |
| `m/MS0033.BIN` r00-r07 | `MS0110`..`MS0115` | clinic / receptionist voices |
| `m/MS003C.BIN` r00-r18 | `MS00A0`..`MS00B8` | 25 more, one per location |

`m/MS0100.BIN` is exactly that and nothing else -- 「いらっしゃいませ。ご用件をどうぞ。」,
「お金が足りないようですが？」, 「そんなに持ち切れませんよ。」, 「ＯＫ。その値で買い取り
ましょう。」 -- and **scanning every `MS01xx` / `MS00Axx` file through the expression
model finds not one item id in any of them.** They are voice only.

### 12.2 `0E` is a percentage table

`0x00430037` (the `0E` handler) calls `0x004328C0`, which computes the key as

    0x0040B960(1, 100, 0)        ; n = 0, so one uniform roll: 1..100

and hands it to `0x004327C0`, which takes the first case byte at or above the
roll. So **`0E` is "roll 1d100 and branch by percentage band"**, and a `0E`
table's case bytes are cumulative percentages. (`0F`, `0x004328E0`, is the same
walk keyed on `ds:0x004919E0` instead of a roll.) `format-notes.md` §2.12
documents the parser these share but not where the key comes from.

### 12.3 Shops are hand-written scripts

`m/MS0019.BIN` r06 is a complete one, and nothing about it is table-driven:

    1F B1 / 1F B2      a two-option menu, 「買う」 / 「買わない」
    1F 89 (rel16, <the party's money>, 5000)     branch if you cannot afford it
                       -> 「残念！！ マッカが足りないな。」
    1E F0 (260, 1, ...)                          hand over item 260
    1F 83 (rel16, <result>)  -> 「荷物を持てないみたいだねぇ」

The price is a literal in a comparison and the item is a literal in the grant.
Corroborating that there is no shared price path: **the only expression nodes
that can read an item's price are selectors 0x06 and 0x07** (`0x00436B94` /
`0x00436BAE` -> `0x00423400`, which decodes the record and returns
`dword ds:0x004911C2`, i.e. `raw[0..3]`, with 0x07 dividing by four), they occur
**26 times in the whole corpus, and every one is in a record `limits.md` already
classifies as unreachable** (`MS0031` c0, `MS610D`, `MS6200`, `MS6F00`,
`MS6F1F`). No shop script in the game computes a price.

### 12.4 The sell path

Settled, and it is engine-side. `0x0041B750(count, data)` creates an item-list
window whose per-line callback is **`0x0041B7C0`**:

* mode 1 (`0x0041B82B`) takes the list entry's item word, masks it with
  `shl 5 / sar 5` (the low 11 bits, §11.1), calls `0x00423460(item)` and reads
  `[rec+0x02]` -- **the price** -- then formats with string `0x3450` when the
  price is non-zero and `0x3500` when it is zero, which is how an unsellable item
  is drawn;
* mode -1 (`0x0041B8D0`) calls `0x00423800` to clear `ds:0x0047FEA0` and
  `0x00423820(item, count)` for each entry, i.e. rebuilds the inventory from the
  window's list.

Its three creators all list things the player already holds: `0x0041C010` over
`ds:0x0047FEA0` (the 64-slot inventory, adjacent to the 16-slot gem pouch at
`ds:0x0047FE60`), `0x0041BF20` over `0x00423AA0`, `0x0041B6E0` over a filtered
copy. **So gems are sellable, at the ladder in §11.1 -- Diamond 12000, Topaz
6000.** What is *not* pinned is the multiplier the shop applies on the way out:
selector 0x07 exists and is exactly `price / 4`, so a quarter-price buy-back is
likely, but no reachable script uses it and the money transfer was not traced.

### 12.5 **`m/MS0039.BIN` r1A is the shopkeeper's thank-you gift**

r1A prints 「店員：」 and then `0D 7F 11` and `0D 7F 15` -- records 0x11 and 0x15
of whichever voice file `1E 70` installed. In `MS0100` those are

> r11 「ああ‥‥そうそう。」 — *Oh, by the way…*
> r15 「つまらない物ですがこれを差し上げます。お役立てください。」 — *It's only a trifle, but please take this.*

and then three nested `0E` rolls choose the item and `1F 60` grants it, over the
message 「…を入手」. It is reached by `0D 39 1A` from r12 and r15, the buy and
sell branches, after the transaction succeeds. Its head is
`reg23 = 16; reg23 &= reg0; 1F 80 <skip>` and the 60% arm at `0x02F6` is
`1F 4F (reg0, 16)` then end -- a once-per-visit gate and a 60% "no gift".

**The tables, decoded** (`0E` case bytes are cumulative, §12.2):

    @0013   40%  -> the gift tables below        60%  -> no gift
    @0039    2%  gems (@004F)   2% charms   3% amulets   13% stones   80% food

    @004F, the gem table -- the same order as et/ET0100.BIN container 0:
      12% Onyx      12% Crystal   12% Aquamarine  12% TOPAZ
       8% Moonstone  8% Amethyst   8% Turquoise    8% Rose Quartz
       3% Lapis      3% Garnet     3% Opal         3% Pearl
       2% Ruby       2% Sapphire   2% Emerald      2% DIAMOND

That is what `et/ET0100.BIN` container 0's otherwise-unread sixteen entries are:
the same list in the same odd order (Topaz sitting between Aquamarine and
Moonstone), authored alongside this table.

**So the odds per completed shop transaction are**

    Topaz    0.40 x 0.02 x 0.12  = 0.096%   (about 1 in 1,000)
    Diamond  0.40 x 0.02 x 0.02  = 0.016%   (about 1 in 6,250)

Rare, and repeatable -- which makes it the **only** repeatable source of a
Diamond in the game, since §10 has no reachable carrier and §11.3 rules the
negotiation gift out at any demon level.

### 12.6 What is still open

* **What exactly re-arms the gift.** The gate is a bit of `reg0` cleared
  somewhere between visits; r12 and r15 each set their own bit after calling
  r1A. "Trade with a shop" is the trigger, but whether it is once per visit,
  once per purchase or once per haggle was not pinned.
* **The sell multiplier** (§12.4).
* Whether the 25 `MS00A0`..`MS00B8` voices belong to shops with their own,
  differently-weighted gift tables: they are installed by `m/MS003C.BIN`, which
  was not read.
