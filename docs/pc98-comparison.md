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

### And then the frame rate -- but the PC-98's is hardware-locked

The gauge advances **once per iteration of the game's clock**, so the clock rate
matters as much as the step. The two builds get theirs very differently.

**PC-98: the vertical-sync interrupt.** `DDS98.EXE` installs a VSYNC ISR at
`0x0112E8` -- `pusha / push ds / push es`, a re-entrancy guard at `ds:0x6E6`, a
switch to a dedicated interrupt stack, and a call to the per-frame worker at
`0x014470`. It acknowledges the interrupt through the PC-98's VSYNC reset port
(`0x0112DC`: `xor ax,ax ; out 0x64,al`) and flips the display bank on the same
event (`xor ds:0x6E2,1` then `out 0xA4,al` at `0x0112D3`). The 38 `out 0x02`
and 16 `out 0x00` sites are the PIC mask and EOI that go with hooking IRQ 2.

That makes the PC-98 clock a **hardware constant**: the display refresh, 56.4 Hz
in the standard 640x400 24.83 kHz mode or 70.1 Hz at 31.47 kHz. It does not
scale with CPU speed. A machine too slow to finish a frame misses a retrace and
drops to *half* rate -- it never runs fast.

**Windows: whatever the display driver happens to do.** The stock loop at
`0x0045104E` steps whenever `timeGetTime` has advanced a millisecond, so its only
real governor was DirectDraw `Flip` blocking on retrace. Take that away -- a
modern driver, dgVoodoo2, a windowed mode -- and the ceiling becomes the actual
rate, up to 1000 Hz. Our release pins it at 60 Hz (`pace()` in `hook.c`).

**So 60 Hz is within about 6% of the PC-98's 56.4.** The clocks are effectively
the same, which means the `x2` on the step is not compensating for a clock
difference on this hardware -- it simply makes combat twice as fast as the
original. Restore the step and the pacing lands within a few percent of 1997.

(This also gives the compensation hypothesis in §4 a sharper form: a 1997 PC
that could not finish a Windows frame in one retrace would have run at *half*
rate, 30 Hz against the PC-98's 56.4, and doubling the step restores parity
exactly. That is consistent with everything here and still unproven.)

**Caveat.** What is established is that the PC-98 *display* is vsync-driven with
page flipping on the interrupt. That the ATB tick hangs off that same clock
rather than a separate free-running loop is not proven -- the overlay thunks
block the caller trace (§5) -- though a separate logic clock would be an odd
design next to this one.

### The faithful fix, if we want one

Restoring the original's own arithmetic is a **four-byte, same-length, in-place
patch** with no relocation and no cave:

    VA 0x0043F52F  (file offset 0x0003E92F in dds_org.exe)
    old:  8D 4C 00 05      lea ecx,[eax+eax*1+5]
    new:  8D 48 05 90      lea ecx,[eax+5] ; nop

It touches nothing else -- same reload, same distribution, same everything --
and it narrows the fast-vs-slow gap back to what the 1997 release had.

**It is not in the release build**, and should not be: combat speed is a
gameplay decision, not a translation one. It is in one dev build, for testing:

    python -m giten exe dev-atb     ->  build/exe/dds_dev_atb.exe

`dds_dev_atb.exe` differs from `dds_dev.exe` in **exactly four bytes** -- three
in the gauge step and one in the popup default, which it holds at the **stock
15 ticks** rather than the 60 the release raises it to. That second point is
deliberate: an open message window hard-disables the command UI, so our longer
dwell is itself a pacing change, and leaving it stock keeps the gauge the only
variable. English battle messages flash past in that build; that is the cost of
a clean comparison. Both builds carry the tracer, so a route played on each can
be diffed token for token.

The blunter alternative is lowering `pace()` below 60 Hz, which slows animation
and everything else along with combat -- measured and rejected already
(`docs/todo.md`: 30 and 40 Hz make walking unbearable).

---

## 4. Was the port playtested?

Worth writing down, because the obvious reading of "combat is unplayably fast"
is "nobody tested it", and the evidence says otherwise.

**Against "untested":**

* Somebody made a **surgical, single-instruction edit to the combat pacing
  constant.** A compiler retranslating the same C would emit the same
  arithmetic; `add ax,5` becoming `2*x+5` means a person changed the source.
* Somebody made a **balance pass over the skill table** -- 73 of 309 records,
  including the *same* edit applied to all fifteen basic weapon attacks and a
  buff to every healing skill. That is deliberate tuning, not drift.
* The port **redrew every asset** at 10-20x the size. A studio spending that
  does not skip QA on the combat system.

**And the direction is the tell.** The port *doubled* the step, which makes
combat **faster**. If the change were compensating for a Windows loop that ran
*faster* than the PC-98's, they would have halved it. Doubling only makes sense
as compensation for a loop that ran **slower** -- which is exactly what you would
expect from art 10-20x larger being blitted at 8bpp through DirectDraw on a 1997
Pentium.

So the likely story is not "they never tested it". It is **"they tested it on
1997 hardware, where the port ran slower, and compensated in the direction that
is now backwards."** Modern hardware runs the loop far faster than either 1997
machine, and the doubled step sits on top of that.

**The actual defect is upstream of any of this.** The stock main loop at
`0x0045104E` runs one update+render whenever `timeGetTime` has advanced by a
millisecond -- a 1000 Hz ceiling, which is not a frame-rate target, it is "as
fast as possible with a trivial guard". What really held it back in 1999 was
DirectDraw's `Flip` blocking on the vertical retrace. **The engine delegates its
clock to the display hardware, and measures every duration in loop iterations.**
On a PC-9821 that is a defensible assumption: a narrow, known family of machines.
On Windows 95 it is not, and the moment `Flip` stops blocking -- dgVoodoo2, a
modern driver, a windowed mode -- the ceiling becomes the real rate and
everything frame-counted runs up to 16x too fast.

They did not fail to test. They failed to own the clock.

That also answers the objection that movement would have given them away: if the
port ran *slower* on their hardware, movement felt fine or slightly sluggish and
there was no signal to act on. Frame-coupled movement is a property of both
builds; what differs is that the PC-98 target was one machine family and the
Windows target was everything from a 486 to a Pentium II.

**Caveat, because this is inference and the rest of this document is not:** the
PC-98 loop rate has not been measured, so "the port ran slower on period
hardware" is a hypothesis consistent with the doubling, not a fact. The
competing reading -- they simply wanted snappier combat in the port -- fits the
`x2` equally well. Two things would separate them:

1. **Whether a 1997 Windows PC held one retrace per frame or dropped to half
   rate.** The PC-98 clock is now known -- it is the vertical-sync interrupt,
   hardware-locked (§3) -- so the open half is the port's own period rate.
2. **Whether the enemy-gauge divisor is Windows-only.** The Windows build ticks
   the enemy gauge only every fourth frame in state 16 (`ds:0x0047B7D4`). If the
   PC-98 build has no such divisor, then the port doubled everyone's step *and*
   quartered the enemy's tick rate -- a net enemy slowdown, which would be
   strong evidence of deliberate tuning toward the player and would settle this.

## 5. What is not established

* **The enemy cadence on PC-98.** The Windows build divides the enemy gauge
  tick by four, but only in state 16 (`ds:0x0047B7D4`, single writer
  `0x00413284`). Whether the PC-98 build has the same divisor is unresolved:
  `DDS98.EXE` routes most inter-module calls through Microsoft overlay thunks
  (404 `INT 3Fh` sites), so the direct-call scan that found the leaf routines
  cannot find their callers. Resolving it needs the overlay map.
* **That the PC-98 ATB tick is on the VSYNC clock**, rather than a separate
  free-running loop. The display certainly is (§3); the gauge is inferred.
* **What the changed `ET0004` fields mean.** The offsets are known to be read
  (`+0x0A`, `+0x0B`, `+0x0C` reach `0x0042C740` through `0x00423460`), but only
  `+0x0C` has a confirmed meaning.
* Whether the 41 differing `MS` scripts and 18 `M` files change anything the
  translation should follow. Unexamined.
