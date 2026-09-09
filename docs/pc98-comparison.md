# The 1997 PC-9801 release, as a reference implementation

Written 2026-09-08 from the PepsimanGB disc dump (ISO 9660, volume `DDS98`,
`DDS98.EXE` dated 1997-03-10, 480,710 bytes). Reproduce anything here with
`python tools/pc98_diff.py <path to DDS98>`.

The headline: **the PC-98 release and the Windows port are the same game.** Of
the 1,548 data files on the disc, **1,041 are byte-identical** to what the
Windows version ships. That makes the disc a reference implementation for this
project rather than a curiosity -- where a file is identical, the port changed
nothing; where it differs, the diff *is* the port's edit.

---

## 1. The file survey

| family | total | identical | differ | not in Windows |
|---|---|---|---|---|
| `CA` | 257 | **257** | 0 | 0 |
| `P` | 432 | 395 | 37 | 0 |
| `MS` | 200 | 159 | 41 | 0 |
| `M` | 100 | 82 | 18 | 0 |
| `ET` | 86 | **79** | 7 | 0 |
| `SB` / `SM` | 24 / 24 | all | 0 | 0 |
| `ID` | 17 | **17** | 0 | 0 |
| `A`, `SE`, `ST` | 4 | all | 0 | 0 |
| `FC` | 401 | 0 | 166 | 235 |

`FC` is the artwork, which the port redrew at a higher resolution -- every one
differs and 235 have no Windows counterpart. Everything else is the game.

Only **103 non-graphics files differ at all**, and most `MS`/`M`/`P` deltas are
small (a few bytes to a few hundred). Those are the port's script edits and are
worth reading whenever a script's behaviour is in question.

Files on the disc with no Windows counterpart, besides art: `DDS98.EXE`,
`MIDE.DRV`, `NMUSE.DRV`. Windows adds `.MDS` music, `.BMP` art, `CONFIG.EXE`
and the `FC2xxxx` high-resolution families.

---

## 2. `et/ET0004.BIN` -- the port rebalanced the skills

Same size, same 309 records, **73 of them carry different numbers, and not one
record's name or description text changed.** Every difference is a number
somebody deliberately retuned. By header offset:

    +0x00: 5   +0x01: 16   +0x02: 15   +0x03: 3   +0x05: 25   +0x06: 3
    +0x07: 2   +0x08: 1    +0x09: 3    +0x0A: 12  +0x0B: 10   +0x0D: 1
    +0x0E: 4   +0x0F: 2    +0x11: 1    +0x13: 6

Patterns worth knowing:

* **Records 1-15, every basic weapon attack** (剣攻撃, 攻撃, ハンドガン,
  マシンガン, 襲撃, 鈍器攻撃, 突き攻撃, 鞭攻撃, ショットガン, レーザーガン and
  攻撃11-15) all take the same edit: `+0x01: 18 -> 0` and `+0x02: 1 -> 0`.
  Fifteen records, two fields, zeroed together.
* **Every healing skill got stronger.** ディ 25->40, ディア 80->120,
  ディアラマ 180->250, ディマール 120->150, メディ 20->30, メディア 60->90,
  メディアラマ 160->200 -- all at `+0x0A`.
* **Buffs up, debuffs down.** タルカジャ / スクカジャ / ラクカジャ / マカカジャ
  `+0x0B: 8 -> 10`; タルンダ / スクンダ / ラクンダ / マカンダ `+0x0B: 8 -> 5`.
* `+0x05: 1 -> 6` on 25 records is the single most common edit.

`+0x0C` -- the packed hit-count nibble byte that `0x0042C740` reads (see
[`combat-pacing.md`](combat-pacing.md) §0) -- **changed in zero records.**

The other six differing `ET` files are `ET0000` (8 bytes), `ET0001` (items,
substantially), `ET0008`, `ET0011`, `ET0020` and `ET0028` (16 bytes).
`ET0022`, `ET0018` and `ET0040` are byte-identical.

---

## 3. The ATB step: the port doubled it

This is the answer to "what is the intended speed of combat".

`DDS98.EXE` is a plain 16-bit MSC 8.0 real-mode DOS program (`MS Run-Time
Library - Copyright (c) 1992, Microsoft Corp`), Microsoft-overlay linked, using
the **pascal** calling convention (`retf N`). The combat code ported across
almost literally, which makes the routines findable and the diff readable.

### Finding it

`0x0040B9A0` in the Windows exe is `round(n x uniform(100+lo..100+hi)/100)` and
opens with two `add eax,0x64`. The 16-bit form `add ax,0x64` occurs **exactly
twice in the whole PC-98 image, adjacent**, at file offset `0x01D99B`. That
pins the whole random-helper family:

| what | Windows VA | PC-98 file offset |
|---|---|---|
| `rand() % (n+1)` | `0x0040B940` | `0x01D93E` |
| `a + avg of (c+1) draws in [a,b]` | `0x0040B960` | `0x01D950` |
| `round(n x uniform(100+lo..100+hi)/100)` | `0x0040B9A0` | `0x01D98A` |
| **one ATB gauge tick** | **`0x0043F510`** | **`0x0321AA`** |
| party gauge tick, slots 0..5 | `0x0043F570` | `0x03D8B4` |
| the master-gate wrapper | `0x00408050` | `0x065312` |
| per-enemy gate | `0x0040F890` | `0x06F9C4` |
| master gate word | `ds:0x00491544` | `ds:0x97D2` |

### The two routines, side by side

PC-98 `0x0321AA`:

    if (*(u16*)(p+1) == 0) return 0
    ax = uniform_avg(1, speed, 0)        ; 1 + rand()%speed
    add ax, 5                            ; <-- 05 05 00
    if (wait < ax) wait = 0 else wait -= ax
    return wait != 0

Windows `0x0043F510`:

    if (*(u16*)(p+1) == 0) return 0
    eax = 0x0040B960(1, speed, 0)        ; 1 + rand()%speed
    lea ecx,[eax+eax*1+5]                ; <-- 8D 4C 00 05
    if (wait < ecx) wait = 0 else wait -= ecx
    return wait != 0

**Everything else is identical**, and verified so, not assumed:

* same reload, **255** -- PC-98 `mov word [..+0x17F],0x00FF` (party, six sites)
  and `mov word [..+0x195],0x00FF` (enemy); Windows `0x0040842C` and
  `0x0040F901`;
* same party layout -- gauge at `unit+0x17F`, ready flag at `unit+0x17E`, speed
  at `unit+0x5E`, **six** slots;
* same enemy layout, shifted 4 bytes by the 32-bit port -- gauge `+0x195` vs
  `+0x199`, speed `+0x74` vs `+0x78`, stride `0x238` vs `0x23D`, **sixteen**
  slots;
* same master gate, same argument values to the random helper (the pascal /
  cdecl push orders cancel out -- both call `f(1, speed, 0)`).

So the port's whole edit to the ATB arithmetic is `x2`.

### What the x2 does

Mean step is `speed/2 + 5.5` on PC-98 and `speed + 6` on Windows. Against a
reload of 255, mean ticks to act:

| speed | PC-98 `510/(s+11)` | Windows `255/(s+6)` | Windows acts in |
|---|---|---|---|
| 4 | 34.0 | 25.5 | 75% of the ticks |
| 8 | 26.8 | 18.2 | 68% |
| 12 | 22.2 | 14.2 | 64% |
| 16 | 18.9 | 11.6 | 61% |
| 24 | 14.6 | 8.5 | 58% |
| 32 | 11.9 | 6.7 | 57% |

(Ticks computed from the mean step. The real value is slightly lower on both
sides, because a step larger than the remaining wait clamps it to zero rather
than overshooting; the ratio between the columns is what matters here.)

Two consequences, and the second is the one that matters:

1. **Everything acts 1.3x to 1.8x more often per tick.**
2. **The gap between fast and slow widens.** The relative rate of two
   combatants is `(s1+11)/(s2+11)` on PC-98 and `(s1+6)/(s2+6)` on Windows.
   For speeds 24 vs 10 that is 1.67 against 1.88; for 32 vs 8, 2.26 against
   2.71. The port's change **systematically favours whichever side is faster**,
   which in this game's early fights is the demons.

That is a quantitative account of the player's own PC-98 observation -- *"PC-98
enemies act far less often and several party members act before the enemy
does"* -- and it is a real difference in the port, not in this patch.

### And then the frame rate multiplies it

The gauge advances **once per iteration of the main loop**. The 1999 Windows
binary free-ran as fast as the machine could draw; our release pins it at 60 Hz
(`pace()` in `hook.c`, see `giten/exe/timing.py`). A 1997 PC-9821 drawing this
first-person view certainly managed far fewer than 60. So the two effects
compound: whatever the PC-98 loop rate was, the Windows build multiplies the
gauge by `(60 / that rate) x (1.3..1.8)`.

**The PC-98 loop rate is not established here** and should not be guessed. It
is measurable from footage -- and it is the last number needed to say how much
faster this build is than the original.

### The faithful fix, if we want one

Restoring the original's own arithmetic is a **four-byte, same-length, in-place
patch** with no relocation and no cave:

    VA 0x0043F52F  (file offset 0x0003E92F in dds_org.exe)
    old:  8D 4C 00 05      lea ecx,[eax+eax*1+5]
    new:  8D 48 05 90      lea ecx,[eax+5] ; nop

It touches nothing else -- same reload, same distribution, same everything --
and it narrows the fast-vs-slow gap back to what the 1997 release had. It is
**not applied**; it is a deliberate gameplay change and belongs to the person
playing the game, not to the translation.

The blunter alternative is lowering `pace()` below 60 Hz, which slows animation
and everything else along with combat.

---

## 4. What is not established

* **The enemy cadence on PC-98.** The Windows build divides the enemy gauge
  tick by four, but only in state 16 (`ds:0x0047B7D4`, single writer
  `0x00413284`). Whether the PC-98 build has the same divisor is unresolved:
  `DDS98.EXE` routes most inter-module calls through Microsoft overlay thunks
  (404 `INT 3Fh` sites), so the direct-call scan that found the leaf routines
  cannot find their callers. Resolving it needs the overlay map.
* **The PC-98 main-loop rate**, as above.
* **What the changed `ET0004` fields mean.** The offsets are known to be read
  (`+0x0A`, `+0x0B`, `+0x0C` reach `0x0042C740` through `0x00423460`), but only
  `+0x0C` has a confirmed meaning.
* Whether the 41 differing `MS` scripts and 18 `M` files change anything the
  translation should follow. Unexamined.
