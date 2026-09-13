# Treasure chests, and the moon

Written 2026-09-12 to answer one question — *is there a gold chest that gives a
Diamond, and is it gated on the full moon?* — and the answer is **yes**, which
also means `encounters.md` §13's "complete item-grant scan" was complete over
the wrong surface. House style as in `format-notes.md`: every claim carries its
evidence and a guess is labelled `[conjecture]`.

**The short version.** A chest is **not** a script grant. It is a **map object**:
`m/M####.BIN` carries, per floor, a list of 16-byte entries keyed on the tile the
player is standing on; when the player presses the action button the engine
copies the matching entry to `ds:0x0047BB50` and runs the script file and record
the entry names. Every chest in the game names `m/MS0037.BIN`, and that script
reads its *own* 16 bytes back through `1E AD` / `1E AC` — so what is inside a
chest is in the **map file**, not in any script, and no scan of `1F 60` / `1E F0`
could ever have seen it. There are **235** such objects, four presentations, and
**18 of them are the 豪華な装飾を施した箱, the ornate chest, which opens only
when the lunar counter is 14 — the full moon**. Thirteen of those, plus two
ordinary pickups, are on a **15-entry renewal list in `et/ET0019.BIN` that the
engine clears one step after every full moon**, so they refill each lunar month.
One of them is a **Diamond**.

Tool: `tools/treasure.py`.

---

## 1. The object list **[VERIFIED by disassembly]**

`0x00421470(state, body)` parses a map file. The body's layout, read off that
routine and confirmed against the data:

    body[0..1]   (unused by this parse)
    body[2..3]   offset just past the floor-offset array (== 6 + 2*N)
    body[4..5]   N, the number of floors
    body[6+2i]   absolute body offset of floor i's header
    floor header 13 u16 **absolute body offsets**, one per object list

The 13 offsets become the floor struct's dwords in order, so list `k` is the
struct's `+4k`. `0x00421880` — the field probe, called from `0x00412E94` (step
on) and `0x00413682` (action button) with the player's `(x, y)` — walks six of
them, each with its own stride:

| struct | header index | stride | what |
|---|---|---|---|
| `+0x08` | 2 | 9 | stair / map links (`entry[3..5]` = dest x, y, floor; `entry[8]` = dest **map id**) |
| `+0x0C` | 3 | 11 | |
| `+0x10` | 4 | 14 | |
| `+0x14` | 5 | 8 | |
| `+0x24` | 9 | 10 | |
| **`+0x28`** | **10** | **16** | **the event objects — every chest is here** |

Every entry, whatever the list: `entry[0]` = tile x, `entry[1]` = tile y,
`entry[2]` = the object **kind**, and a `0xFF` in `entry[0]` ends the list.
`0x004217E0(x, y, entry)` is the two-byte coordinate match and
`0x00421810(entry, off)` is a condition test on the flag word at `entry+off`.

**How a match becomes a script.** `0x00421850(entry)` looks `entry[2]` up in the
26-row, 4-byte, `0xFF`-terminated table at `0x00468E50` and returns the row;
`[row+1]` is a **code 1..14** which `0x00413682` dispatches through the jump
table at `0x00413A40`. Chest kinds `0x88` and `0x89` both carry code 12, whose
arm is `0x004139E9`, and that arm calls

    0x00418200(5, 6)   ->   0x004181E0(obj[5], obj[6])

where `obj` is the 16 bytes at `ds:0x0047BB50` that `0x00417CE0(entry)` has just
copied there. **`entry[5]` is the script file and `entry[6]` the record.** All
235 event-list entries that name a script name file `0x37`, i.e. `m/MS0037.BIN`.

`[conjecture]` Kinds `0x4F` and `0x8A` also occur in the list with `entry[5] =
0x37` (67 and 86 entries) but are **not** rows of `0x00468E50`, so this dispatch
path skips them; they are the two records that print nothing and prompt nobody
(§2), and `entry[13]` — a sprite id for `0x88`/`0x89`, `0` for these two — is
zero for every one of them, which reads as "no object is drawn". Which walker
fires them was not traced.

## 2. `m/MS0037.BIN`, the one chest script **[VERIFIED by disassembly + data]**

Nothing in the corpus calls it. A scan of every `0C`/`0D` and of every kind-0 arm
of every switch table, across all 309 `m/MS*.BIN` (the seven records
`limits.md` classifies dead or unreachable included), finds **no caller of
`m/MS0037.BIN` outside `m/MS0037.BIN` itself**. It is entered only from the map.

`entry[6]` picks the entry record, and the first thing each one does is put its
own number in **register 17**:

| record | `r17` | presentation |
|---|---|---|
| `r00` | 0 | 「宝箱が置かれている。」 — *a treasure chest is here* |
| `r01` | 1 | 「豪華な装飾を施した箱が置かれている。」 — *an ornately decorated box is here* |
| `r02` | 2 | nothing printed, no prompt |
| `r03` | 3 | nothing printed, no prompt |

`r00` and `r01` fall into `r04`, which prints 「誰が開ける？」 (*who opens it?*),
runs the party-member picker `r05`, the trap sequence, and then the payout `r08`.
`r02` and `r03` jump straight to `r08`. `r08`'s `1F 8A (rel16, 2, r17)` is why:
the "chest opens" record `r0B` runs only for `r17 < 2`.

**How the object's bytes are read.** `1E AD (3, 21)` is
`0x0042F9F0` → `0x00404520(0x10, 1)` then `0x00417D00(buf)`, which copies the
**16 bytes at `ds:0x0047BB50`** into a script buffer; `1E AC (3, 21, <offset>,
<length>, 3, <dst>)` is `0x0042F950`, which reads `length` bytes little-endian at
`offset` inside that buffer. So:

| bytes | read as | meaning |
|---|---|---|
| `[0]`, `[1]` | engine | tile x, y |
| `[2]` | engine | object kind (`0x88` chest, `0x89` ornate, `0x4F`/`0x8A` pickup) |
| `[3..4]` | `1E AC #3 #2` in `r08` | **item index, or an amount of Macca / Magnetite** |
| `[5]`, `[6]` | engine | script file `0x37`, entry record 0..3 |
| `[7]` | `1E AC #7 #1` in `r08` | **content kind and count** (below) |
| `[11..12]` | `1E AC #11 #2` in `r04`, `r02`, `r03`, `r10` | the **"already opened" flag**, low byte = bank, high byte = bit — the same word shape as an encounter cell's condition (`encounters.md` §3). `1E AF` tests it, `1E AE` sets it in `r10`. |
| `[13]` | — | `[conjecture]` the object sprite; `0x52`/`0x54` for chests, `0` for the two silent kinds |

**`[7]` is one byte doing two jobs.** `r08` switches on it with
`1F 19` (`0x004327C0` mode 0: the first case byte **at or above** the key, so
cases 0, 1, 2 and then a fall-through):

    0        one of item [3..4]      (r0F defaults a zero count to 1)
    1        [3..4] Macca            「…マッカ入手した。」
    2        [3..4] MAG              「…ＭＡＧ入手した。」
    >= 3     [7] copies of item [3..4]

and `r0F`'s head is exactly that default: `1F 80 (rel16, r1)` is "branch when
`r1 == 0` is **false**", so a non-zero `[7]` skips `reg1 = 1` and is used as the
count. If `[7]` is 0 *and* `[3..4]` is 0 the chest prints
「宝箱の中には何も入っていない。」 instead.

Branch polarity was settled from the engine, not assumed:
`0x00434740(op, mode)` evaluates `a - b` and `0x004346B0` dispatches
`op` 0..5 as `!= == <= >= < >`, and the branch is taken when the condition is
**false** (`docs/opcodes.json` `_conditional_branch`). So `1F 80` is
"branch unless `a == 0`", `1F 86` "branch unless `a == b`", and so on.

## 3. The moon gate **[VERIFIED by disassembly + data]**

`m/MS0037.BIN` r04, at `+0x1F`:

    1F 86 (rel16 -> +0x36, r17, 1)     ; branch unless r17 == 1  -- skip the gate
    1F 17 { 14 -> 0C 37 0D ;  15 -> jump +8 ;  28 -> 0C 37 0D ;  FF }

`1F 17` (handler `0x0043027F`) is `0x00436610`, which reads
**`ds:0x00491566`** through `0x00417990`, adds 1, and hands it to the same
threshold walker `0x004327C0` with mode 0. The counter runs 0..27, so the key
runs 1..28, and the only key that is neither `<= 14` nor `<= 28`-after-14 is
**15**. Every other value runs `m/MS0037.BIN` r0D, 「何も入っていない」.

So: **only the ornate chest is gated, and it opens only at counter 14.**

### 3.1 Counter 14 is the full moon

Four independent things say so.

* **`et/ET0003.BIN` is the 28-step damage table** `combat-damage.md` §5 could not
  locate. `0x004179D0` calls `0x00401DD0(3, 12, 0)` — kind 12, `et\et%.4x.bin` —
  reads it plain into `ds:0x0047B8B8` and writes
  **`ds:0x0047BEAC = 0x0047B8B8`**, which is the pointer that section names. It
  is 590 bytes: a 2-byte length and **21 rows of 28 percentages**, the row chosen
  by `actor+0x1F8` and the column by the counter. Row 0 is a flat 50. Of the
  other twenty, **column 14 is the extreme in fourteen of them** — the maximum in
  eleven (row 1 runs 15 … 180 **200** 160 … 15) and the minimum in five (rows 11,
  12, 13, 15, 16, which peak at column 0 instead). The cycle has exactly two
  poles, 0 and 14, half a cycle apart.
* **One counter step is 1520 minutes.** `0x00417960(target)` returns
  `1520 * ((target - counter) mod 28, forced positive) - ds:0x00491564`. 28 steps
  × 1520 minutes = 42 560 minutes = **29.56 days**, the synodic month.
* **The moon icon.** `0x00454C80(counter)` draws sprite
  `word[0x0046B560 + 2*counter]`. Counters 1..13 and 15..27 are the contiguous
  run 638..650, 652..663, 637 — but counter **0 is sprite 110** and counter
  **14 is sprite 111**, two ids from a different bank, adjacent and in that
  order. The two phases that get their own art are new moon and full moon.
  The UI also prints `counter + 1` with `%2d` (`0x0041E873`), so what the player
  reads is **15** at the gate.
* **The story says it.** `m/MS0004.BIN` r01 and r06 and r0A and r0E and r0F and
  r11 are full of 「満月の夜になると、決まって、誰か一人が行方不明になる」 —
  *every full moon night, without fail, someone goes missing* — and
  `m/MS000E.BIN` r0A..r0E each open with the **same `1F 17` shape**
  (`14 -> skip, 15 -> the event, 28 -> skip`) over the abduction scene. The event
  the town calls a full-moon event runs at key 15.

`[conjecture]` Counter 0 is therefore the new moon and the game starts there:
`0x00420B00` zeroes `ds:0x00491560` (day), `0x00491566` (the counter),
`0x00491567` (hour) and `0x00491568` (minute) on a new game.

### 3.2 Everything else the moon gates

Every script site that can see `ds:0x00491566`, found by walking every record of
every `m/MS*.BIN` through the opcode model:

| opcode | what it does | sites |
|---|---|---|
| `1F 17` / `1F 18` | switch on **counter + 1** (`0x00436610`) | 19 + 5 |
| `1E C0 (expr, dst)` | **minutes until phase `expr`** (`0x00417960`) | 3 |
| `1E 31 (kind, dst)` | the current unit's `et/ET0003.BIN` value at this phase, halved (`0x00436630`) | 26 |
| `1E C1`, `1E C2` | the day counter, and the time of day — not the moon | 6 + 5 |

The `14 / 15 / 28` shape — "this arm only at the full moon" — occurs in
`m/MS000E` r0A-r0E (the abduction event), `m/MS0037` r04 (the ornate chest),
`m/MS003A` r1B/r1D, `m/MS0060` r00-r04, `m/MS0064` r02, and the two unreachable
`m/MS6F00` / `m/MS6F1F` r01. `m/MS6800` r01 and `m/MS6500` rC4 — negotiation —
give **key 1 and key 15** their own arms, i.e. the new moon and the full moon.
And `m/MS003F.BIN` r14 is 時だましの香, Time-Cheat Incense: a `1F 18` that sends
the first half of the cycle to r15 (`1E C0 14`, then `1E BF` to advance the
clock) and the second half to r16 (`1E C0 0`) — **it skips you to the next full
or new moon, whichever is closer ahead.** That is the item to carry if you are
farming a full-moon chest.

Outside the script VM, `0x00420CF0` clears bank 0 bit `0x24` when the counter is
14 and bank 0 bit `0x26` when it is 0 — the two phase flags — and, also at 14,
bank 7 bits 254 and 255.

### 3.3 `et/ET0019.BIN`: the chests that come back

`0x00420CF0` ends with `cmp ds:0x00491566, 0x0F` → `0x00420E40`, which walks the
buffer at `ds:0x0047FE50` as `{u8 bank, u8 bit}` pairs to a `0xFF` and calls
`0x00439330(bank, bit, 0)` on each — **clears the flag**. That buffer is loaded
once by `0x00420B00`, the new-game clock init: `0x00401DD0(0x19, 12, 0)` then **`0x00401D40`**, the
plaintext reader — so `encounters.md` §2.1 applies and `container.split` must not
be used on `et/ET0019.BIN`.

The file is 34 bytes: a length word, **15 pairs**, and `FF FF`. Every pair is
bank 4, and every bank-4 flag in the game is a chest's `[11..12]`. So the reset
happens **one counter step after the full moon**, which is exactly what
`m/MS0004.BIN` r01 tells the player:

> 「無尽蔵って言っても、１回に１つしか出てこないみたいよ。
> 次の満月になると、また入ってるみたいだけどね。」
> — *inexhaustible or not, only one comes out at a time; come the next full moon
> there'll be another one inside.*

All fifteen resolve to a real object:

| flag | where | what |
|---|---|---|
| `4104` | Ochanomizu Shelter, floor 14, tile (2,0) | **ornate chest — Diamond** |
| `9904` | Hall of the Cult, floor 2, (0,7) | ornate chest — Topaz |
| `5104` | Ebisu Garden, floor 2, (6,3) | ornate chest — Ruby |
| `4504` | Asakusa Subway, floor 3, (4,5) | ornate chest — Sapphire |
| `4204` | Ochanomizu Stn, floor 1, (3,3) | ornate chest — Emerald |
| `7A04` | Yaesu Arcade, floor 2, (5,1) | ornate chest — Opal |
| `0F04` | Metro Gov't Bldg, floor 4, (5,1) | ornate chest — Lapis Lazuli |
| `5A04` | Roppongi, floor 0, (0,7) | ornate chest — Pearl |
| `2704` | Metro Gov't Bldg, floor 3, (5,1) | ornate chest — Pearl |
| `4A04` | Shinagawa Hotel, floor 4, (8,4) | ornate chest — Aquamarine |
| `5304` | Pleasure Quarter, floor 0, (3,4) | ornate chest — Crystal |
| `6904` | Underground Lab, floor 0, (0,11) | ornate chest — Crystal |
| `7004` | Olympic Pool, floor 3, (11,1) | ornate chest — Onyx |
| `1604` | Metro Gov't Bldg, floor 7, (6,4) | pickup — 520 Macca |
| `5204` | Ebisu Garden, floor 5, (11,9) | pickup — Angel Hair x4 |

Thirteen gem chests, one per gem tier except Moonstone, Turquoise, Rose Quartz,
Garnet, Amethyst — and **the Diamond**. Three ornate chests are *not* on the list
and are therefore once-only: Moonstone (Metro Gov't Bldg floor 11) and the two in
`m/M0081.BIN`, whose map name is 「会話チェック」 *Talk Check* — a debug map.

## 4. The census

`tools/treasure.py` prints it. 235 objects in 45 map files:

| record | presentation | count |
|---|---|---|
| `r00` | chest | 64 |
| `r01` | ornate chest (full moon only) | 18 |
| `r02` | pickup | 86 |
| `r03` | pickup | 67 |

Twenty-seven of them hold a gem. Three hold a **Diamond**, and all three are in
the Ochanomizu Shelter:

| map | floor | tile | kind | renews |
|---|---|---|---|---|
| `m/M0016.BIN` | 14 | (2,0) | ornate chest | **yes** (`4104`) |
| `m/M008A.BIN` | 14 | (2,0) | ornate chest | **yes** — the same flag, so the same chest |
| `m/M008A.BIN` | 9 | (2,6) | ordinary chest | no (`4004`) |

`[conjecture]` `m/M0016.BIN` and `m/M008A.BIN` are two versions of the same
15-floor dungeon: they carry the same location name, the full-moon chest is the
same object with the same flag in both, and `M008A` has almost none of `M0016`'s
ordinary pickups but does have one extra ordinary chest holding a second Diamond
on floor 9 — where `M0016` has a Holy Water. Which version the player is in when,
and by what route, was not traced: the stair lists (`+0x08`) of both files only
ever name their own map id, so both are entered from somewhere else.

## 5. What this corrects in `encounters.md`

§13.2 concluded "the only script site in the game that grants item 167 or 172 is
`m/MS0039.BIN` r1A", and §11.6's table said "chest or event script: none" for
both Topaz and Diamond. The scan was sound and the conclusion was true **of
scripts**; it was the surface that was wrong. Walking up from `0x004236E0` etc.
does reach every caller — the nine callers of `0x004236E0` are the two grant
opcodes, the pack-splitter at `0x00423A04`, and six sites in the item and
equipment menus at `0x0044xxxx` that hand an item back to the inventory (they
unpack the item word with the same `shl 5` / `sar 5` as the sell window,
`encounters.md` §12.4) — but a chest never calls them directly. It
calls `1E F0` *from inside `m/MS0037.BIN` r0F*, with the item in a register the
**map file** supplied, and no static read of the script corpus can resolve that
register. `m/MS0037` r0F was in §13's 15 unresolved register-valued sites in
spirit; it is the case that mattered.

So §11.6 should read:

| route | Topaz | Diamond |
|---|---|---|
| drop | Cassiel, 20%, four areas | none reachable |
| negotiation gem gift | needs a level 41-45 demon | impossible at any level |
| **full-moon chest** | **Hall of the Cult, floor 2 — renews monthly** | **Ochanomizu Shelter, floor 14 — renews monthly** |
| ordinary chest | none holds a Topaz | Ochanomizu Shelter floor 9, once |
| bought from a shop | no | no |
| shopkeeper's gift | 0.096% per transaction | 0.016% per transaction |

The shopkeeper's gift is **not** the only repeatable source of a Diamond. The
ornate chest is, at one per lunar month, and `m/MS0004.BIN` r01 is the game
telling the player so in as many words.

## 6. What is still open

* **Which walker fires object kinds `0x4F` and `0x8A`.** They are not rows of
  `0x00468E50`, so `0x00421880`'s event-list loop skips them, yet 153 of the 235
  entries are one of the two. `0x00421DC0` is a second object walker and was not
  read.
* **The other five object lists.** Only list 10 was decoded; lists 2 (map links)
  and 3, 4, 5, 9 hold NPCs, doors and scenery that this pass did not need.
* **Which of `m/M0016.BIN` and `m/M008A.BIN` the player visits, and when** (§4).
* **`entry[8..10]`.** Read by `m/MS0037.BIN` r04 as `#8 #1` and `#9 #2` / `#9 #1`
  inside the trap sequence; non-zero on only a handful of chests
  (`m/M000B.BIN` floor 2 has `03 0A 0A`). Almost certainly the trap's kind and
  strength, but the trap arm was not decoded.
* **Where the moon counter advances.** `0x00420CE7` writes it and
  `0x00420CC8` reads it, inside the clock tick; the exact step size in minutes
  follows from §3.1's 1520 but was not read off the increment.
