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
* `actor+0x6B` (the critical damage bonus), `actor+0xE0` and `actor+0xE8` (the
  critical roll) and `actor+0x1F8` (the cycle row) are not joined to any file
  record.
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
