# Exe patches

Source of truth for `python -m giten exe build-*`. Every row is applied to `original/ddswin/dds_org.exe` and the applier asserts the `old` bytes before writing.

Sets: `xp` (base), `locale` (release = base + locale), `dev` (dev = release + tracer + debug arm; see below).

Builder-applied patches (`giten/exe/tracer.py`, not table rows because their rel32 depends on where the appended section lands; the builder still asserts the old bytes):

| build | VA | old | new | note |
|---|---|---|---|---|
| release, dev | 0x438E8D, 0x438E9B, 0x438F0D, 0x438F32, 0x438FAD | `E8 <fetch 0x438E50>` | `E8 <.ovl hook>` | runtime text overlay (docs/overlay.md) |
| release, dev | 0x45108A | `ff15d8414600 3bc7 76ba` (`call [timeGetTime]; cmp eax,edi; jbe 0x45104E`) | `E8 <.ovl pace> 85c0 74bb 90` (`call pace; test eax,eax; je 0x45104E`) | **60 Hz tick gate.** The main loop ran one game tick per millisecond, relying on DirectDraw Flip's vertical-retrace wait for pacing; without that wait (modern drivers, wrappers) movement, menus and battle animation ran up to 16x too fast. `pace()` (hook.c) advances a 1/3-ms deadline by 50 per tick, requests `timeBeginPeriod(1)` once (the exe never did; timeGetTime otherwise steps 15.6 ms on Win10/11), and re-bases after a stall > 250 ms instead of bursting. The XP tool did *not* change the battle wait (0x1FF17 is `05` in both exes), so nothing else needs reverting. |
| release, dev | 0x43CA5D..0x43CC00 (25 `push imm32` operands, found by scanning) | `68 <.rdata JP name slot>` | `68 <.nam English string>` | **English character names.** The default names the game copies into the character records (family at record+2, given at record+0x13, 17-byte fields; installer 0x43CC00) are 8-byte `.rdata` slots too short for "Katsuragi", so `giten/exe/names.py` appends a `.nam` section with the English strings and re-points the pushes. Given names carry a leading space because `1F01` selector 00 prints family+given with no separator ("Katsuragi" + " Ayato"); a given-name-only print (selector 08) therefore begins with a space. The player can still rename at the name-entry screen. |
| dev | 0x4390C4, 0x439103, 0x43913C | `E8 <exec_token 0x439020>` | `E8 <.trc wrapper>` | **Interpreter tracer.** The wrapper snapshots the interpreter state, calls the real `exec_token`, then appends one 20-byte record to `ddswin	race.bin` behind an 8-byte `"GTRC" u16 version u16 record_size` header: `u16 file, u16 rec, u16 pc, u16 ch, i16 r, u8 capflag, u8 caplen, u16 idx_off, u16 idx_len, u16 pc0, u16 flags`. **`file`, `rec`, `pc0` and the index entry are read *before* the call**; `pc` after it. That matters: the engine clears the script context when a script ends and `exec_token` is still reached once afterwards, so v1 -- which read everything afterwards -- logged `pc = 0` and `idx_off = 0` for every token that ended a script and could not place those events at all (106 of 18,683 on the traced routes). The snapshot lives in stack locals, not the cave buffer, because it spans the real call and a re-entrant token would otherwise clobber it. `flags` bit 0 / bit 1 record the context being null before / after. `pc0` with `pc` also gives the engine's own length for each token, which is what an operand model is judged against. v1 traces (headerless, 16-byte) still decode. |
| dev | the 6 `call 0x451230` sites, and all 71 `call` sites of the six draw-string variants | `E8 <real target>` | `E8 <.tlg stub>` | **Text logger** (the menu-overlay spike). The exe never calls `TextOutA`; it blits every character itself. `0x451230` draws one glyph (built-in half-width font at `0x0046C230`, `GetGlyphOutlineA` for the rest), and six variants -- `0x451650`, `0x451750`, `0x451850`, `0x451950`, `0x451B20`, `0x451CB0` -- walk a `char*` calling it per character. Those six are where a menu overlay would hang, since each takes the string as an argument; but each has a **different signature**, so this build logs both levels and lets a play session say which argument is the string rather than staking the hook on six hand-decoded stack frames. Records `u16 kind, u16 pad, u32 arg1..arg8` to `ddswin	extout.bin` behind `"GTXT" u16 3 u16 36`; kind 0 is a glyph, 1-6 a variant. Each stub pushes its id and shares one body, which tail-calls by overwriting that pushed word with the real target and `ret`-ing to it, so the callee sees an untouched frame. Sites are found by scanning, not listed. Read it with `giten trace textout`. |

| set | file offset | old | new | note |
|---|---|---|---|---|
| xp | 0x506BC | `837c240c07772c33d28a4c142083c2048ac1c0f9` | `8bd8c1eb02837c240c07772c33d28a4c142083c2` | XP compatibility patch r0.2b (code only; its font edits at 0x69E42+ are NOT carried) |
| xp | 0x506D1 | `80e10f240f884c141c8a4c141dc0e004c0f9040ac183fa408844141d7cd66681fe518174398b5424188b0495d0cf460083f81e7d318d4c24218a51ff83c104885438028a51fc8854380383c00283f81e7ce78bc75f5e5b81c494000000c3b0ff88471f88471e8bc75f5e5b81c494000000c39090909090909090` | `8ac1c0f90480e10f240f884c141c8a4c141dc0e004c0f9040ac183fa408844141d7cd66681fe5181743c8b5424188b0495d0cf460083f81e7d348d4c24218a51ff83c104885438028a51fc8854380383c00283f81e7d034b75e48bc75f5e5b81c494000000c3b0ff88471f88471e8bc75f5e5b81c494000000c3` | XP compatibility patch r0.2b (code only; its font edits at 0x69E42+ are NOT carried) |
| xp | 0x54B8B | `0f8440010000` | `909090909090` | XP compatibility patch r0.2b (code only; its font edits at 0x69E42+ are NOT carried) |
| xp | 0x5AB04 | `75` | `74` | XP compatibility patch r0.2b (code only; its font edits at 0x69E42+ are NOT carried) |
| locale | 0x59DE0 | `6afde819fbffff83c404c39090909090` | `68a4030000e816fbffff83c404c39090` | __initmbctable: _setmbcp(-3=ANSI) -> _setmbcp(932); rel32 = 0x45A500-0x45A9EA |
| locale | 0x509A9 | `01` | `80` | CreateFontA lfCharSet DEFAULT_CHARSET -> SHIFTJIS_CHARSET |

Applied by their own modules (each finds its sites in the image, so they cannot be table rows; each asserts what it found before writing):

| build | site | what | why not a data edit |
|---|---|---|---|
| english | `0x468310` system-menu table, `0x46A118` stat/equip labels, and the `printf` templates' `push imm32` operands | `giten/exe/menus.py` -- re-points each `u32` slot at an English string in an appended `.men` section | the strings live in `.rdata`, not in any `m/`/`et/` file; there is nothing to translate on the data side. `EFFECTS` (the status-condition names) is the exception: a packed struct array with the name inline, so it is overwritten in place under a hard six-character budget |
| english | `0x4232C2` (39 B), `0x422D2B` (5 B), `0x422D32` (rel32) | `giten/exe/database.py` -- lifts the 64 KB ceiling off the item database; the load is re-pointed at `et/et0102.bin` (which we add) and the offset table widened `u16` -> `u32` | `et/ET0001.BIN` is capped at 65,535 bytes three separate ways and the English does not fit. `ET0001.BIN` itself is left untouched, so an unpatched exe still reads the original |
| english | `0x42147C` | `giten/exe/mapnames.py` -- hooks the map parser's one pointer computation and indexes a `u32 name[256]` table in `.mnm` | the name is stored inside each of the 109 `m/M####.BIN` headers; one hook covers all of them without editing any map file |
| release, dev | `0x40263A` (`mov eax,15`, the operand) | `giten/exe/timing.py` -- the popup auto-close default. Raised 15 -> 60 for most of this repo's life; **back to the stock 15 on 2026-09-08**, so this pass now asserts the instruction and writes the value already there | **not a translation change.** See the accounting note below |
| release, dev | `0x43F52F` (`lea ecx,[eax+eax*1+5]`) | `giten/exe/timing.py` `atb_pc98()` -- the turn gauge, restored to the 1997 PC-9801 step (`lea ecx,[eax+5] ; nop`) | **not a translation change; a gameplay one, decided by the player.** See the accounting note below |

## What the shipped exe actually differs by

Reproduced by `tests/test_v2.py::test_the_exe_is_only_as_patched_as_the_documentation_says`, which rebuilds the release image from `dds_org.exe` and re-derives these numbers, so they cannot drift silently.

| pass | in place | appended | translation? |
|---|---|---|---|
| XP compat (`xp` set) | 149 B | -- | inherited; not ours, and its 228 font-table edits are deliberately dropped |
| locale (`_setmbcp`, charset) | 15 B | -- | yes |
| overlay hook `.ovl` | 38 B | 5120 B | yes |

The `.ovl` figure is the cave, and it grows as the hook does: 2048 when this
table was written, 4608 for overlay v5's per-span verification bitmaps, 5120 on
2026-09-10 for the merged-buffer fix. **The 38 bytes in place have never moved**,
and that is the number that matters: five `E8` call sites redirected, nothing
else of the original rewritten. `EXE_PASSES` in `tests/test_v2.py` pins both
halves, so a pass that starts editing the original in place fails there.

| background-script divider (`dds_dev_bat<N>.exe` only) | 4 B | -- | no -- behaviour, and **dev builds only**: `0x401985`'s rel32 is pointed at `script_step()` in the `.ovl` cave, which calls `0x43B5E0` every Nth game tick instead of every tick. `0x43B5E0` runs the background script until it blocks (`0x4390F0` = `do exec_token while r >= 0`), so that call is the rate at which scripted actors take their turns. The release exe is built with `SCRIPT_DIV=1` and its call site is untouched. |
| character names `.nam` | 117 B | 512 B | yes |
| menu strings `.men` | 596 B | 1536 B | yes |
| item database `.idb` | 64 B | 512 B | yes |
| location names `.mnm` | 25 B | 3072 B | yes |
| 60 Hz tick gate | 10 B | -- | **no** |
| popup default (left at the stock 15) | 0 B | -- | **no** |
| turn-gauge step restored to the 1997 arithmetic | 3 B | -- | **no** |
| **total** | **1016 B** (0.0080% of 12,675,072) | **7680 B** | |

Three of those 1,016 bytes' worth of edits -- 13 bytes -- do not exist to show English, and they are the ones to argue about:

* **The 60 Hz tick gate (10 B)** is a compatibility fix of the same kind as the XP patch. The engine ran one game tick per millisecond and leaned on DirectDraw Flip's vertical-retrace wait to hold it back; on a driver that does not block, the game runs up to 16x too fast and is not playable at all. Without this the patch has nothing to demonstrate.
* **The popup default (0 B)** was 1 byte and is now none. The argument for raising it 15 -> 60 stands on its own terms -- pinning the loop at 60 Hz gives every tick-counted duration a wall-clock meaning it did not have in 1997, and neither value is the neutral one. What changed is that the dwell turned out to be the *same number* as how long the battle command UI is refused ([`combat-pacing.md`](combat-pacing.md) §2), so 60 was quietly undoing a quarter of what the gauge fix below gave back. The player chose the stock 15 with the gauge restored. Battle messages are short; the pacing was worth more than 750 ms of reading time.
* **The turn-gauge step (3 B)** is the one outright gameplay change in the exe, and the only one not decided here. `0x0043F52F` restores the step the 1997 PC-9801 release uses; the Windows port doubled it and changed nothing else about the gauge ([`pc98-comparison.md`](pc98-comparison.md) §3). Measured 80 party actions to 11 enemy against 1 : 1.22, 1 : 11.88 and 1 : 18.50 in three archived pre-patch sessions. It was built dev-only first and put to the person playing, whose verdict was *"it's technically faithful and actually makes battles, battles (the speed it ran at before was impossible to fight at)"*. **The honest objection is that what this project translates is the Windows port, and its authors doubled that step on purpose** -- so this makes the patch a small rebalance as well as a translation. `dds_dev_x2.exe` builds without it, and `tools/battle_ratio.py` measures the difference, so the decision stays reversible and checkable rather than a matter of taste.

Everything else either shows English or is inherited. Nothing overwrites game content: all English lives in appended sections, `patch.apply` refuses a patch whose old bytes are absent or whose length changes, and no original data file is modified except by the normal table pipeline.

One coupling is deliberate and worth knowing: `database.apply` re-points the item-database load at `et/et0102.bin`, so **the English exe cannot run on a Japanese install** -- the router returns NULL and the game dies on the first frame rather than misreading. `build_image(english=False)` exists for exactly this reason, so a Japanese dev build keeps the hook, the tracer and the pacing and stays trace-comparable.
