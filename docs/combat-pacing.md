# Combat pacing: what actually schedules turns

Rewritten 2026-09-08, second pass. **The first pass of this file was wrong about
its main claim and is retracted in section 0.** The retraction is kept in place
rather than deleted, because the wrong reading is a very easy one to arrive at
again from the same code.

The player's report was consistent across sessions: *"I was spamming clicks on
the character selector to get a turn in and couldn't, because the enemy was too
fast"*, and in the final Dantalion fight three party members alive against one
enemy produced **six enemy actions and zero party actions**.

---

## 0. Retraction: `0x0042C740` is not the scheduler

The first pass reported that turn order was "a uniform random draw with
replacement" out of a queue at `0x00480AD0`, and recommended patching the draw
to sample without replacement. **Do not do that.** Every instruction quoted was
read correctly; what was wrong was the identification of the data.

`0x00480AD0` / `0x00480CFC` is the **target list**, not a turn queue. Three
independent proofs, any one of which is sufficient:

* `0x0042BA73` writes `0` into the length **immediately before** calling
  `0x0042C740`. A turn queue that is cleared before the scheduler runs is not a
  turn queue.
* `0x0042BAC7` dequeues and stores the result into `ds:0x00491996`, which is the
  **target**. The actor, `ds:0x004919F6`, is not touched anywhere in that path.
* `0x0042B5DB` removes a unit from the list at the moment it dies
  (`0x0042AAE0` = "delete every occurrence"). Pending *targets* need that;
  a turn order does not work that way.

And the call sites give the arguments their real meaning. All three are inside
sub-state 0 of state 24 — "resolve the action this actor already chose":

    0x0042B8D6   command 5 (skill):  0x42C740(rec[0x0A], rec[0x0B], rec[0x0C], target, actor)
                                     rec = 0x00423460(skill id)
    0x0042B9A5   command 2:          0x42C740(7, 0x0A, 0xF1, target, actor)
    0x0042BAB4   item:               0x42C740(rec[5], rec[6], rec[7], target, actor)
                                     rec = 0x0042E4B0(item id)

So `0x0042C740` is the **multi-hit target-list builder**, and the loop at
`0x0042C8D6` picks *which enemies this one attack hits*, not who acts next.

### What `di` is — the first open question, answered

`di` is the number of entries to write into the target list, and it comes from
argument 2, a packed nibble byte in the skill or item record (low nibble `n`,
high nibble `m`):

| `m` | behaviour |
|---|---|
| `0` | draws = `round(max(n,1) x uniform(80..120) / 100)`; pool sampled **with replacement** |
| `1`..`E` | walk the pool **in order**, enqueue each entry `round(max(n,1) x uniform(80..120)/100)` times, draws clamped to the pool size |
| `F` | draws = whatever the sub-effect at `0x0042C9E0` returned, clamped to the pool size |

Sampling *with replacement* is correct here: a random multi-hit attack is
allowed to hit the same target twice. Nothing about it is a bug.

`0x0040B9A0(n, lo, hi)` is `round(n x uniform(100+lo .. 100+hi) / 100)` — an
"n plus or minus x%" helper — built on `0x0040B960(a, b, c)`, the average of
`c+1` uniform draws in `[a, b]`.

### The second open question, answered by the same reading

"Whether any stat feeds the draw" — no. The parameter is a constant byte in the
skill/item record. No actor stat reaches it.

---

## 1. Turn order is an ATB wait counter, ticked per frame

This is the mechanism the first pass was looking for and did not find. It is
also exactly the alternative named in `todo.md` ("an accumulator advanced per
tick ... or a plain agility sort"): **it is the accumulator.**

Every combatant carries a u16 wait counter:

    party member + 0x17F      (the ready flag is the byte at + 0x17E)
    enemy        + 0x199      (the ready flag is the byte at + 0x198)

`0x0043F510(p, speed)` is one tick of one gauge, where the counter is at `p+1`:

    if (*(u16*)(p+1) == 0) return 0            ; already ready
    step = 2 * (1 + rand() % speed) + 5        ; uniform in [7, 2*speed+5]
    if (wait < step) wait = 0 else wait -= step
    return wait != 0                           ; nonzero = still waiting

`speed` is the unit's speed field: **`unit+0x5E`** for a party member (read at
`0x0043F591`), **`enemy+0x78`** for an enemy (read at `0x0040F8D7`).

The counter is reloaded to **255** the moment its owner acts — party at
`0x0040842C`, enemy at `0x0040F901`.

**Both sides tick the same gauge, with the same step formula and the same
reload.** There is no initiative sort and no per-round ordering anywhere.

### The two tick drivers

    0x0043F570   party:  slots 0..5.  Ticks EVERY slot; calls 0x00409420 for
                         each one that just became ready; returns the count.
                         Reached only as a tail jump from 0x0040805A, which
                         first checks the ds:0x00491544 gate.

    0x0040E250   enemy:  slots 0..15, array base 0x004789D0, stride 573 (0x23D).
                         Ticks each slot via 0x0040F890 and **breaks at the
                         first enemy that actually acts**.

`ds:0x00491544` is the master gate. Zero means "enemies do not act":
`0x0040F890` returns immediately on it and `0x00408050` skips the party tick
entirely. It is set to **0** at `0x00408440` — the instant a party member's
queued command begins resolving.

### Cadence — where the real asymmetry lives

Three state handlers tick the gauges. They do not tick them at the same rate:

| state | handler | party gauge | enemy gauge |
|---|---|---|---|
| 11 | `0x00407390` | every frame (`0x0040778A`) | **every frame** (`0x004077F0`) |
| 16 | `0x00412D20` | every frame (`0x00413258`) | **every 4th frame** (`0x00413284`) |
| 34 | `0x00407AA0` | every frame (`0x00407C70`) | **every frame** (`0x00407C7D`) |

The divide-by-four is a free-running counter at `ds:0x0047B7D4`, which has
**exactly one writer in the whole image** — the `inc / and 3` at `0x00413284`.
So the enemy handicap exists *only* in state 16.

**Which state a battle actually runs in therefore decides whether enemies fill
their gauges at the same rate as the party or at a quarter of it.** That is the
single highest-value unknown left, and it is one instrumented play-test away
(log `ds:0x0047BB70` per frame during a fight).

### A caution before anyone rebalances agility

`step` has a floor of 7 and a `+5` constant, so mean time to act is
`255 / (speed + 6)` frames of whichever tick applies. Speed 4 acts about every
26 ticks; speed 24 about every 8.5. **A 6x difference in the stat is only a 3x
difference in turn rate.** Editing the stat tables moves this less than it looks
like it should.

---

## 2. An open message window disables the command UI outright

Unchanged from the first pass and re-verified. Separately from *who* acts, the
player's ability to *input* is hard-gated.

The battle command UI is state 32, `0x0041D530`, and it begins:

    0x0041D530  push $0x2
    0x0041D532  call 0x00404380      ; return flag_word(0x004683F0) & 2
    0x0041D53A  test %ax,%ax
    0x0041D53D  je   0x0041D548      ; bit clear -> run the UI
    0x0041D53F  call 0x00416C20      ; bit set   -> leave; this tick does nothing
    0x0041D547  ret

Bit 1 of `0x004683F0` has **exactly one setter and one clearer in the whole
image**, both inside the message-window subsystem:

    0x0041985E   set   bit 1     (a message window opens)
    0x00419D4B   clear bit 1     (it closes)

So while a battle message is on screen the command UI does not run at all. Not a
side effect: the state handler tests that bit first and returns.

### How long a message holds the gate shut — and what we did to it

    0x00402740   per tick: if 0x004716F8 == 0 and 0x004716F4 != 0,
                 decrement it; on reaching zero, jump to the close path
    0x00402630   set_popup_timer(n):  default 15 when n < 1

**Stock is 15 ticks. This repo already ships 60** — `giten/exe/timing.py`
`POPUP_TICKS = 60`, pinned by `tests/test_timing.py`. We raised it so English
text is readable, and the cost is that **every battle message holds the command
UI shut four times longer than the original did.**

The first pass warned "do not raise this timer". That was too simple: we already
raised it, deliberately. The accurate statement is that the dwell and the input
lockout are the same number, so if the party is losing turns to the lockout the
lever is to *lower* it, or to stop the dwell from holding the gate — not to
raise it further.

---

## 3. Why the battle-state divider did nothing — now properly explained

`7e0b76d` built `dds_dev_btl<n>.exe`, which divides the call site of the battle
state handler (state 24, `0x0042B6A0`) so that machine steps once every N ticks.
It had no perceptible effect.

**The patch was real** — at `0x0041720A`, `dds_dev.exe` calls `0x0042B6A0` while
`dds_dev_btl3/4.exe` call the divider in the cave. The experiment was valid.

It did nothing because **state 24 does not tick the gauges.** State 24 resolves
one already-chosen action; the gauges are ticked from states 11, 16 and 34.
Dividing state 24 slows the *animation* of an action, not the rate at which
actions are granted. The null result is exactly what the mechanism predicts, and
the first pass's explanation of it ("it slows message production by the same
factor") was a guess that happened to land on the right conclusion.

---

## 4. The PC-98 release answers it: the port doubled the step

**Done, same day.** Full write-up: [`pc98-comparison.md`](pc98-comparison.md).

The 1997 PC-9801 release turns out to be the same game -- 1,041 of its 1,548
data files are byte-identical to the Windows ones -- and its combat code ported
across almost literally, which makes the ATB tick findable and the diff exact:

    PC-98   0x0321AA:   add ax, 5             ; step =     1 + rand%speed  + 5
    Windows 0x0043F510: lea ecx,[eax+eax*1+5] ; step = 2*( 1 + rand%speed) + 5

Everything else is verified identical -- reload 255, the party layout (gauge
`unit+0x17F`, ready flag `+0x17E`, speed `+0x5E`, six slots), the enemy layout
shifted 4 bytes by the 32-bit port, the master gate, and the arguments to the
random helper. **The port's entire change to the ATB arithmetic is the `x2`.**

It does two things: everything acts 1.3x-1.8x more often per tick, and the gap
between fast and slow *widens* (relative rate `(s1+11)/(s2+11)` becomes
`(s1+6)/(s2+6)`), which favours whichever side is faster -- the demons, early.
That is a quantitative account of the player's own PC-98 observation.

And it compounds with the frame rate, because the gauge advances once per loop
iteration and this build pins the loop at 60 Hz where a 1997 PC-9821 could not
have come close.

The restoration is four bytes at `0x0043F52F`, same length, no cave:
`8D 4C 00 05` -> `8D 48 05 90`. **Shipped in the release 2026-09-08**, together
with putting the popup dwell back to the stock 15 -- they are one decision,
because the dwell is also how long the command UI is refused (§2).

The rest of this section is the reasoning that led there, kept because it is
the right shape for the next question of this kind.

The gauges advance **per frame of a state handler**, so:

* The party:enemy *ratio inside one state* is frame-rate independent — both
  sides advance on the same tick. A "PC-98 feels slower" observation alone does
  **not** implicate the loop rate.
* The *absolute* rate is entirely frame-rate dependent, and the player's
  thinking time is wall-clock. A loop running several times faster than a 1997
  PC-9821 managed makes every gauge fill several times faster in real seconds
  while the human at the keyboard does not speed up.

That splits the question into two things PC-98 footage can actually settle:

1. **Count enemy actions per party action in a PC-98 battle.** If that ratio
   matches this build's, the port did not change the balance and the whole
   difference is wall-clock speed — the lever is the loop rate. If the PC-98
   ratio is materially lower, something structural differs: the divisor, or
   which state battles run in, or the stat tables.
2. The already-recorded observation — *"PC-98 enemies act far less often and
   several party members act before the enemy does"* — reads as evidence for
   **(1) second branch**, i.e. a structural difference, which under this
   mechanism most plausibly means the enemy divisor or the battle's state.

Caveat, stated because it is tempting to forget: the PC-98 release is a separate
build for a different CPU. Its executable cannot be diffed against this one.
It is useful as a **behavioural reference**, and potentially for its **data** —
if the `et/` databases are close enough between the two releases, the speed
column can be compared directly, which is a cheap and decisive experiment.

---

## 4b. Measured: what the restored step actually did

Play-tested 2026-09-08 on `dds_dev_atb.exe`, counted with
`tools/battle_ratio.py`, which counts the announcement *span* the engine picks
rather than the rendered English -- see its docstring for why three earlier
attempts from the glyph log disagreed with each other.

| session | build | party | enemy | ratio | battles won |
|---|---|---|---|---|---|
| `2026-09-06b-murmur` | dev | 32 | 39 | 1 : 1.22 | 76 |
| `2026-09-07c-softlock` | dev | 8 | 95 | 1 : 11.88 | 138 |
| `2026-09-07e-newsave-bat4` | btl4 | 2 | 37 | 1 : 18.50 | 68 |
| **`2026-09-08-atb`** | **atb** | **80** | **11** | **1 : 0.14** | **81** |

The player's report on the last row: *"it feels perfect now. I still lost the
fight, but you can see from the trace and textout that I was able to actually
fight back."* And, after seeing the numbers and having played both releases:
**"this patch is gold. it honestly gives parity between the two versions."**

That verdict is the evidence that matters here, and it is worth being clear about
why. Whether combat *feels* like the original is not a question a disassembler
can answer -- it is a question for someone who has played both. The arithmetic
predicted parity (§4: our 60 Hz against the PC-98's hardware-locked 56.4, and the
step restored to the 1997 formula, so both clocks and both formulas match within
a few percent). The person who has played both reports parity. The prediction and
the play-test agree, which is the strongest position this question has been in.

**Two honest caveats, neither of which changes the verdict.**

*The sessions are different content* -- different areas, enemies and lengths --
so this is not a controlled experiment. Battles won are the same order of
magnitude across all four (68-138), so these are comparable session lengths, and
the swing is 130x, far outside what content variation plausibly explains.

*The gun line is unattributed.* `r04[5]` ("'s {04:02} opened fire") is used by
both sides and the tool refuses to guess: 81 in the ATB session against 30-36 in
each earlier one. Assign **every** gun attack to the enemy and the ATB session is
still 80 : 92 = 1 : 1.15, better than all three; assign them all to the party and
it is 1 : 0.07. It does not track either side cleanly across sessions -- in
`2026-09-07e` the party made 2 attributable attacks and 33 gun attacks -- which
is why it stays out of the count until something settles it.

So under the most hostile assumption available, the restored step still moved the
worst session from 1 : 35 to 1 : 1.15.

---

## 5. What is still not known

* **Which state a battle runs in** (11, 16 or 34). Decides the enemy divisor.
  Highest value, cheapest to answer. The PC-98 side of the same question is
  blocked by Microsoft overlay thunks -- see `pc98-comparison.md` §4.
* ~~**The PC-98 main-loop rate.**~~ **Answered by disassembly, not footage.**
  `DDS98.EXE` hooks the vertical-sync interrupt (ISR at `0x0112E8`, acknowledge
  `out 0x64,al`, page flip `out 0xA4,al`), so the PC-98 clock is the display
  refresh -- 56.4 Hz at 24.83 kHz, 70.1 at 31.47 -- and does not scale with CPU
  speed. Our 60 Hz is within ~6% of it. See `pc98-comparison.md` §3.
* **Whether the gauges advance while a message window is up.** The popup
  countdown is driven from the main loop (`0x00401980` -> `0x00402740`), not
  from a state, so if the current state stays at 11/16/34 during a message then
  the gauges keep filling while the player is locked out — and our 60-tick dwell
  is directly costing the party turns. If a message instead makes state 32
  current, they do not. Not resolvable statically with confidence.
* **What sets the "a command is queued" flag** `[unit+0x17E]`. Written at
  `0x00409B16` and `0x00409BE3`, both inside `0x00409620`, the battle
  command-input driver, which has not been read.
* Whether `unit+0x5E` / `enemy+0x78` are literally the displayed Agility stat
  (`0x0046A28C`, "Agility" / the Japanese label) or a derived speed.

---

## 6. Addresses

| address | what |
|---|---|
| `0x0043EF60` | status walker: all 35 slots, once per gauge tick |
| `0x0043EFA0` | one status slot: gate, rate-table lookup, add, clamp |
| `0x00469F08` | **status rate table**, 35 x u16; zero = that status never ticks. Byte-identical to the PC-98 exe (`pc98-comparison.md` §3b) |
| `unit + 5 + n` | status slot `n`, one byte, 0..255 |
| `0x0040B890` | clamp(v, lo, hi) |
| `0x0043F510` | **one ATB gauge tick**: `step = 2*(1+rand%speed)+5`, counter at `p+1` |
| `0x0043F570` | party gauge tick, slots 0..5; calls `0x00409420` on ready |
| `0x0040E250` | enemy gauge tick, slots 0..15; breaks at the first that acts |
| `0x0040F890` | one enemy's gate: master gate, status, then `0x0043F510` |
| `0x00408330` | party input driver (`0x00408200`, `0x00408050`, `0x0043F5F0`) |
| `0x00408050` | gate check, then tail-jump to `0x0043F570` |
| `0x0043F5F0` | first party slot with a queued command, or -1 |
| `unit+0x17E` / `unit+0x17F` | party ready flag / u16 wait counter |
| `unit+0x5E` | party speed field |
| `enemy+0x198` / `enemy+0x199` | enemy ready flag / u16 wait counter |
| `enemy+0x78` | enemy speed field |
| `0x004789D0` | enemy array base, stride 573 (`0x23D`), 16 slots |
| `ds:0x00491544` | **master gate**: 0 = enemies do not act, gauges do not tick |
| `ds:0x0047B7D4` | the divide-by-four counter; one writer, `0x00413284` |
| `ds:0x004919F6` / `ds:0x00491996` | current actor / current target |
| `0x0040B940` | `rand() % (n+1)` |
| `0x0040B960` | average of `c+1` uniform draws in `[a, b]` |
| `0x0040B9A0` | `round(n * uniform(100+lo..100+hi) / 100)` |
| `0x0045B290` | CRT `rand()` |
| `0x00417160` | state dispatcher; 41 states via the table at `0x00417288` |
| `0x0047BB70` / `0x0047BB72` / `0x0047BB74` / `0x0047BB76` | state / sub / sub-sub / sub-sub-sub |
| `0x00407390` / `0x00412D20` / `0x00407AA0` | states 11 / 16 / 34 — the three gauge tickers |
| `0x0042B6A0` | state 24, resolve one action, 9 sub-states via `0x0042C02C` |
| `0x0042AB40` | the only launcher of state 24; busy flag `ds:0x00480D00` |
| `0x0041D530` | state 32, battle command UI |
| `0x004683F0` | UI flag word; **bit 1 = a message window is open** |
| `0x0041985E` / `0x00419D4B` | the only setter / clearer of bit 1 |
| `0x004716F4` / `0x004716F8` | popup countdown / its pause flag |
| `0x00402630` | `set_popup_timer(n)`, stock default 15; **we ship 60** |
| `0x0042C740` | multi-hit **target-list** builder (NOT a scheduler) |
| `0x00480AD0` / `0x00480CFC` | the **target list** and its length |
| `0x0042AA50` / `0x0042AAA0` / `0x0042AAE0` | target list append / pop / remove-all |
