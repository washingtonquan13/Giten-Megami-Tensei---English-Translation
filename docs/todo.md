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

### ✅ CLOSED: combat difficulty is the Windows port's own balance

Settled 2026-09-08 by the person playing it, against PC-98 footage of the same
game: PC-98 enemies act far less often and several party members act before the
enemy does. **That difference is the port's, not this patch's.** Nothing here
caused it and nothing here should try to "fix" it.

Do not reopen this from the symptom. What the investigation did establish, and
what is worth keeping:

- **`5dce533`'s divider is a no-op** and is retracted (entry 0 below). The
  `dds_dev_bat*` exes are deleted from the install.
- **`dds_dev_btl<n>.exe` is real** -- it gates the battle state machine at
  `0x0041720A` -- but `btl3` made no perceptible difference when played, so the
  battle's phase rate is not what decides how many turns a side gets. Kept
  because it is correct and tested, not because it helps.
- **The battle is strictly turn-based.** Every call state 32's handler makes
  lands outside `0x0042Axxx`-`0x0042Dxxx`, so the engine does not run while the
  player is choosing, and `0x00402740` freezes the popup countdown for
  input-wait popups. There is no time limit on a command.
- The architecture map and the pacing measurements below stand.

If it is ever worth revisiting as a *deliberate* rebalance rather than a bug,
the lever is demon agility in the stat tables, not the loop.

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

##### Counting turns from the glyph log is not a reliable instrument

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

### 4b. The six `m/MS0031` records -- 2 explained, 3 staged for a trace, 1 open

**Two are not model defects at all.** Their walk fails *inside dead data after a
terminator* (opcode `00` = `or ax,0xFFFF; ret`, which ends the run loop):

| rec | terminators | last one | dead bytes after it | fails at |
|---|---|---|---|---|
| `00` | 10 | 0x5F | 177 | 0x60 |
| `0D` | 2 | 0x31 | 4 | 0x33 |

No branch anywhere in the container targets either dead region, so nothing
executes those bytes. `0D`'s tail even has the canonical switch shape
(`31 14 ff` is a switch *entry*, matching `0F 00 00 31 12 01 00 ... 31 11 ff` in
four tiling records) -- it is leftover data, not code we mis-parse.

**Three turn on one binary question.** `02`, `03` and `17` end with a conditional
branch whose operands run past the record, and whose final byte is `00`:

    r02  ... 0a 1d 01 | 18 00           opcode 18 = [rel16]
    r03  ... 0a 1d 01 | 16 00           opcode 16 = [rel16, expr]
    r17  ... 0a 1f 00 | 10 01 01 00     opcode 10 = [rel16, expr], selector 00 = [u8]

Two facts point opposite ways, which is exactly why this needs the engine:

* **For "the `00` terminates":** all 22 tiling records in the container end with a
  `0x00` byte, 21 as a one-byte terminator token. `r02` and `r03` contain
  **exactly one `0x00` byte each -- the final one**. Our model eats it, leaving
  those records with no terminator at all.
* **For "our model is right":** the runtime image is one flat buffer
  (`base(id) = 0x400 + sum of lengths`) with no end-of-record, so spilling into
  the next record is physically normal; and every component of the reading is
  independently verified against engine code -- opcode `10` four ways on
  2026-09-08, the expression table 94/94 against the engine's own two tables.

**The run is staged.** `tools/make_warp_seq.py` writes `0D 31 17` (call) then
`0C 31 02` (goto) into `m/MS0017` r01, so one session measures `r17`, `r02` and
-- if `r02` spills -- `r03` too. `play/warp31/ddswin` holds it with `m/MS0031`
**restored byte-identical to the original** (the fall-through patch is gone) and
exactly one file changed. Predictions are registered in the tool's docstring
*before* the run, A vs B, so the result cannot be read either way after the fact.

**`0B` is still open** and is not in this run: its `1F 04` at 0x236 runs a
`pairs_ff` for 612 bytes, swallowing whole records, which is plainly wrong rather
than one byte out. It needs its own analysis.

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
