# Open work, newest findings first

Kept because the same items kept being rediscovered from scratch. Each one says
what is *measured*, so nobody has to re-derive the number before deciding
whether to do it. Tick items here when they land; delete nothing.

---

## Done

### ✅ `m/MS6xxx` gets no English — SHIPPED 2026-09-08

`rebind()` asked two questions a merged buffer cannot answer. *Which file is
this?* — by hashing the whole 1024-byte record index, which belongs to a merge
of up to five files. *Where does this span go?* — from our model of one file's
layout, which the merge moves. So it returned 0 and 7,943 spans were never
served.

overlay.dat **v5** asks neither. A span carries the record it lives in, its
offset inside that record, and a hash of the Japanese it replaces:

    addr = live_index[rec].offset + rec_off
    serve only if fnv1a(live[addr : addr + jp_len]) == jp_hash

| | |
|---|---|
| m/MS6000's spans that resolve, over all 25 merges | **7,310 of 7,400 (98.8%)** |
| every merged file's spans | **18,024 of 18,192 (99.1%)** |
| the 90 that do not | records another file replaced — refused, not mis-served |
| m/MS6000's spans against a *wrong* buffer | **0 of 109** |

Virtual addresses now follow the live image end, because a merged buffer is
longer (`m/MS6000` c0: 0x1D7B alone, 0x23D4 merged) and tails handed out from
the old end would land on records that only exist in the merge.

Verified end to end in the real C, not just the model:
`test_the_c_hook_serves_a_merged_buffer_the_way_the_model_does` walks the exact
`hook.c` that goes into the exe over the image the engine builds for a demon
conversation, under file id `0xE0` — the id no filename maps to — across all 98
records, and demands the same bytes as the model. 203 tests pass.

Installed: v5 `overlay.dat` and six rebuilt exes in `play/en/ddswin`. The exe
cave grew 2048 -> 3072 bytes for the two verification bitmaps; **the in-place
count is unchanged at 38 bytes**, which is what
`test_the_exe_is_only_as_patched_as_the_documentation_says` exists to hold still.

**Not play-tested.** Follow-up: `rebind` maps `0xE0 + slot` to `m/MS6000`'s
container, so only that entry is reachable per merged buffer. The
demon-specific files' own spans need the hook to try more than one entry —
worth roughly the difference between 7,310 and 18,024 above.

---

### ✅ Serve a merged buffer from every file in it — SHIPPED 2026-09-08

`m/MS6000` is only the shell: 296 spans, 4 KB, the prompts and the approach
menus. The demon files merged onto it hold **7,647 spans and 170 KB** — every
line a demon says — and the hook could reach none of it, because one buffer
could bind only one entry.

The rule is the cheapest one that works: **an entry belongs to this buffer when
every one of its spans verifies against it.** A file not in the merge fails on
the first record the merge does not share with it. That is the per-span hashing
the hook already does, read as a per-entry verdict — no extra data in
overlay.dat, no new engine address, no hook on the loader.

Measured over all 25 `et/ET0007` rows x 16 slots: **17,309 placements accepted
against 7,310**. At most 5 entries and 274 spans bind to one buffer. Exactly two
addresses in the whole family are claimed by two entries with different English
(`Mwah!` / `*Smooch*`, `Please` / `Please!`) — both correct renderings of the
same Japanese, so the tie-break only has to be repeatable: candidates are tried
in file-id order and the first to claim an address keeps it.

**The C conformance test earned its keep here.** The first version had every
bound entry start its virtual space at the same address, so several entries
answered the same virtual PC and the walk never terminated. The model and the C
agreed — both were wrong — and the test caught it because it walks to a *real*
stop address. Each entry now gets a stacked, disjoint window.

---

### ✅ Stop promoting reference drafts into the macro pools — 2026-09-08

A pool record is not a line, it is a fragment spliced into every sentence that
calls it (`m/MS7F07` record 0x52: 3,931 call sites). A reference translation was
written against at most one of those sentences, so it cannot be right in the
rest *by construction*. `tools/make_draft_tree.py` now refuses the whole class:
**297 rows held back**, worth 5,351 call sites. The 76 pool rows a person wrote
by hand in `tables/` are untouched and carry 21,910 call sites — four times the
coverage — because a person picked the ones that are actually words.

Shipped damage this removes, both seen on screen 2026-09-07 in one sentence:
`m/MS7F02` 0:0C `され` → "was" (793 sites) and `m/MS7F01` 0:0A `ま{08:66}` =
ません → "not" (393 sites), which rendered as `AMS用マップDataが登録wasていnot`.

No "is this grammar?" test was built, and `tests/test_pool_promotion.py` pins
why: "pure hiragana" refuses `はい` → Yes and `ありがとう` → Thank you, which are
words; "has no pool call" misses `ま{08:66}`, which is not one. Whether a
fragment is a word is not decidable from its characters. The line that *is*
decidable — a person wrote it, or a promotion did — is the one drawn.

---

## Open

### Presentation (upscaling / shaders) -- proposal, nothing built

[`docs/presentation.md`](presentation.md), 2026-09-09. Asked whether the sprites
could be extracted, upscaled and put back to fix how rough it looks in
fullscreen. **They can be extracted trivially -- all 1,577 `fc/` files are plain
BMPs -- but upscaling them would not fix it.** Every file is 8bpp (256 colours),
and 640x480 is hardcoded in the display setup: `push 0x1E0` occurs exactly four
times in the whole image, twice each at `0x00450AC9` and `0x00450C9B`. There is
no other resolution path, so the full-screen art is already native and anything
larger is downsampled straight back.

The dgVoodoo2 config is already optimal (`max_isf` + `pointsampled`, both
bilinear paths off), so what is on screen is an honest integer scale of 640x480.
The proposal is a post-process shader instead -- ReShade over dgVoodoo2, CRT
first -- which sidesteps both the palette and the framebuffer and touches no
game file. Untested.

**The part that matters to the translation regardless:** build the `fc/`
extractor and check whether any of the 239 full-screen images have Japanese text
baked into the bitmap. No table covers those, and they would ship untranslated
without anyone noticing.

### Release / distribution -- planned, nothing built

[`docs/distribution.md`](distribution.md), written 2026-09-09. Design and
measurements only; every claim is marked measured or conjecture.

The short version: **not a 1.0.** `tables/` is 41.0% translated (18,497 of
45,083 rows) while the installed build is 97.7% -- the difference is 25,527 rows
and 953,674 characters promoted from v0.05, about 61% of the shipped text, which
the v0.05 policy says is never a build input. `giten check` reports 1,479
errors. 1.0 means every shipped line is ours or `reviewed`, zero errors, and the
four known visible defects closed. Until then it is a **0.9 public beta**, which
is worth shipping.

**The one task that gates two sections of that plan: get a clean retail install
and hash it.** Our `original/ddswin` has `dds_org.exe` only because someone ran
the XP tool -- it is that tool's backup -- so a clean copy almost certainly has
`dds.exe` = `9b810530...` and no `dds_org.exe`, and a patcher that opens
`dds_org.exe` by name would fail on exactly the users it needs to serve. That
inference has never been checked against an actual clean install.


### ✅ CLOSED: combat difficulty is the Windows port's own balance -- and it is now fixed

Settled 2026-09-08 by the person playing it, against PC-98 footage of the same
game: PC-98 enemies act far less often and several party members act before the
enemy does. **That difference is the port's, not this patch's.** Nothing here
caused it.

~~Nothing here should try to "fix" it.~~ **Superseded the same day.** The cause
turned out to be one instruction (below), the restoration is four bytes, and the
person playing has tested it and given the verdict: *"this patch is gold. it
honestly gives parity between the two versions."* Measured 80 party actions to
11 enemy, against 1 : 1.22, 1 : 11.88 and 1 : 18.50 in the three archived
pre-patch sessions (`docs/combat-pacing.md` §4b, `tools/battle_ratio.py`).

**The one decision left is whether it ships**, and it is not a technical one --
see the open item immediately below.

**Confirmed from the PC-98 disc later the same day, and now quantified.**  The
1997 PC-9801 release is the same game (1,041 of 1,548 data files byte-identical)
and its combat code ported across almost literally.  The port's entire change to
the turn gauge is one instruction: `add ax,5` became `lea ecx,[eax+eax*1+5]`, so
the ATB step doubled.  Everything acts 1.3x-1.8x more often per tick and the
fast-vs-slow gap widens, favouring the demons.  A faithful restoration is four
bytes at `0x0043F52F` (`8D 4C 00 05` -> `8D 48 05 90`), **not applied** -- it is
a gameplay change and belongs to the player, not the translation.  The port also
retuned 73 of the 309 skill records.  Full write-up:
[`docs/pc98-comparison.md`](pc98-comparison.md); reproduce with
`tools/pc98_diff.py`.

Do not reopen this from the symptom. What the investigation did establish, and
what is worth keeping:

- **`5dce533`'s divider is a no-op** and is retracted (entry 0 below). The
  `dds_dev_bat*` exes are deleted from the install.
- **`dds_dev_btl<n>.exe` is real** -- it gates the battle state machine at
  `0x0041720A` -- but `btl3` made no perceptible difference when played, so the
  battle's phase rate is not what decides how many turns a side gets. Kept
  because it is correct and tested, not because it helps.
- ~~**The battle is strictly turn-based.**~~ **Wrong, corrected 2026-09-08
  second pass.** It is an ATB: every combatant has a wait counter advanced once
  per frame of a state handler (`0x0043F510`). The evidence used for the old
  claim -- that state 32's handler calls nothing in `0x0042Axxx`-`0x0042Dxxx` --
  was scoped to the wrong address range; the gauge tick lives at `0x0040E250` /
  `0x0043F570`, outside it. It remains true that only one state handler runs per
  frame, so the gauges are frozen whenever state 32 is current; what is *not*
  established is whether state 32 is current while a message window is up.
- The architecture map and the pacing measurements below stand.

If it is ever worth revisiting as a *deliberate* rebalance rather than a bug,
agility is a **weaker** lever than it looks: the step is `2*(1+rand%speed)+5`
against a reload of 255, so mean time to act is `255/(speed+6)` and a 6x stat
difference buys only about 3x the turn rate. The cadence (which state, and the
mod-4 divisor at `ds:0x0047B7D4`) moves it much harder than the stat tables do.

### ✅ SHIPPED: the restored turn gauge is in the release build

**Decided 2026-09-08 by the person playing it** -- *"it's technically faithful
and actually makes battles, battles (the speed it ran at before was impossible
to fight at)"* -- and shipped the same day, together with putting the popup
dwell back to the stock 15. Those are one decision, for the reason in the trap
below. `dds.exe`, every dev build and the installed `play/en/ddswin` all carry
both; `dds_dev_x2.exe` (`giten exe dev-x2`) is the opt-out with the port's
doubled step, kept so the A/B stays reproducible. Exe accounting moved 1,015 ->
1,016 bytes in place and 11 -> 13 non-translation
([`exe-patches.md`](exe-patches.md)).

The reasoning is preserved because it was a real judgment call, not a formality. The change is
four bytes at `0x0043F52F` restoring the 1997 arithmetic; it is currently in
`dds_dev_atb.exe` only.

Both readings of "faithful" are defensible, which is exactly why this is not a
technical decision:

* **Ship it.** The thing being restored is the *original release's own* formula.
  A player on this patch would experience the pacing the 1997 game had, which is
  what a translation is usually trying to deliver.
* **Do not ship it.** What this project translates is the **Windows port**, and
  the port's authors doubled that step deliberately. Changing it makes the patch
  a rebalance as well as a translation, which is a different promise.

**The trap, and how it was resolved.** The tested build held the popup dwell at
the stock **15** ticks so the gauge was the only variable, while the release ran
**60** so English was readable. Shipping the gauge alone would have produced
*ATB-restored + dwell 60* -- a combination nobody had played, and a worse one
than either, because the dwell is also how long the command UI is refused
(`combat-pacing.md` §2) and 60 eats a quarter of what the gauge gives back. The
player chose the tested combination: gauge restored **and** dwell 15. So what
ships is what was measured, which is the only version of this that was ever
safe.

#### Findings from the closed combat thread, kept for reference

##### The battle divider does nothing — RETRACT `5dce533`

**`dds_dev_bat3.exe` and `dds_dev_bat4.exe` are behaviourally identical to
`dds_dev.exe`.** Diffed: they differ only in the redirect at the `call 0x0043B5E0`
site and the code behind it, so the one thing they change is gating that call.

And that call is already a no-op. `0x0043B5E0` opens with:

    or   eax, 0xFFFFFFFF
    cmp  word ptr [0x00469828], ax     ; background-script FILE
    je   ret
    cmp  word ptr [0x0046982C], ax     ; background-script RECORD
    je   ret

Those two words start at `FFFF FFFF`. Of the four places that write them, three
write `-1` — they are clears (`0x0043B132`, `0x0043B527`, and the tail of
`0x0043B590`). The only one that can store a real value is `0x0043B590`, reached
from opcode **`1ECB`**, and `1ECB` occurs **0 times in 20,690 records**.

So the function returns immediately, always, and dividing it divides nothing.

**Also retract the measurement.** The "party:enemy ratio 1:3.8 -> 1:0.8" credited
to that commit cannot have been caused by it; two traces of different play are
the likelier explanation. It should not be quoted again.

**What actually paces combat is still unknown.** Candidates, none checked:

- the main tick itself (`pace()`, 60 Hz) — but that governs the field too, and
  30/40 Hz was already tried and is unbearable out of combat;
- the script stopwatch `[0x0048164C]` / `[0x00481650]`, incremented once per tick
  by `0x0043BBC0` and read only around `0x0043BAE5`-`0x0043BB67` — a
  script-visible "wait n" timer, which is the most promising lead;
- a battle-specific frame counter nobody has looked for.

The first real question is what the battle loop *is*: whether it runs as script
through `exec_token` and blocks on that stopwatch, or has its own update.

##### What actually paces the script — first measurements

**The stopwatch lead is dead.** `0x0043BBC0`'s counter is reached from exactly
three opcodes -- `1E 0B` start, `1E 0C` stop, `1E 0E` read -- and their use counts
are **0, 0 and 2**. It is not the battle pacer.

**The real mechanism is the yield.** `0x004390F0` runs `do exec_token while
(r >= 0)`, so any negative return ends that tick's script run. `1E 07`, `1E 08`
and `1E 11` each end with `mov ax, 0xFFFD` (**-3**) — 1,976 + 1,965 + 1,698 uses.
`1E 10`, the page wait, is the most-used opcode in the game at **22,295** uses;
its handler `0x0043C0BC` reads two u8 operands plus a mode byte and calls
`0x0041A930`, which is where a text page's dwell actually lives.

**A trace can be timed even though it has no clock**, because `r` is logged for
every token: count the negative returns and you have counted ticks. Measured on
the 2026-09-07 session (`build/trace/en-negotiate.bin`), a multi-hour play:

| | |
|---|---|
| whole session | 159,926 tokens, 5,999 yields — **100 s of script** |
| `m/MS00DD`, the battle script | 42,917 tokens, 853 yields — **14.2 s** |
| the 14 separate battle stretches | 1.0 s, 1.1 s, 0.4 s, **4.1 s**, 1.8 s, 0.3 s, … |

**A whole battle spends about a second of script time.** That is the complaint,
in a number. (Of the 853, 233 are the clean `-3` yield, 489 are `-1` "page full,
loop exits" and 131 are `-2` re-dispatch; all three end the tick, so 853 is the
count of ticks in which the script ran and stopped. Ticks where the engine
blocks on input produce no token at all, so wall time is longer than this — this
measures the script's own budget, not the player's reading time.)

**Next, on the incoming trace:** count yields between consecutive battle actions
rather than per battle, and find which opcode ends each one. If most battle
ticks end on `1E 10`, the lever is `0x0041A930`'s dwell and it can be scaled in
battle without touching the field. If they end on `-1`, the pacing is the page
buffer filling up and the lever is elsewhere.

##### Combat: what the 2026-09-08 session does and does not show

**Established, and it closes the pacing thread:**

- Of `m/MS00DD`'s 491 yields, **413 end on opcode `00` with `r = -1`**, and
  opcode `00`'s handler is `0x004314E7` = `or ax, 0xFFFF ; ret` -- an
  unconditional terminator, not a wait. The battle script never waits.
- Battle messages are popups (item 0d), and the popup dwell `[0x004716F4]` is
  already 60 ticks here -- a full second per message.
- **There is no input timeout.** `0x00402740` skips the countdown entirely while
  `[0x004716F8]` is set, which is what an input-wait popup sets. The player has
  unlimited time to choose.

So nothing in the interpreter, the tick divider, `1E 10`'s dwell or the popup
timer explains "combat is too fast".

**Retracted.** An earlier version of this entry read the end of the Dantalion
fight -- seven enemy actions with no party turn -- as evidence of a broken turn
scheduler. It is not. Reading the same stretch with the HP bar included:

    Katsuragi Ayato  95 HP  <- takes 108 from Ziora, down
    Sonoda Tetsuya  109 HP  <- takes 143 from Zanma, down
    Kamikawa Kouki          <- takes 164 from Agilao, down
    Hayasaka Tatsuya  0 HP  <- already down before the stretch began

**Each enemy action removes an actor.** A party being one-shot naturally yields
consecutive enemy turns; that is the shape of losing, not of a scheduler fault.

The "1 party turn per 1.35 enemy" figure is also not diagnostic on its own --
enemies can outnumber the party, and the detector behind it counts some dialogue
lines (`Hayasaka:Let...`) as party actions.

**So there is currently no measured evidence of a combat bug in this patch**, and
the honest reading of that fight is that the party was underlevelled for it. What
would settle it: fight the *same* battle on `dds_dev_nopace.exe` (no pacing gate,
free-running) and compare the party:enemy action ratio. If the ratio moves, turn
order is tick-driven and the 60 Hz gate skews it. If it does not, the ratio is
the game's own and there is nothing here to fix.

##### The battle machine steps once per tick

The player's report is the evidence that settles this -- *"I was spamming clicks
on the character selector to get a turn in and couldn't, because the enemy was
too fast."* That is not a party being out-damaged. That is the battle advancing
while the player is trying to act.

**The mechanism.** `0x00417160` is a 41-state machine, one handler per tick,
dispatched through the table at `0x00417288`. Battle is **state 24**,
`0x0042B6A0`, and that handler is itself a **9-way sub-state machine** dispatched
through `0x0042C02C`. Every one of those sub-states opens with
`call 0x00416AD0`, and `0x00416AD0` is:

    mov ax, [0x0047BB72]      ; current sub-state
    inc ax
    push eax ; call 0x00416AA0 ; ret      ; set_substate(cur + 1)

So **the battle advances exactly one phase per tick** -- 60 phases a second at
the rate `pace()` pins. The command UI is a *different* top-level state (32,
`0x0041D530`), so the window in which the player can act is a particular phase of
a cycle spinning at 60 Hz.

**This is also why the divider in `5dce533` did nothing.** It gated
`0x0043B5E0`, which is dead. The battle clock is the state-24 handler.

**The lever.** `0x00416AD0` itself is generic -- 92 callers across menus, field
and battle -- so gating it would slow everything. But the state table's entry 24
is one call site, `0x0041720A`, and redirecting that through a counter makes the
battle machine step once every N ticks while the field, the menus and the battle
command UI are all untouched. That is exactly the "battle has its own divider"
idea, applied to the right function this time. Five bytes in place, same
technique as the existing hooks.

**Built 2026-09-08.** `giten.exe.tracer.build_dev_battle_div(n)` writes
`dds_dev_btl<n>.exe`, which redirects the state-24 call site at `0x0041720A`
through `battle_step()` in the cave: the battle machine advances one phase every
`n` ticks and every other state keeps running every tick. Installed at n = 2, 3
and 4. `build_dev_script_div` is kept only to carry its retraction, and
`dds_dev_bat3/bat4` are deleted from the install so nobody plays a no-op again.

Pinned by `test_the_battle_divider_gates_the_state_the_battle_actually_runs_in`
(state 24's stub really is a call to `0x0042B6A0`, the command UI really is a
different entry, and `-DBATTLE_DIV` really changes the compiled hook) and by
`test_the_retracted_script_divider_gates_a_function_that_does_nothing` (opcode
`1ECB` still occurs 0 times, so the retraction still holds). 205 tests pass.

**Still unverified, and only play can say:**

- whether the state-24 handler also drives battle *rendering*, in which case a
  divided build stutters the picture instead of slowing the turns;
- states 26 (`0x0042D7C0`) and 31 (`0x0042A790`) are also in the battle region
  and may need the same gate;
- which `n` is right.

##### btl3 changed nothing, and that inverts the hypothesis

Played 2026-09-08 on `dds_dev_btl3.exe`: **no perceptible difference.** Dividing
the battle state machine by three is not a small effect, so that is a real
negative result, not a null one.

**And the command UI proves the battle is strictly turn-based.** Every direct
call made by state 32's handler (`0x0041D530`-`0x0041D860`) lands in
`0x00402xxx`, `0x00404xxx`, `0x0040Cxxx`, `0x00414xxx`, `0x00416xxx`,
`0x0041Dxxx`, `0x00422xxx`, `0x00439310`, `0x00449CD0`, `0x00452xxx`,
`0x00454xxx` -- and **nothing in the battle region `0x0042Axxx`-`0x0042Dxxx`**.
So while the player is choosing, the battle engine is not running at all. The
enemy *cannot* act while the command menu is open.

Which kills the reading this whole thread was built on. The player is not being
out-raced while choosing. **The command menu is simply not being offered**, and
when it is offered they have unlimited time (`0x00402740` freezes the countdown
for input-wait popups).

**The player's other observation is the lead now:** PC-98 footage of the same
game shows the party taking several attacks where this build gives one. If the
number of actions a side gets is derived from a counter that advances with the
loop, then pinning the loop at 60 Hz -- where the 1999 build free-ran as fast as
the machine could draw -- would *starve* the party rather than rush it.

**That inverts the fix.** Every attempt so far has tried to slow combat down.
The next test is to speed it up: `dds_dev_nopace.exe` removes the pacing gate
entirely and lets the loop free-run as the original did. If the party suddenly
gets its turns, the 60 Hz gate is the cause and `pace()` is the thing to change,
not any divider. Rebuilt and installed 2026-09-08.

##### SOLVED: count the announcement span, not the rendered prose

`tools/battle_ratio.py`.  `m/MS00DE.BIN` is the attack-announcement file, and
several of its records carry **both directions of the same attack as different
alternates within the record** -- `r29[1]` "slashed at the enemy!" against
`r29[2]` "came slashing at you!", and the same pairing on r02/r05/r06/r0C/r2A/
r2B/r23/r26/r27.  The direction is a span index the engine picks before a glyph
is drawn, and the trace records which span ran.  No prose is parsed, and editing
the English cannot move the number.

Ambiguous alternates (`r04[5]` "'s {04:02} opened fire", `r03[5]` "'s attack" --
both sides use them) are reported as *unattributed* rather than folded into
either side.  Open: whether r04's gun alternates split by side through some
other tell.

**The trace is truncated on every launch.**  Copy it out before relaunching, and
archive anything worth keeping in `traces/`.  The 2026-09-08 20:02 ATB session
was lost this way while being analysed.

##### Why the glyph log was not a reliable instrument

Three attempts at the same question on the same data gave 1 : 1.38, 1 : 1.75 and
1 : 6.56. The reasons, all found the hard way:

- a party weapon attack reads `Katsuragi Ayato with Sabre,thrust at the enemy`,
  not `X's Y`, so an `X's Y` pattern misses every one of them;
- consecutive messages are drawn back to back and a run-splitter that breaks on
  the draw-variant merges them, so only the first in each run is ever matched;
- status results (`attack power was lowered`) are consequences of someone
  *else's* turn and inflate the party side if counted.

And the deeper problem: two sessions are different content -- different areas,
different enemies, different amounts of negotiation -- so per-battle rates are
confounded no matter how good the pattern is.

**Use it for existence, not for rates.** "The party acted zero times in a fight
it outnumbered 3 to 1" is a fact the log states plainly and no pattern can spoil.
"The ratio improved 2x" is not something this log can support.

To measure pacing properly the tracer would have to log a tick counter --
`pace()` already has one, and `flags` has no spare bits left, so it wants a
record-format bump rather than another regex.

##### The combat architecture, mapped 2026-09-08

Read out of the exe, with the call-site field in the trace confirming which
paths actually carry battle tokens.

```
0x00450AC0  main loop
  0x004510B8  pacing gate (pace(), 60 Hz)
    0x004019D0  per-tick update
      0x00417160  UI/state  ->  0x0041D530  battle command UI
                                  ->  0x00414E70 -> command table 0x004687FC
                                      {u32 id, u32 handler, u16} x 7,
                                      ids 5,8,3,2,4,0,1
      0x00401980  ->  0x00402740  popup countdown  [0x004716F4]
                  ->  0x0043B5E0  background script   -- DEAD (item 0)
                  ->  0x0043BBC0  stopwatch           -- DEAD (1E 0B/0C/0E: 0/0/2 uses)

0x0042Bxxx-0x0042Cxxx  battle engine
  ->  0x00402800  open a popup and run a script record inside it
        ->  0x00439090  run-until-blocked  ->  exec_token at 0x004390C4
```

**The battle script is driven by the popup system, not by the per-tick chain.**
The trace's call-site field says so: `m/MS00DD`'s tokens arrive from `0x004390C4`
(14,769) and `0x0043913C` (7,678), and **not** from `0x00439103`, the site inside
`0x004390F0` that the dead background script would have used. `0x00402800` is
"open a popup and run this record in it", and its only callers are five sites in
`0x0042BDCF`-`0x0042C23C` -- the battle engine.

**Correction to `CALL_SITE_ROLE` in `giten/trace/core.py`:** it labels
`0x004390C4` and `0x0043913C` "direct". `0x004390C4` is not direct -- it sits in
a `do { fetch; exec_token } while (r >= 0)` loop at `0x00439090`, the same shape
as `0x004390F0`. The label should say so.

**Where this leaves the pacing question.** Each battle message is a popup that
runs one script fragment; the popup's dwell is `[0x004716F4]` ticks, set at
`0x00402630`, whose default this repo already raised 15 -> 60 (`POPUP_TICKS`).
So message dwell is already a full second. That is consistent with the trace:
**the problem is not that messages fly past, it is that the party is not
offered turns** (item 0c: 1 party turn per 1.35 enemy, longest enemy run 7).

**Next:** the turn order itself, in `0x0042Bxxx`-`0x0042Cxxx`. The question to
answer first is whether the next actor is chosen from an accumulator advanced
per tick -- in which case the 60 Hz gate skews it and the fix is there -- or from
a plain agility sort, in which case the ratio is the game's own and the fix is a
different one. Nothing above answers that; it needs the battle unit structure.

---


### 0. Replace the v0.05 English -- USER PRIORITY, set 2026-09-08

**16,789 rows / 582,706 characters of the English we would build are byte-for-byte
Sneikkimies' v0.05 text, unreviewed.** That is 38% of the shipped rows and 37% of
the shipped characters.

`giten check` already flags every one of them and has all along -- the guard at
`check_v2.py:275` errors when `en == ref_en` and `status != "reviewed"`. The
current count:

| | rows | characters |
|---|---|---|
| `en` set but `status` empty | **0** | -- |
| `en == ref_en`, not reviewed, `ref_src = v005` | **16,789** | 582,706 |
| `en == ref_en`, not reviewed, `ref_src = ours` | 10,652 | -- |
| **total `status` errors** | **27,441** | |
| rows marked `reviewed` in the whole corpus | **292** | |

So there is already a progress metric that cannot be gamed: **drive the `status`
error count to zero**, by either rewriting the line (so `en != ref_en`) or reading
the Japanese and marking it `reviewed`. Nothing else needs building first.

**Worst files, by rows of unreviewed v0.05 text:**

    m/MS003B 855   m/MS0030 794   m/MS005C 514   m/MS005D 512   m/MS000D 511
    m/MS005B 447   m/MS001E 428   m/MS0006 359   m/MS0060 334   m/MS0029 325

**Scope, set by the user 2026-09-08.** Retranslate the **16,789 v0.05 rows** and
the rows with no English at all. **Our own 10,652 unreviewed drafts stay** -- they
were written against the Japanese by us, where the v0.05 lines took liberties.
They remain `status` errors and can be reviewed later; they are not a rewrite job.

**This work does NOT wait for the opcode model.** Measured:

| | |
|---|---|
| rows to retranslate | 16,789 |
| ...in a record the builder refuses to edit (`@noedit`) | **20** |
| ...in an `@untiled` record | **0** |

99.88% of the scope already sits in records that tile and are editable, which is
the decision corpus consistency exists to make and it is already made. Neither
the exhaustive handler walk nor any further model work changes it. The only
coupling is that a model change which moved token boundaries would **re-key** span
indices -- a migration the extractor already handles by fingerprinting on `jp` and
re-anchoring on content, with anything unresolvable written to `docs/recovery/`.
Rows would need re-anchoring, never retranslating. Drop the 20 `@noedit` rows
from scope.

**PILOT DONE 2026-09-08: 469 rows across 4 early-game files, all applied.**
`m/MS0002` (82), `m/MS0015` (119), `m/MS0016` (86), `m/MS0017` (182), by Sonnet
agents through `tools/tl_export.py` -> `tools/tl_apply.py`.

    status errors   27,441 -> 27,138      width-choice  109 -> 107 (2 better than baseline)
    japanese 129, tokens 5, missing 915, width 10 -- all UNCHANGED

Quality beats v0.05, which the agents caught mistranslating (`Water Wall` as
"Ice Wall"), inventing sentences absent from the Japanese, and flattening nuance.
Backup of the tables before the first write:
`build/tables_draft.bak-20260908-121325` (the tree is gitignored -- that is the
only undo).

**Four defects found, all in the tooling, none in the translations:**

1. an exact-token-multiset rule, which produced `No one{08:24}{02:08} here...`;
2. keeping a token whose pool entry is untranslated, which ships Japanese inside
   English (`by 人間 strength`) -- 102 of `m/MS0017`'s 182 rows;
3. the refusal list truncated at 40, silently capping a 102-row re-brief;
4. no output-token discipline: `m/MS0016` died at the 64,000-token ceiling with
   nothing written, on 86 rows whose text is ~3,000 tokens. Narration and repeated
   whole-file rewrites, not the translations.

**The number that should change the plan: ~35% of rows converge.** 166 of the 469
still read `en == ref_en` *after* independent retranslation, because there is only
one reasonable English -- 146 of them have <= 8 Japanese characters (`男性：` ->
`Man:`). Corpus-wide **57% of the 17,790 in-scope rows are under 12 Japanese
characters**. Those cannot be improved by an LLM at ~2,500 tokens each; they need
a reviewer to confirm and mark `reviewed`.

**Cost, measured, not estimated:** ~2,400-3,000 tokens per row, flat across batch
sizes from 82 to 182 rows -- so per-row reading and reasoning dominates, not
fixed overhead. Extrapolating naively gives **40M+ tokens** for 16,769 rows. A
convergence pass over the short rows first would cut that by more than half.

**A/B RESULT 2026-09-08: anchoring is 2%. Showing the reference is nearly harmless.**
`m/MS0016`'s 86 rows were translated twice -- once with the v0.05 line visible,
once **blind** (`tools/tl_export.py --blind`, which hides the reference *and* the
English of surrounding context rows; the agent was also told not to read the
tables, other answer files, or git history, and confirmed it did not).

| | rows matching v0.05 |
|---|---|
| sighted pass | 15 of 86 |
| blind pass | 13 of 86 |
| **anchoring effect** | **2 rows -- 2% of the file** |

The two are equivalent phrasings, not copying: `YOU DEFEATED THE BOSS` against
`YOU HAVE WON AGAINST THE BOSS`.

So the earlier worry was wrong. **The rows that come back identical really are
forced translations, not the reference echoed.** Two consequences:

* the 469 rows already applied do **not** need redoing;
* the convergence evidence in `tl_converge.py` is more trustworthy than its own
  docstring claims -- our earlier drafts were written with v0.05 visible, and
  that turns out to bias the wording by about 2%.

Also measured: the sighted and blind passes agree with **each other** on only 43
of 86 rows. Legitimate phrasing variation is wide, which is why the ~15% that
match v0.05 stand out as genuinely forced rather than coincidental.

`--blind` stays the default for new work: it costs nothing and keeps the
provenance argument clean, which matters independently of the wording.

**Why this is not merely bookkeeping.** Shipping another translator's work
verbatim is a real attribution problem independent of quality, and the v0.05
lines were never checked against the Japanese by anyone here -- they were carried
in as *candidates*. The standing policy ("v0.05 lines are drafts only, never a
build input") is currently violated in effect for 16,789 rows, because they were
promoted into `en`.

**Relationship to item 1.** Item 1 is ~200 rows with *no* English at all. This is
16,789 rows with the *wrong provenance*. Item 1 is much smaller and finishes
coverage; this one is the larger body of work and the one the user has named the
priority.

### 1. Finish the untranslated ordinary rows — 216 of 854 done

**The "854 untranslated rows" figure overstated the job by about half**: 441 of
them contain no Japanese at all (pure `{08:xx}` macros, digits, ASCII rules like
`~ON` / ` ---------------- ----`), so there is nothing to translate in them and
there never will be.

| | rows | state |
|---|---|---|
| no Japanese in them at all | 441 | not work; ignore |
| speaker tags | 191 | **174 done**, 17 left |
| debug menu (`m/MS00D1`) | 177 | open, developer-facing |
| real prose | 45 | **42 done**, 3 left |

Done 2026-09-08. The 174 tags were filled from the rendering the corpus had
already settled on — `ハリティー：` → `Hariti:` was in 14 other places,
`バール兵：` → `Baal Soldier:` in 141 — so they were consistency, not judgement.
The 42 prose spans were written against their neighbours, because each is a
*fragment*: the engine prints span, then a runtime name, then the next span.

Still open:

- **17 speaker tags** with no rendering anywhere. 13 are `m/MS00D1` debug field
  labels (`系統`, `計算式`, `消費`, `範囲`, `距離`, `相性`, `治癒`, `追加効果`,
  `体数`, `使用状況`, `修得`, `特殊コード`, `ﾘｽﾄｱｯﾌﾟ対象`); the others are
  `ハツセオノミコト：`, `ウサギ：`, and `ﾒ泪：` (mojibake, in `m/MS0031`).
- **2 `@untiled` rows in `m/MS0031`** — no dependable span boundary, and the
  overlay refuses them anyway. Blocked on the tiler, not on translation.
- **1 row in `m/MS0027` 0:01[71]** — its neighbours already print the name twice
  (`早坂` then `英美`, and the following English repeats `Hayasaka`), so any
  English here reads wrong until that passage is untangled.
- **The 177 debug-menu rows in `m/MS00D1`**, if they are wanted at all.

### 2. Why did `ムールムール：` draw in Japanese?

**Open, and my first two explanations for it were both wrong.** It is not our
English keeping the Japanese name — all 89 rows carrying the name already read
`Murmur:` — and it is not `m/MS00DD`; the rows live in `m/MS001F` (40) and
`m/MS0058` (35), and the trace only *labelled* them `0x00DD` because `FILEID`
is stale on that path.

The current overlay serves them correctly: walked through `overlay.Model`,
`m/MS001F` 0x0BD7 yields `Murmur:` and `m/MS0058` 0x0DB3 yields `Murmur:`.
Yet the 2026-09-07 session drew the Japanese name with an English body, on an
overlay that provably contained both. So `lookup()` failed for that stretch —
most likely the same identity failure as item 1, in its general form.

Needs one fresh trace of that scene. **Note for next time: that session's
`overlay.dat` was overwritten when the tree was regenerated, so the run can no
longer be reproduced byte-for-byte.** Copy `overlay.dat` next to the trace
before rebuilding.

### ✅ 3. `m/MS610D`'s mojibake English — FIXED 2026-09-08

They were never translations. `m/MS610D` is a negotiation script with **binary
tables mixed into it** — real menu options (`Save Heart`, `Give Food`, `Grin`,
`Wipe Away`) interleaved with data the tokenizer walks into and calls a text
span. The fake spans decode to the clothing-radical block that binary lands on
when read as Shift-JIS (褫 襁 襄 褻 褶 袿 襌), and a `02 00` inside one reads as a
pool call — so promotion substituted **"Devil Buster" into the middle of a data
table**.

Two refusals now keep English out, and the obvious version of each was tried
first and was wrong:

- **A span following opcode `11`, in a container holding a record we cannot
  tile.** Both halves are needed. 49 of the 50 are data, in `m/MS610D`,
  `m/MS6200` and `m/MS6500`; the fiftieth is `m/MS6000` 12:CE[1] — `失敗！` →
  `Failure!` — and is real. "No kana" does not separate them (that one has
  kanji and no kana) and neither does the clothing-radical block (it holds 裂
  and 裏, used in 580 real lines). **The container's own tiling does** — the
  same correlation that explains every off-boundary branch target.
- **0xFF counted, not merely present.** The old rule compared presence, so a
  span with two in the Japanese and one in the English passed. Exactly one did:
  `m/MS610D` 0:FE[4], the only one of the 25 that ever reached the overlay.

Refusals 29 → 44. **No served row carries Japanese in its English any more**,
and `m/MS6000`'s `Failure!` is still served. Pinned by
`tests/test_data_spans.py`. 208 tests pass.

### 3. ~~Finish the half-translated row in `m/MS000C`~~ — misdiagnosed

**The row is fully translated.** `m/MS000C` 0:04[174] already reads
`It almost seemed as if it had all been a dream......`. The Japanese appears
because a branch lands at `0x3E67`, 41 bytes into the span, and the overlay
must answer a branch target with the original bytes — deliberately, since
`b4ec69b`. Only the first 41 bytes are served in place; the rest is reachable
only by entering the span at its start.

So this is the known "branch into a span" gap in `docs/limits.md` (71 remaining
cases), and the honest fix is the one recorded there: split the span at the
target so each fragment is separately translatable. Not a translation task.

---

### 4a. `m/MS0031` -- CLOSED 2026-09-08. There was no bug. Do not change the tokenizer.

**Ten spans** in `m/MS0031` (not 22 -- the earlier count was wrong) begin on the
trailing byte of a two-byte character, so they extract as `｢きなり`, `ﾚしい事情`,
`ｳ事だと`. Shifting one byte back reads perfectly in all ten. That argument
lost. `10 01 01 82` is opcode `10`, rel16 `01 01`, and `82` as the condition's
expression selector; `0x82` is above the table's `0x5D` bound, so the reader
takes the nullary "invalid" kind and consumes one byte -- and that byte is the
lead byte of `い`. **Our tokenizer was right the whole time.**

Four independent lines of evidence, gathered after `tools/make_fallthrough.py`
redirected the record's opening `1F 04` from 0x019F to 0x0014 so the region
actually executes:

| evidence | result |
|---|---|
| the engine's own pc | 44 token starts logged in r01, **44 of 44 on our boundaries**; pc goes 0x3F -> 0x43 and **never** lands on 0x42 |
| the glyph blitter (not the interpreter) | drew `ああ、やっと気がついた。｢きなり、倒れるんだもん。` -- the engine itself renders the broken `｢` |
| the ten rel16 targets | all exactly `token + 0x104`, a **constant**, while the fourth byte varies (`82`, `8F`, `96`) -- so that byte is not part of the target |
| the handler walk | `0x00430055` reports `(0 u8, 1 u16, 0 u32, 1 expr)` on every path: `[rel16][condition expr]`, exactly as `_conditional_branch` says |

**The broken character is the original 1997 game's own bug**, visible on screen
in Japanese: the script author omitted the condition operand, so the engine eats
the text's lead byte as the selector. Our English replaces the whole span, so
shipping these ten rows *fixes* a bug rather than causing one -- the selector at
token+3 lives inside the token and English never reaches it.

Pinned by `tests/test_opcode_10.py` (4 tests), with both traces kept in
`traces/2026-09-08-warp31-*.bin`.

**What this cost, and the lesson.** The change would have re-keyed 217 spans
across 219 rows, 67 of them hand-written, to correct something that was never
wrong. That is the fifth rule this month that looked decisive and was wrong on
the corpus -- after "pure hiragana is grammar", "no kana means data", "the
clothing-radical block means data", and "an operand ending on a lead byte
swallowed a character". **Text that reads better one byte over is not evidence.**

### 4. Opcode model — re-stated 2026-09-08 after the data-span work

**"99.65% of records tile" was the wrong headline.** A record can tile and tile
*wrong*: the tokenizer invents spans over data, and 25 of them had English
promoted into them. So the number that matters is not how many records tile but
how many spans we can vouch for.

| | |
|---|---|
| records that tile | 20,617 of 20,690 — 99.65% |
| spans in a container holding an untiled record | **615 of 44,604 — 1.38%** |
| ...of those, served with English | **311** (MS0031 193, MS610D 92, MS6200 22, MS6500 4) |
| branch targets on a token boundary | 20,150 of 20,269 |
| spans shaped like a pointer table | 37 — **0 served** (fixed, item 3) |

**The correlation is now confirmed three independent ways.** Untiled records,
off-boundary branch targets, and data-shaped spans each occur in the same seven
containers and **nowhere else**: `m/MS0031` c0, `m/MS610D` c0 and c3,
`m/MS6200` c0, `m/MS6F00` c31, `m/MS6F1F` c0, `m/MS6500` c0. Outside them the
model shows no evidence of being wrong at all — every branch lands on a
boundary and no span is shaped like data.

**The `m/MS0031` residue was ours to explain, not ours to fix -- CORRECTED
2026-09-08.** This section used to say its 193 served spans "start a byte or two
late" and called fixing them the highest-value work left. That was wrong twice
over. The observable residue is **18 spans, not 193**, and every one of them is
the game's own data bug:

| class | n | what it is |
|---|---|---|
| opcode `10` | 10 | `10 01 01 82`: rel16 `01 01`, then `82` as the condition's expression selector. `0x82 > 0x5D` so the reader takes the nullary kind and eats it -- and it is `い`'s lead byte. See 4a. |
| nested expression | 4 | same defect one level down. Selector `1F` is `u8 + expr`, so `10 01 01 1F BA 93` ends on a nested selector `93` -- `突`'s lead byte. |
| leading `0xFF` | 4 | not a broken start at all; `0xFF` is a real control byte and the span legitimately opens with it. |

**One member of each of the first two classes is confirmed directly**, by the
engine's own pc *and* by the glyph blitter, which is not the interpreter:

* `0:01[2]` -- pc `0x3F -> 0x43`, blitter drew `｢きなり、倒れるんだもん。`
* `0:01[0]` -- pc read `0x00D2` at 0x14, then `泥` at 0x15, `：` at 0x17; blitter drew `ﾒ泥：！`

Even the speaker label is garbled in the original Japanese. The other 12 share
the identical byte shape. **Our boundaries match the engine everywhere it was
observed: 44 of 44 token starts.**

### `m/MS610D`: no loader found -- 2026-09-08, and 67 untiled records may go with it

Item 4 treated `m/MS610D` as a file whose loader we had not found yet. After an
adversarial pass the honest statement is **"no path found, one branch still
open"** -- not "proven unreachable". The first version of this section said
proven; that was wrong and is corrected below.

The negotiation merge is the only thing that loads an `m/MS61xx` file, and it
forms the name in one instruction -- `0x0040EC31 add $0x6100,%edx`, from
`table[id*3 + 2]`. The table is not inferred: `0x0040EB70` loads it itself and
caches the pointer.

    0x0040EB79  jne  0x40ebac          ; already cached?
    0x0040EB7F  push $0x7              ; file id 7
    0x0040EB7D  push $0xc              ; kind 12 -> et\et%.4x.bin
    0x0040EB81  call 0x401dd0          ; -> et/ET0007.BIN
    0x0040EB99  movl $0x47b058,0x47b4f8

`et/ET0007.BIN`'s third column holds `{00, 06, 07, 08, 09, 0B, 0C}` across all
25 rows. **It never holds `0D`.** Four other things had to be ruled out and were:

* **no `0x610D` immediate exists anywhere in the exe's code** (191 raw hits, 0 in
  the code range);
* **only one instruction forms a `61xx` id**, and it is the one above;
* **only one call site** of the merge (`0x0040E9CA`);
* **no script can name a file by a u16 id** -- every file-referencing opcode
  either hardcodes a pool (`m/MS7F0x`) or takes a **u8** that resolves to
  `m/MS00xx`. `0C`/`0D` cannot reach `0x610D`.

Two other `et/` files share the table's shape; both are excluded because their
columns name files that do not exist (`ET1011` 22 of them, `ET10FF` 9).

**What it bought.** 16 of the 46 `m/MS6xxx` files are unreachable, and they hold
**every untiled record in the family**:

| | files | untiled | spans |
|---|---|---|---|
| reachable | 281 | **6** | 42,905 |
| unreachable | 28 | **67** | 1,028 |

**Every reachable `m/MS6xxx` file tiles perfectly.** The corpus-wide gap is no
longer "73 untiled records in six containers, 40 of them in a file we cannot
reach" -- it is **six records in one container of `m/MS0031`**, and everything
else was never code the game runs.

Pinned by `tests/test_reachability.py`.

**What the adversarial pass found -- the claim is weaker than first written.**

* **`m/MS6800` IS loaded**, by an immediate at `0x0040E948` (kind 9). The first
  reachability classifier called it unreachable. It has no untiled records so
  the counts above are unaffected, but the classifier was wrong.
* **`0x0043AD20` is a generic `m/MS%04X` loader taking a 16-bit id**, reached
  through a cache at `0x0043B7A0` (`0x481688` heads a list of loaded buffers,
  each stamped with its id at offset 0). Its caller `0x0043458E` supplies that id
  in `%edi` from a path **not traced to immediates**. Until that is closed,
  "nothing can name `0x610D`" is not established.
* The merge's row index is a `u16` struct field (`0x47b16f`, stride 254), not a
  bounded counter, so an out-of-bounds index is not excluded either.

**Why this does not block progress.** The reachability claim is only load-bearing
if the six `m/MS0031` records fail for a different reason than `m/MS610D`'s
forty. They do not:

| failure class | MS0031 | MS610D | others |
|---|---|---|---|
| expression selector past end | 1 | **25** | -- |
| expression node 0x00 payload past end | 1 | **13** | MS6200 3 |
| switch entry | 1 | 2 | 4 |
| unterminated pairs_ff | 1 | -- | 2 |
| rel16 operand past end | 2 | -- | -- |

The two classes that account for **38 of MS610D's 40** each have a live example
in `m/MS0031` -- the file the warp already reaches and traced successfully on
2026-09-08. Correcting the model there should tile both, which **dissolves the
reachability question rather than requiring it to be settled**. So: do the six
first, then re-measure. If all 73 tile, reachability becomes trivia.

**What is left, in full:**

1. **`m/MS0031` c0: 6 untiled records** (`00`, `02`, `03`, `0B`, `0D`, `17`) --
   the entire remaining opcode gap, in a file the warp already reaches. This is
   now the whole of item 4.
2. ~~`m/MS610D`, `m/MS6200`, `m/MS6500`~~ -- unreachable; nothing to model.
3. ~~`m/MS6F00`, `m/MS6F1F`~~ -- not script, already deny-listed.

**Follow-on worth doing:** 1,028 spans of English are built into the overlay for
files that can never load. Harmless, but they consume overlay budget; dropping
them is a small win once item 1 is done.

---

### 4b. The six `m/MS0031` records -- ALL SIX RESOLVED 2026-09-08. None is a model defect.

The engine was asked and answered. `tools/make_warp_seq.py` wrote `0D 31 17`
then `0C 31 02` into `m/MS0017` r01, with `m/MS0031` byte-identical to the
original and **predictions registered in the tool's docstring before the run**.
The result was **A**, on both the program counter and the glyph blitter.

**Two records fail inside dead data after a terminator.** Opcode `00` is
`or ax,0xFFFF; ret`, which ends the run loop. r00 has ten terminators, the last
at 0x5F with 177 bytes after it; r0D has two, the last at 0x31 with 4. r0D's
tail carries the canonical switch shape -- `31 14 ff` is a switch *entry*,
matching `0F 00 00 31 12 01 00 ... 31 11 ff` in four records that tile.

**Three end with a branch that eats the terminator and spills into the next
record.** This is the one that looked like our bug:

* **r17 has no terminator.** 74 tokens executed past its end. The first is at
  **r18+0x01 with `ch=0x00D2`** -- the bare trailing byte of `1F D2` -- because
  opcode `10`'s expression (selector `00` = `[u8]`) consumes r17's final `00`
  plus one byte of r18. Exactly the registered prediction.
* **r02 crashes the game.** Its closing `18` reads its rel16 as `00 1F` -- its
  own last byte plus r03's first -- and branches to `0x0C9D + 0x1F00 = 0x2B9D`,
  **past the 0x2457 end of the image**. The dialogue played and the process died,
  which is what the play session showed.

**The cleanest evidence in the project.** The glyph log has the *same*
`[1FD2]泪：[1FD3]` marker drawn twice in one session:

| entry | drawn |
|---|---|
| r17 at offset 0 | `泪：‥‥なによ！` -- clean |
| r18 at offset 1, by the spill | `ﾒ泪：うふっ、それで` -- garbled |

Same bytes, two renderings, decided only by the entry point. That also
retroactively explains the identical `ﾒ泪：` in r01 and closes the last doubt
about item 4a.

**So the opcode model has no known defect anywhere in the corpus.** The 73
untiled records are dead tails, broken data, or files with no loader found --
not code we cannot parse. Pinned by `tests/test_ms0031_tails.py`.

**What this does NOT establish.** That these records are unreachable. Only one
`0C`/`0D` reference to `m/MS0031` exists in the entire corpus (r1B), and the file
appears in **none of the 668,311 events across nine play traces** -- but those
sessions are all early-game and this is plainly a late-game scene, and the
intra-container reachability walk does not follow `0E`/`0F` switch targets, so it
under-approximates. Evidence, not proof.

**r0B: the corpus's single unterminated `pairs_ff`.** Its `1F 04` at 0x236 is
real -- the rel16 is `0x00C9`, targeting record offset `0x0303`, which is the
record's own final `00` terminator. A jump to the end of the record is not
something a misaligned walk produces by chance. What is broken is the condition
list: the record holds **only two `0xFF` bytes**, at 0x113/0x114, and both are
legitimately consumed by an earlier `1F 01`, so nothing after 0x23A can end the
list and the engine would read pairs on into the following records.

The loop was read, not assumed:

    call 0x4393e0        ; *a = first & 0x7F, *b = second; returns -1 if first & 0x80
    cmp  bx,0xffff       ; bit 7 set?
    jne  body            ; no -> evaluate the pair and loop
    cmp  ax,0x7f         ; set, and (first & 0x7F) == 0x7F -> first byte is exactly 0xFF
    je   terminate

-- terminator is a first byte of exactly `0xFF`, costing two bytes, which is
what `_read_pairs_ff` already does. Corpus-wide, **916 of 919 `1F03`/`1F04`
sites terminate inside their own record**; the only exceptions are r0B and two
byte-identical copies of one record in `m/MS6F00`/`m/MS6F1F`, files already
established as not script. The model is right 916 times; this record is broken.

### The opcode model is now clean

> **Full write-up: [`docs/opcode-model.md`](opcode-model.md)** -- what the model
> is, the four independent verification methods, the findings that cost the most
> to get right, and a "what is NOT established" section that must be quoted
> alongside any confidence number.

Every one of the 73 untiled records in the corpus is accounted for, and **not one
is a defect in the tokenizer**:

| cause | records |
|---|---|
| dead data after a terminator | `m/MS0031` r00, r0D |
| operand spills past the record (r02 crashes the real game) | `m/MS0031` r02, r03, r17 |
| the one unterminated `pairs_ff` | `m/MS0031` r0B |
| files with no loader found | 67, in `m/MS610D`, `MS6200`, `MS6500`, `MS6F00`, `MS6F1F` |

The remaining gap to "100%" is not model accuracy. It is that six records of
broken data cannot be tiled *because they are broken*, and 67 more sit in files
nothing has been found to load.

---

## C1. Combat pacing -- REOPENED 2026-09-08, and the popup hypothesis is CORRECT

**The battle command UI is hard-gated by an "a message window is open" flag.**
`0x0041D530` (state 32, the command UI) opens with

    0x0041D530  push $0x2
    0x0041D532  call 0x404380      ; return flag_word(0x004683F0) & 2
    0x0041D53A  test %ax,%ax
    0x0041D53D  je   0x41d548      ; clear -> run the UI
    0x0041D53F  call 0x416c20      ; set   -> leave, this tick does nothing
    0x0041D547  ret

Bit 1 of `0x004683F0` has exactly **one setter and one clearer** in the whole
image: `0x0041985E` sets it and `0x00419D4B` clears it, both inside the
message-window subsystem (`0x00419xxx`, the neighbourhood the `1E 10` page-wait
handler reaches through `0x0043C0C0` -> `0x0041A930`).  So while a battle message
is on screen the player's command UI **does not run at all** -- not as a side
effect, by design.

**How long each message holds the gate.**  `0x00402740` decrements `0x004716F4`
once per tick and fires the close path at zero (`0x004716F8` pauses it).  The one
setter, `0x00402630`, is

    mov 0x4(%esp),%eax ; cmp $1,%ax ; jge use_it ; mov $0xf,%eax   <- default 15

so a message with no explicit duration holds the UI shut for **15 ticks** at
stock.  **This repo already ships 60** (`giten/exe/timing.py POPUP_TICKS`), so
every battle message holds the command UI shut *four times longer than the
original did*.  We chose that for readable English; it is a real cost and it is
the one pacing lever this project has actually pulled.

**Why the battle-state divider did nothing.**  `dds_dev_btl3/4` really did patch
the call site -- verified: `0x0041720A` points at the divider, not at
`0x0042B6A0` -- so that experiment was valid.  It did nothing because **state 24
does not tick the turn gauges at all**; it resolves an action already chosen.
The gauges are ticked from states 11, 16 and 34 (below).

**RETRACTED: "turn order is a uniform random draw with replacement".**  That
claim, made earlier the same day, was wrong.  `0x0042C740` is the **multi-hit
target-list builder**, and `0x00480AD0` is the **target list**, not a turn queue:
`0x0042BA73` zeroes its length immediately before the "scheduler" runs,
`0x0042BAC7` dequeues into `ds:0x00491996` (the *target*, never the actor), and
`0x0042B5DB` deletes a unit from it when it dies.  Sampling with replacement is
correct there -- a random multi-hit attack may hit the same target twice.  **Do
not patch it.**

**ANSWERED, second pass: turn order is an ATB wait counter advanced per frame.**
Which is exactly the first branch this file predicted ("an accumulator advanced
per tick ... or a plain agility sort").  Each combatant has a u16 counter --
party at `unit+0x17F`, enemy at `enemy+0x199` -- reloaded to 255 on acting and
decremented once per tick by `0x0043F510` as `2*(1 + rand()%speed) + 5`
(speed = `unit+0x5E` / `enemy+0x78`).  Party gauges tick via `0x0043F570`, enemy
via `0x0040E250`, both gated by `ds:0x00491544`.

**The asymmetry is a cadence, not a draw.**  Three state handlers tick the
gauges: state 11 (`0x00407390`) and state 34 (`0x00407AA0`) tick the enemy gauge
**every frame**, state 16 (`0x00412D20`) only **every fourth** frame (the mod-4
counter at `ds:0x0047B7D4`, single writer `0x00413284`).  So *which state a
battle runs in* decides whether enemies fill at 1x or 4x the party rate.  That is
the highest-value open question and one instrumented play-test answers it.

**Full write-up with every address: [`docs/combat-pacing.md`](combat-pacing.md).**

**Also found while looking:** the damage line the player actually sees is
`m/MS00DD` **rec 0x4C** (4,200 tokens in the evening trace).  Record 0x65, which
this session "fixed", **never executes** -- 0 events.  0x4C still reads
" HP of damage" and needs the same correction.

## Parked 2026-09-08 -- picked up after the combat-pacing work

### P1. District names are in `et/ET000D.BIN`, which nothing extracts

`百人町`, `大久保`, `北新宿`, `高田馬場`, `上落合`, `新宿` draw in Japanese in the
location strip.  They are in **no table** -- found by decoding every game file
and searching the plaintext, which is why a raw byte search missed them (the
container is XOR-chained).  Not `mapnames.tsv` (106 of 109 done; the 3 gaps are
whitespace and an already-Latin name) and not `maplabels.tsv` (a different table,
96 entries with 69 *empty* slots).  Needs an extractor of the same shape as
`giten etdb`.

### P2. The Dantalion-corridor directions regressed and I cannot explain it

`m/MS005C` 0:10[14] and 0:10[23] -- "head right, the door will be in front of
us" -- drew in **Japanese** in the 2026-09-08 evening session; the user reports
they used to be English.  Everything checks out on paper: both rows carry
English, both are planned into the overlay, and the file has full coverage (750
spans for 750 English rows).

**Two process failures made this hard to diagnose, both mine.**  The previous
`overlay.dat` was overwritten with no backup, so old and new cannot be diffed.
And a first diagnosis of "not in the overlay" was **wrong**: `Span.idx` is not
stored in the binary format and reads back as `-1`, so comparing against it says
"absent" for every span.  Compare against `overlay.plan()`, which carries `idx`,
or match on `(rec_id, rec_off)`.

`play/en - Copy/ddswin/overlay.dat` is an older (v4) overlay.  If that copy dates
from when the corridor read English, swapping it in and walking that corridor
settles the question in one run.

---

## Deferred -- only after 100% opcode accuracy and 100% translation

### D1. The engine eats a character at 14 sites. We could give it back.

`m/MS0031` has 14 spans where the script author left a conditional's operand
short, so the expression reader takes the following text's **lead byte** as a
nullary selector and eats it. The engine renders `｢きなり` for `いきなり`, `ﾚしい事情`
for `詳しい事情`, `ﾒ泥：` for a speaker name. Confirmed on screen via the glyph
blitter -- Japanese players saw this in 1997. Full analysis in 4a.

**We do not hit it.** Our English replaces the whole span and the stray glyph
disappears, so the English build already reads correctly. This is only worth
doing if we ever ship a *Japanese* build or want byte-level parity with intent.

**The fix, if we take it.** Insert one byte -- a valid nullary selector above
`0x5D` -- before each affected text run, so the reader eats that instead of the
real lead byte. Every record holding one of the 14 would grow by a byte, so the
rel16s that span the insertion all relocate; `script.py` already does exactly
this relocation for translated text, so the machinery exists. **Do not attempt
it before item 4 closes** -- growing a record in a file whose tiling we cannot
fully vouch for is how a byte goes missing somewhere we are not looking.

---

## Carried over from before this list existed

- 73 untiled records; 119 of 20,269 branch targets missing a boundary (99.413%);
  10 opcode slots used but marked no-op (162 uses).
- `m/MS6012` `4:14[0]` duplicate table-key collision — the record's occurrence
  has to go into the key before that file is safe to translate.
- Restore the 8 lost / 4 changed translations in
  `docs/recovery/2026-09-07-1ebe-reextract.tsv`.
- `m/MS006A` r00 is 34,424 bytes against the loader's 32,767 cap — blocks the
  byte-build path only, not the overlay.
