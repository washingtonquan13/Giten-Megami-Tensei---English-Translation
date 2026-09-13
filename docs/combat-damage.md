# The damage formula, and how a hit becomes a message

Written 2026-09-09. This closes items 3 and 4 of
[`combat-unknowns.md`](combat-unknowns.md), which were listed separately but
share one entry point and had to be read as one pass.

Everything below is read out of `original/ddswin/dds_org.exe` and out of the
shipped scripts, not inferred from play logs. The one exception is section 7,
which checks section 2 against a recorded trace -- and which caught a mistake,
so it is worth reading before trusting the rest.

---

## 0. The short version

    damage = sqrt(max(atk - 0.2*def, 0)) * (atk/def + 2.2 or 1.0)
             * (situational multipliers)
             * weapon power% * cycle-row% * random 80..120%

and the four outcomes the player reads -- dodged, could not damage, grazed,
N damage -- are **not** four bands of one number. Three of them are decided
before any damage is computed, by a separate accuracy roll, and only "could not
damage" is a damage result.

A graze is a hit quality, not a small number. The accuracy roll picks it
outright, and the damage formula then multiplies by **0.25**. The grazed line
prints its own number like any other hit, so "grazed for 6" and "hit for 24" can
be the same swing against the same target.

---

## 1. How the number reaches the screen

The chain runs script -> engine global -> script -> text, which is why looking
for a `printf` in the exe found nothing.

`m/MS00DD` record `0x4C` -- the "N damage" line -- opens like this:

    1F E8  03 08  4B 00 01        var[8] = battle_result(1)
    1F 02  03 08                  print var[8]
    03 0D                          the "HP" pool word
    のダメージを                    text

Reading right to left:

* **`1F 02 <expr>`** (`0x102`, handler `0x00430141` -> `0x0043BA30`) is *print a
  number*. It calls `sprintf(buf, "%ld", eval(expr))` with the format string at
  `0x00469EDC`, then converts each ASCII digit to its full-width Shift-JIS twin
  one byte at a time and appends that to the draw buffer at `0x004815A0`.
* **`1F E8 03 nn <expr>`** (`0x1E8`, handler `0x00430E22` -> `0x004338D0`) is
  *assign*: `var[nn] = eval(expr)`. It is the corpus's generic assignment, 1,399
  uses. The `03 nn` in front is an expression node `0x03` read as an lvalue by
  `0x004335A0`, which skips the node byte and keeps the index.
* **`var[n]`** is `dword [0x004815E0 + 4*n]`, `0 <= n < 26`, through the getter
  `0x0043BFA0` and the setter `0x0043BF60`. There are 26 script registers and
  nothing else; no exe code names one directly.
* **expression node `0x4B`** (handler `0x0043708A`) calls `0x00437440(n)`, which
  is a four-way read of the battle-result globals:

  | n | global | meaning |
  |---|---|---|
  | 0 | `ds:0x00491994` | **outcome code** |
  | 1 | `ds:0x00491998` | **HP amount** (the damage) |
  | 2 | `ds:0x0049198C` | MP amount |
  | 3 | `ds:0x00491986` | a third amount, written from one site only |

So `1F 02 4B 00 01` prints the damage directly and `1F E8 03 08 4B 00 01` parks
it in a register first; `m/MS00DD` uses both.

**Where the four accessors are used at all** (whole corpus, `m/*.BIN`): `f(0)`
appears throughout many files, while `f(1)`, `f(2)` and `f(3)` appear almost
only inside `m/MS00DD`, `m/MS00DC` and `m/MS0042`. The battle-message file is
the only real consumer of the amounts.

---

## 2. The outcome code is a jump table, not a range

`m/MS00DD` record `0x05` is the whole of the player-facing outcome logic:

    1F E8 03 07 4B 00 00     var[7] = outcome_code
    1F E8 03 09 00 00        var[9] = 0
    1F 1A 03 07 <switch>     switch (var[7])

and the switch table (`_switch` in `opcodes.json`: `[u8 case][u8 kind][u16]`,
kind 0 meaning *file, record*) reads:

| code | record | line | prints N? | what it is |
|---|---|---|---|---|
| 0 | `DD:0A` | 巧くかわ… | no | dodged |
| 1 | `DD:0B` | ダメージが無… | no | could not damage |
| 2 | `DD:0C` | かすり傷を受け… | **yes** | grazed |
| 3 | `DD:0D` | 、 | yes | ordinary hit |
| 4 | `DD:0E` | 会心の一撃！/ 痛烈な一撃！ | yes | critical |
| 5 | `DD:0F` | 必殺の一撃！/ 痛恨の一撃！ | no | deadly blow |
| 6 | `DD:10` | に効か… | no | no effect |
| 7 | `DD:11` | 跳ね返… | yes | repelled |
| 8 | `DD:12` | は吸収… | yes | HP absorbed |
| 9 | `DD:13` | は吸収… | yes | MP absorbed |
| 10 | `DD:61` | によ護ら… | no | protected by another |

Record `0x06` is the same switch with a different arm set (0 -> `DD:14` 回避,
1 -> `DD:15` 耐 / には効か), so more than one caller drives this table.

Records `0x0C`, `0x0D` and `0x0E` all end with `0D DD 4C`. Opcode `0x0D` is a
**call**, not a goto (`opcodes.json`: *return context pushed*), which is why the
trace shows `05 0D 4C 0D` -- into `0x0D`, out to `0x4C`, back to `0x0D`. Graze,
ordinary hit and critical therefore share one damage line, and **a graze prints
its number like any other hit**.

That last point was got wrong first time round. Record `0x0C` has no number
token anywhere in its text, and the call is its last token, past the end of the
text a reader sees. Section 7 is how the trace caught it.

---

## 3. Where the outcome code is decided

`0x0042AC90` resolves one action. It looks up the actor from `ds:0x004919F6`
and the target from `ds:0x00491996` through `0x0042ABE0`, zeroes
`ds:0x00491994`, **reloads the actor's ATB gauge (`actor+0x17F = 0xFF`)** -- an
independent confirmation of `combat-pacing.md` section 1 -- and then dispatches
on the action kind at `actor+0x181`:

| kind | routine |
|---|---|
| 1 | `0x0040A8A0` physical attack |
| 2 | `0x00408E60` skill / magic |
| 5 | `0x00424890` |
| 4, 6 | `0x0042D480` |

The physical path, `0x0040A8A0`, is the readable one and the magic path mirrors
it field for field.

1. `0x00406E00`, `0x00406CA0` and `0x004251C0` produce the weapon power into
   `ds:0x004784D8`.
2. `0x0040A690` is a **pre-roll** for the two special hits. It returns exactly
   0, 4 or 5, and writes its own return value to `ds:0x00491994`:

       gate:  ((counter+13) % 14 + 1)^2 / 4  >  rand(0..254)
              -- counter is ds:0x00491566, the 28-step cycle of section 5

       5 (deadly blow)  a further comparison, which also sets the damage
                        straight to 0x7FFF
       4 (critical)     actor+0xE0 + actor+0xE8 + rand(0..6) + power
                          >  target+0xE0 + target+0xE8 + rand(0..30)
       0                neither

   A 4 or a 5 **skips the accuracy roll entirely**, so a critical cannot miss.

   **The stats are named, 2026-09-12** (`format-notes.md` §9.1). `+0xE0` is
   **Intuition** and `+0xE8` is **Blessing**, so the critical line reads

       Intuition + Blessing + rand(0..6) + power
         >  target Intuition + target Blessing + rand(0..30)

   and the deadly-blow comparison above it (`0x0040A70E`..`0x0040A7E4`) turns
   out to use a **different pair**: `+0xE0` again and `+0xF4`, which is
   **命運 Fate** -- the eleventh stat, the one the status screen never draws.
   With `0.01` at `0x00464298` and `0.5` at `0x004642A0`:

       actor  = round( (Fate + 0.5*Intuition) * rand(80..120) * 0.01
                       + 0x00408480(actor, target) )
       target = round( (target Fate + 0.5*target Intuition)
                       * rand(100..200) * 0.01 )
       deadly blow if actor > target

   The branch is only reached when **`power == 0`** (`0x0040A6FC` tests the
   same argument the critical line later adds), so a deadly blow is a plain
   attack's privilege and a powered skill can never roll one. `0x00408480` is
   unread.

   So Fate is not decoration: it is the whole of the game's rarest outcome, and
   finding it there is the strongest single confirmation that slot 10 is real.
3. If the pre-roll returned 0, **`0x0040A490` rolls to hit** and writes outcome
   0, 2 or 3.
4. `0x0040A270` computes the damage; if it lands at zero it writes outcome 1.

So the three questions the player sees answered in one line are answered in
three different places, and the graze is settled in step 3, before any damage
exists.

### The accuracy roll, `0x0040A490`

Automatic hit, no roll, if either the target carries the status tested by
`0x0043EE80` or `0x004085A0(actor, target) == 2`.

Otherwise, with `acc = actor+0x12A` and `eva = target+0x12E`:

    if actor has status 0x17:  acc = max(acc / 4, 1)
    a = acc * 25
    a *= (0x004086D0(actor,target) >= 0) ? 4 : 2
    if 0x00408610(actor,target) == 0:  a *= 2
    e = (0x004085A0(actor,target) != 0) ? eva * 75 : eva * 100

    if a >= e and a*8 >= e * roll(-2..12, 2 dice):   hit   (3)
    elif            a*8 >= e * roll(0..15):          hit   (3)
    elif            a   >= e * roll(0..7):           graze (2)
    else:                                            dodge (0)

`0x0040B960(lo, hi, n)` averages `n+1` draws of `0x0040B940(hi-lo)` and adds
`lo`, so the first roll is a two-dice bell curve and the other two are flat.

---

## 4. The damage formula, `0x0040A270`

Arguments are the actor, the target and the hit quality `q` (recovered from
`actor+0x186 & 0x7F`, which is where section 3 stored it). The body is floating
point; the constants live at `0x004642A8`..`0x004642E0` and are, in order,
`0.2, 0.0, -2.2, -1.0, 1.2, 1.5, 0.25, 100.0`.

    if q == 0: return 0                         # a dodge never reaches here

    atk = actor+0x12C                           # attack
    if actor has status 0x13: atk *= 2
    if actor has status 0x1A: atk *= 2
    def = target+0x130                          # defence

    base  = max(atk - 0.2*def, 0.0)
    ratio = (def != 0 ? atk/def : atk) + (atk >= def ? 2.2 : 1.0)
    dmg   = sqrt(base) * ratio

    if q == 4:                          dmg += actor+0x6B + 5   # critical bonus
    if 0x0043EE80(target):              dmg *= 1.2
    r = 0x004085A0(actor, target)
    if r == 2:      dmg *= 1.5
    elif r != 0:    dmg *= 1.2
    if q == 2:                          dmg *= 0.25             # GRAZE
    if 0x00408610(actor, target) == 0:  dmg *= 1.5

    n = round(dmg * 100)                        # 0x0040B8F0
    n = n * weapon_power% * 2 / 100             # 0x00406A40, ds:0x004784D8
    n = n * cycle_row_byte% * 2 / 100           # 0x00417A40, actor+0x1F8
    n = n * random(80..120) / 100               # 0x0040B9A0(n, -20, +20)
    n = n / 100                                 # undo the *100
    n = clamp(n, 0, 0x7FFFFFFF)

    if n <= 0: outcome = 1 ("could not damage")
    return n

The `*100` early and the `/100` late keep two decimal digits alive through an
integer pipeline; they are not a balance number.

**Both percentage steps are doubled, so 50 is the neutral value, not 100.**
`0x00406A40` even substitutes 50 when the power it is handed is negative. A
weapon of power 50 multiplies by 1.0 and one of power 80 by 1.6 -- which is the
arithmetic behind the special bullets that carried the second Dantalion fight.
`actor+0x1F8` is a byte and selects the cycle row the same way.

### The magic version

`0x00408B40` is the same function with a different stat quad, the same eight
constants, the same helper calls and the same zero-result tail. `0x00408910` is
its accuracy roll. The pairing is exact:

| | physical | magic |
|---|---|---|
| attack | `actor+0x12C` | `0x00408B20(actor)` |
| defence | `target+0x130` | `target+0x13C` |
| accuracy | `actor+0x12A` | `actor+0x136` |
| evade | `target+0x12E` | `target+0x13A` |

That names six fields of the runtime unit struct that were unread. They are
**runtime** fields; the join to the `p/` demon record is not made here.

**The join was made on 2026-09-12** and is section 4.1.

**One caveat on the word "magic" in that table.** The right-hand column is one
of *four* parallel quads the equip screen draws side by side, at `unit+0x126`,
`+0x132`, `+0x13E` and `+0x14A` (`format-notes.md` §9). It is the second, and
the **firearm** equip check at `0x0041BA1A` reads that same column's skill
figure, `unit+0x132` -- which is what a gun column would look like, not a spell
column. The quad is reached through `0x00408B40`, the not-physical damage
function, and Giten routes gun attacks through the skill list the same way it
routes spells (`format-notes.md` §7.2: `ET0004` records 1..15 are the basic
weapon attacks, and element 1 is "gun"), so "magic" here may be too narrow a
name for one path that covers both. The *offsets* are right either way; only
the label is in doubt.

---

## 4.1 Where those fields come from **[VERIFIED 2026-09-12]**

`format-notes.md` §9.1 names the eleven base stats and pins the array at
`unit+0xE0` (`u16`, stride 2, in status-screen order). This section is the
other half: what the engine builds out of them.

`0x0043D560(unit)` recomputes the whole combat block. It hands
`edi = unit+0xE0` -- the *total* stat array -- to a family of one-line
functions and files each result in a **maximum** block at `unit+0xF6`..`+0x124`.
`0x0042D140` then restores the **current** block at `unit+0x12A`..`+0x154` from
it: every pair it touches is exactly `0x30` apart (`+0xFA`->`+0x12A`,
`+0xFC`->`+0x12C`, `+0x100`->`+0x130`, `+0x106`->`+0x136`, `+0x108`->`+0x138`,
`+0x10C`->`+0x13C`), so **current[x] = max[x-0x30]** and naming the maxima names
the six fields of section 4.

With the constants at `0x00464928`..`0x00464980` (`0.25, 0.5, -0.25, 0.2,
-0.1, -0.2, 0.4, -0.15`) folded in, and every result passed through
`0x0043D160` = `clamp(1, 999, round(x))`:

| field | max | formula |
|---|---|---|
| accuracy `+0x12A` | `+0xFA` | `Strength + 0.5*Agility + weapon` (`0x0043D390`) |
| attack `+0x12C` | `+0xFC` | `weapon + 0.2*(Strength + Vitality)`, plus `0.15*x` for item kinds `>= 0x20` (`0x0043D3F0`) |
| evade `+0x12E` | `+0xFE` | `Agility + 0.4*Intuition + armour` (`0x0043D470`) |
| defence `+0x130` | `+0x100` | `0.2*Blessing + 0.25*Strength + 0.1*Willpower + armour` (`0x0043D240`) |
| magic accuracy `+0x136` | `+0x106` | `Dexterity + 0.2*Intuition + a`, `+ (2b+10)` when `b > 0` (`0x0043D2C0`) |
| magic attack `+0x138` | `+0x108` | a clamp of a local; not derived from the stat array (`0x0043D81E`) |
| magic evade `+0x13A` | `+0x10A` | `0.4*(Blessing + Intuition)` (`0x0043D340`) |
| magic defence `+0x13C` | `+0x10C` | a straight copy of `+0x100`, the physical defence (`0x0043D84D`) |

Four more in the same block, for completeness: `+0x112 = (Intelligence +
Magic)/2`, `+0x114 = Magic + w`, `+0x116 = (Blessing + Intelligence)/2`,
`+0x118 = (Willpower + Blessing)/2 + w`.

**This is the cross-check that makes §9.1 safe.** Attack comes out of Strength
and Vitality, and Vitality is the stat a weapon's first requirement byte is
compared against -- a weapon gates on part of what makes it hit hard. Evade and
magic evade come out of Intuition and Blessing, the same two slots the critical
pre-roll of section 3 reads (`actor+0xE0` = **Intuition**, `actor+0xE8` =
**Blessing**), so criticals and dodges are decided by the same pair. None of
that was assumed; the formulas were read first and the names fitted afterwards.

`0x0040A690`'s pre-roll therefore reads, in words:

    Intuition + Blessing + rand(0..6) + power
        >  target Intuition + target Blessing + rand(0..30)

---

## 5. Two things found on the way

**The 28-step cycle counter.** `ds:0x00491566` indexes a 28-byte row inside a
table reached through the pointer at `ds:0x0047BEAC`, the row chosen by
`actor+0x1F8`; the byte found there is a percentage applied to every physical
and magical damage number (`0x00417A40`). The same counter drives the critical
pre-roll in `0x0040A690` as `(counter + 13) % 14 + 1`, and `0x00420CF0` compares
it against 14 and 15. A 28-step cycle scaling damage and criticals in a Megami
Tensei game is the moon phase; the exe does not say so, and the file the table
is loaded from has not been located.

**Both halves are settled, 2026-09-12 (`docs/treasure.md` §3.1).** The file is
**`et/ET0003.BIN`**: `0x004179D0` calls `0x00401DD0(3, 12, 0)`, reads it plain
into `ds:0x0047B8B8` and writes `ds:0x0047BEAC = 0x0047B8B8`. It is 21 rows of
28 percentages. And the counter *is* the moon: one step is 1520 minutes, so 28
steps are 29.56 days; column 14 is the extreme of fourteen of the twenty
non-flat rows; the icon table at `0x0046B560` gives counters 0 and 14 their own
two sprites out of a different bank; and **counter 14 is the full moon** -- the
phase `m/MS0037.BIN` r04 opens the ornate chest at and `m/MS000E.BIN` runs the
abduction event the town blames on 満月 at.

**And the row a unit uses comes out of its record, 2026-09-12.**
`0x004107D5` copies `p/` record `+0x58` to `struct+0x212` = `actor+0x1F8`
biased, which is the selector `0x00417A40` indexes with. Values across the
corpus are 0..16, inside the file's 21 rows.

**A hardcoded buff path.** `0x0043DA90` scales stats by status flag, through
`0x0043DBE0(v, pct) = v*pct/100`:

* status `0x24` -> accuracy, evade, magic accuracy, magic evade all **x50%**
* status `0x23` -> those same four **x150%**
* status `0x25` -> attack and defence **x150%**

These are flat, hardcoded, and do not read the skill record's magnitude field,
so they are a different mechanism from the Tarukaja/Tarunda numbers the port
rebalanced (`pc98-comparison.md`). Item 7 stays open, but it is now narrower:
whatever the magnitude field scales, it is not this.

---

## 6. What this does not settle

* `0x004085A0`, `0x00408610` and `0x004086D0` are relation tests between actor
  and target that gate four separate multipliers. Their contents are unread. One
  of them is very likely the affinity join already documented in
  `format-notes.md` section 7.1, but that is a guess and is marked as one.
* ~~`actor+0xE0` and `actor+0xE8` (the critical roll) and `actor+0x1F8` (the
  cycle row) are not joined to any file record.~~ **Joined 2026-09-12.**
  `actor+0xE0` is Intuition and `actor+0xE8` is Blessing, entries 0 and 4 of
  the eleven-stat array whose base values are `p/` record `+0x4C`..`+0x56`
  (`format-notes.md` §9.1); `actor+0x1F8` is `p/` record `+0x58`, the moon-cycle
  row (`format-notes.md` §7). `actor+0x6B`, the critical damage bonus, is still
  unjoined.
* Outcomes 6..10 (no effect, repelled, absorbed, protected) are written from
  `0x00406F20`, `0x0041F7D0`, `0x0040AA20` and `0x0040B0F0`, which were located
  but not read.
* `0x0041FE90` is the effect applicator: it dispatches on an effect code up to
  `0x41` and publishes the applied amount into `ds:0x00491998` / `ds:0x0049198C`
  for the recovery and status lines. It is not part of the damage formula and
  was not read past that.
* **The arithmetic has not been checked against a live trace.** The formula is a
  static reading. It predicts a distribution and no logged fight has been used
  to confirm the numbers it produces.

---

## 7. What the trace did check

Section 2 was checked against `traces/2026-09-08-atb.bin`, the ATB A/B fight,
by decoding it and reading off the order in which `m/MS00DD` records ran.

**It caught an error.** The first draft of section 2 said a graze prints no
number, on the strength of record `0x0C` containing no number token. The trace
shows all 27 grazes calling `DD:4C` immediately, exactly as the 107 ordinary
hits do. The call is the record's last token, past the end of its text, and
reading the text alone hid it. The table above is the corrected one.

What the trace confirms:

| | |
|---|---|
| ordinary hits (`0D` -> `4C`) | 107 |
| grazes (`0C` -> `4C`) | 27 |
| dodges (`0A`, no damage line) | 15 |
| could not damage (`0B`, no damage line) | 3 |
| criticals (`0E`) and deadly blows (`0F`) | 0 |

Every `0A` and every `0B` is followed by a return to the dispatcher `0x05` and
never by `0x4C`, which is the switch table behaving as read. One fight is one
sample, and the zero for criticals is consistent with the pre-roll in
`0x0040A690` being rare rather than evidence that it never fires.
