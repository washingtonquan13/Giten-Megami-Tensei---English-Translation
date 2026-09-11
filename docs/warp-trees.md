# Warp trees: making the engine tile the records nothing has ever run

`giten warp <file-hex> <rec-hex> --out build/warp/<name>` builds a complete
**Japanese** play tree whose opening jumps straight to one record. This file is
copied to `build/warp/README.md` (which is gitignored, like everything under
`build/`) so the instructions sit beside the trees.

The engine is the tiler. `dds_dev_jp.exe` logs one trace record per token
dispatch, so a record the interpreter has actually executed has *known*
instruction boundaries — no model, no inference. Every record still in the
tiling census is there only because no play session has ever reached it. A warp
costs five minutes of play instead of a playthrough.

## What a tree is, and why it is Japanese

`original/ddswin` hard-linked (a tree's data costs nothing on disk; `fc/` alone
is 324 MB), `Config.exe`, the dgVoodoo wrapper from the play install, and
`dds_dev_jp.exe` — the tracer build with **no** English data patches and **no**
`overlay.dat` beside it. Both halves matter:

* an English exe re-points the item database at `et/et0102.bin` and dies on the
  first frame when that file is absent, which it is in a Japanese tree;
* with no `overlay.dat` the overlay hook no-ops, so the engine executes the
  file's own bytes and every logged program counter is directly comparable with
  what the tokenizer produces from those same bytes. A served span would move
  the boundaries and the measurement would be about the overlay instead.

The **target file is left byte-identical**. Only `m/MS0017.BIN` record 0x01 is
touched, and only its first three bytes, in place — the record keeps its length,
so no record's runtime base moves and no branch anywhere is disturbed.

## How to run one

1. Open the tree folder and run **`dds_dev_jp.exe`** (not `dds.exe`; there isn't
   one).
2. Start a **New Game** and let the opening play. `m/MS002D` r00,01,02,01,04 run
   first — that is the engine initialising — and then `m/MS0017` r01 runs and
   warps.
3. Play the scene the paragraph below describes until it ends, loops, or the
   process dies. **A crash is a result, not a failure**: `m/MS0031` r02 crashed
   the game in the 2026-09-08 session and that crash is the evidence that its
   final `18` reads its `rel16` out of the next record.
4. Quit. Copy the tree's `trace.bin` to
   `build/traces/warp-<name>.bin` and `textout.bin` to
   `build/traces/warp-<name>-glyphs.bin`, **before launching anything again** —
   the next launch truncates both.
5. `python -m giten tile observe build/traces/warp-<name>.bin --build build/warp/<name>`

### The ESET caveat

ESET (and any other real-time scanner) will not let a freshly built exe with an
appended executable section run, and it may delete it silently. The test suite's
own C harness reports `NOT RUN: this machine will not execute the harness` for
the same reason. Pause real-time protection for the session, or the tree will
appear to do nothing at all. This is also why a trace that comes back empty
should be re-run rather than believed.

---

## The trees

### `m/MS0031` — the late-game Mu-continent / underworld scene

Six records, and the file is reachable in normal play (one `0C 31 1B` exists, in
its own r15) but no trace has ever entered it. Its records refer to each other
through `0F` switch tables: r0E→r0F/r10/r11/r12/r13, r14→r15/r16, r16→r17/r18/r19,
r1A→r17/r18/r19. **r17 is therefore reached in normal flow, from r16 and from
r1A.** r00, r02, r03, r0B and r0D are named by nothing at all — not by a `0C`,
not by a `0D`, not by a switch case anywhere in the corpus. Trees are built for
all six anyway: the warp is the only way to put the interpreter on r17 at a
*known* entry, and the whole point is to compare boundaries, not to reproduce a
route.

* **`MS0031-r00`** — walks to `0x61`, where a `0F` switch case has kind 13. The
  record has ten `00` terminators, the last at `0x5F`, with 177 bytes after it;
  the walk fails *inside* that tail. Expect the warp to print the debug lines
  「＃暫定：ゲームオーバーです。」 and stop almost at once. What the trace has to
  answer is where the engine's last boundary is: if it is at or before `0x60`,
  the 177 bytes are dead data and the record is tiled to its terminator.
* **`MS0031-r02`** — six spans of Alice-style farewell dialogue, then a closing
  `18` whose `rel16` is its own last byte plus `m/MS0031` r03's first, branching
  to `0x2B9D`, past the `0x2457` end of the image. **This one is expected to
  crash after the dialogue**; let it, and keep the trace.
* **`MS0031-r03`** — three spans, same shape, closing `16` with the same
  one-byte spill. Play until it stops.
* **`MS0031-r0B`** — 772 bytes, the corpus's only unterminated `pairs_ff`: the
  `1F 04` at `0x236` is real (its `rel16` targets the record's own final `00`),
  but the record holds only two `0xFF` bytes and both are consumed at `0x113` by
  an earlier `1F 01`, so nothing can end the list. Either the engine runs past
  `0x23A` into the next record, or `_read_pairs_ff` is wrong in a way 916 other
  sites hide. Expect the long prison-camp monologue and then something abnormal.
* **`MS0031-r0D`** — 54 bytes, three spans, two terminators, the last at `0x31`
  with four bytes after it; the walk fails at `0x33`. A very short scene
  (「‥‥‥‥誰も{08:24}ようだ。」). Same question as r00, four bytes wide.
* **`MS0031-r17`** — 「泪：‥‥なによ！」. Straddle-tiled: the closing
  `1F 00 10 01 01 00` wants one byte more than the record has. The 2026-09-08
  session already showed the engine spilling into r18 at `+0x01` and the blitter
  drawing `ﾒ泪：`; this tree re-takes that measurement on a **v5** trace so
  `giten tile observe` can use it.

### `m/MS0080` — the five closed shops

All five records are the same shape: a nine-byte head
`1f 00 02 1f 00 01 1f ff 00`, one speaker span and one body span, and the
trailer `1f 00 10 01 01 00`. The text is the town's shops saying they are shut
(weapon shop, item shop, pharmacy, liquor store, hospital).

**The entry point, searched for and not found.** The brief for this work assumed
these records are entered mid-way by design and that the real entry offset had
to be established first. It was searched for three ways and the answer is that
*nothing names the file at all*:

* **No script reference.** Over every `m/` and `et/ID*` file: zero `0C` tokens,
  zero `0D` tokens and zero `0E`/`0F` switch cases of kind 0 carry the file
  operand `0x80`. (`m/MS0031`, for comparison, has 18 such references.)
* **No exe immediate.** `0x0080` does not appear as an argument to any of the
  loaders — `0x0043AF40`, `0x0043B340`, `0x00438D70`, `0x00433D70`,
  `0x0043B7A0`, `0x0043B650`, `0x0043AD20`. The ten `push 0x80` sites in the
  image are graphics and CRT calls.
* **No merge path.** `et/ET0007`'s three columns form `0x6000 + t` and
  `0x6100 + t` only.

So there is no "real entry offset" to honour, and offset 0 is the only entry
that exists. That is not a wasted measurement — it is the decisive one. Read
from 0 the head is `1F 00` (a two-byte no-op), then `02 1F` (pool call into
`m/MS7F01` record `0x1F`), then `00`, which is opcode `00` — `or ax,0xFFFF; ret`,
the run-loop terminator. If the engine really stops after nine bytes and draws
nothing, the head is a preamble some other subsystem reads and these five
records are not entered at 0 by anything; if it draws 「武器屋：おっと、まだ店は
開店してねーんだ。」 then `02 1F` is not a pool call and the tokenizer's reading of
the head is wrong.

**Since the container-image walk these five records tile completely**, so they
are no longer prefix-tiled and the file no longer needs `partial`'s opt-in: the
trailer reads one byte into the next record, and for r04 — the last — into the
`0x00` the loader pre-installs for absent record `0x05`. Two spans per record
that the old safety kernel used to reject, the `02 1F` and `01 1F` of the head,
are now ordinary spans. Whether *that* is right is the same question.

* **`MS0080-r00`** — 武器屋 (weapon shop). **Watch the screen**: whether any text
  is drawn at all is the measurement.
* **`MS0080-r01`** — 道具屋 (item shop).
* **`MS0080-r02`** — 薬屋 (pharmacy).
* **`MS0080-r03`** — 酒屋 (liquor store).
* **`MS0080-r04`** — 病院 (hospital). This is the last record in the container,
  so its trailing `10 01 01 00` reads into whatever follows it in the runtime
  buffer — the `0x00` filler byte the loader pre-installs for absent record
  0x05. It is the one record of the five that no lookahead inside the file can
  complete.

If a tree stops after nine bytes with nothing on screen, that is the answer for
all five; run `MS0080-r00` first and only do the other four if it draws.

### `m/MS610D` — the negotiation merge, and a demon that never had this script

No jump is patched into these trees. `m/MS610D` is not reachable by a `0C` at
all: only the demon-negotiation merge names an `m/MS61xx` file, and it forms the
id in one instruction — `0x0040EC31 add $0x6100,%edx`, where `edx` is the third
column of `et/ET0007.BIN`. That column holds `{00, 06, 07, 08, 09, 0B, 0C}` and
never `0D`. So the way in is to put `0D` there.

**How the merge works**, from `0x0040EB70` and `0x0040EB00`:

* The row index is the demon's own `p/P####.BIN` field at `0x73` (the descriptor
  copies the 122-byte record to `+0x04` and reads it at `+0x77`). It is a
  *lineage* index, not a per-demon one: 25 rows cover 432 demons.
* For that row the engine merges, in order, `m/MS6000`, then `0x6000 + t0`,
  `0x6000 + t1`, `0x6100 + t2` (each unless the column is `0xFF`), then the
  demon's own `et/ID%04X`. Later files **replace** earlier records by id.
* `0x0040EB00` opens its file **once** and calls the one-container loader
  `0x0043AA90` sixteen times, so container *i* becomes buffer slot *i*, stamped
  `i - 0x20` — which is why the engine reports these images as file ids
  `0xE0..0xEF`. All sixteen containers are always loaded; a script picks one
  with `0C E<slot> <rec>`.

**The demon: ピクシー (Pixie), `p/P20C7`, level 3**, the game's first demon and a
member of table row 5 (16 demons, also プリムローズ, ブルーベル, シルフ,
ハーピー, ネコマタ). Row 5's third column is `0xFF` today, so setting it to
`0x0D` *adds* `m/MS610D` to the merge without removing anything the demon
already had. `m/MS610D` c0 defines records `0x00`-`0x64` densely, including the
conversation's own entry record `0x00`, so **the whole negotiation becomes
`m/MS610D`'s script** — one conversation, branched exhaustively, executes a
large share of its 135 records.

Save files live in the Windows directory, not in the tree, so an existing save
loads in a warp tree unchanged. Demon conversation needs the D.D.C.

* **`MS610D-c0`** — `et/ET0007.BIN` row 5 column 3 = `0x0D`, and nothing else:
  `m/MS0017` is the original. **In game:** load a save that has the D.D.C, find
  a Pixie, talk to it, and take every branch — every conversation topic, both
  outcomes, several encounters. This is the broad pass over `m/MS610D` c0's 35
  straddle-tiled records.

**Why r1B and rCE need more than that.** Once the merge is in place, nothing
names either record:

* c0 r1B's only reference in the whole corpus is a `0E` case in **`m/MS6000`
  c0 r1A** (`0e 0a 00 e0 1b ...` — a 1..100 roll, ≤10 takes it) — and
  `m/MS610D` c0 defines r1A too, so that reference is the record the merge
  replaces.
* c3 rCE is named by **nothing at all**, in any file. It cannot be fallen into
  either: the record below it in id order is `0xC6`, and ids `0xC7`-`0xCD` are
  absent, i.e. one `0x00` byte each — and `0x00` is the run-loop terminator.

So these two trees rewrite a jump the engine *does* make. The dev cave claims
`0C E0 00` — the negotiation's own entry into slot 0 — and substitutes the
target. No script is patched, and `m/MS610D` stays byte-identical.

* **`MS610D-c0-r1B`** — the cave rewrites `0C E0 00` → `0C E0 1B`. **In game:**
  exactly as above; the moment the Pixie conversation opens, the engine is in
  `m/MS610D` c0 r1B instead of its usual opening line. Expect something
  abnormal — r1B is a 97-byte record whose `0E` switch fails at `0x1D` with
  kind 225.
* **`MS610D-c0-rFF`** — the cave rewrites `0C E0 00` → `0C E0 FF`. **In game:**
  as above. rFF is 20 bytes ending `1f 0d 1f e5 00`, and `0xFF` is the highest
  record id there is, so its `1F 0D` expression wants a byte past the end of the
  installed image — there is no next record to read it from, in any buffer.
  Either the model is wrong about `1F 0D` here or the record is broken; the
  trace says which.
* **`MS610D-c3-rCE`** — the cave rewrites `0C E0 00` → `0C E3 CE`, i.e. into
  merge slot **3**. **In game:** as above. rCE opens `0e 32 00 e4 b2 ff` — a
  `0E` switch whose one case jumps to slot 4 record 0xB2 — and fails at `0xA5`
  with kind 229. It also carries `0C FF FF`, and file id `0xFF` inside a merge
  means `m/MS6800` (`0x0040E936`), so the run may leave for that file.

**The slot is not chosen per demon.** The brief for this work asked for "a demon
whose slot is 3"; there is no such thing. All sixteen containers of every merged
file load into slots 0..15 for *every* demon, and which slot runs is decided by
the script with `0C E<slot>`. Slot 3 is reached in ordinary play — `m/MS6000`
c0 r00 does `0C E3 00` at offset 0x40 — but nothing ever asks for record `0xCE`
there, which is why the cave is the only way.

### `m/MS6200` and `m/MS6500` — the 16-bit warp

`0C` reads two `u8` through `0x00433C10`, so a script can only name `m/MS00xx`;
the merge can only form `0x6000 + t` and `0x6100 + t`. Neither reaches `0x6200`
or `0x6500`. **The verdict is that a cave can do it safely, and it needs no new
loader code**: `0x00433D70` — the function the `0C` handler already calls —
takes the file id in a **u16** (`cmp di,0xde` at `0x00433D82` compares the whole
word), resolves it through `0x00433CA0` → `0x0043B720`, and on a miss loads it
via `0x0043B650` → `0x0043AD20` → `0x00401DD0(id, kind 9, 0)`, the generic
`m\ms%.4x.bin` path. `0x0043AA90` reads exactly **one** container per call — one
header word, one count word, count records, return — so a plain 16-bit load
gives **container 0**, which is where all seven of these records live.

The cave therefore only substitutes arguments. It claims the file operand
`0xD9`, which occurs nowhere in the corpus as a `0C`/`0D` operand and is below
`0xE0` so a cave that failed to fire would take the ordinary `m/MS00xx` path
rather than the demon-merge arm. The tree writes `0C D9 00` into `m/MS0017` r01,
exactly like an 8-bit warp.

**In game, for all seven:** start a New Game and let the opening play; the warp
fires when `m/MS0017` r01 runs. These records are fragments of a file nothing
loads, so expect a short run and quite possibly a crash — keep the trace either
way.

* **`MS6200-r16`** — 26 bytes; switch entry at `0x14` has kind 31.
* **`MS6200-r1F`** — 79 bytes; switch entry at `0x0C` has kind 229.
* **`MS6200-r55`** — 10 bytes; a switch entry running past the end.
* **`MS6200-r4F`** — 25 bytes; straddle-tiled since the container-image walk (it was untiled when this tree was built, which is why it has one).
* **`MS6200-r18`** — 22 bytes, straddle-tiled.
* **`MS6200-r1A`** — 165 bytes, straddle-tiled.
* **`MS6500-rC7`** — 141 bytes; switch entry at `0x4E` has kind 255.

**The exe in a cave tree is still called `dds_dev_jp.exe`** so the instruction
above never changes, but it is not the plain build: it carries the `.wrp`
section and its five redirected calls. Do not copy it anywhere else.

---

## Results — the 2026-09-11 session, tree by tree

All 22 trees were played.  The traces are `build/traces/warp-<name>.bin`, the
reports `build/traces/observe-<name>.txt`, the player's notes
`build/traces/warp-notes.md`, and every boundary they produced is a fixture
under `tests/data/observed/`.

**Headline: 2,052 engine token starts the repo had never seen — the fixture
corpus goes 246 records / 1,414 boundaries → 399 / 3,466 — and `giten tile
observe` disagrees with the model at 0 of them.**  Not one opcode
and not one expression node changed.  What did change is the accounting: a
program counter the model does not start a token at is scored as an **entry**
when the model's own reachability closure over the container image reaches it
(every `rel16` target, every straddle landing, walked), because the engine
really does enter a record in the middle of one of our tokens.  The census's
`untiled` category is empty; the eight records in it were classified from these
traces as `dead` (5) or `unreached` (3).

### `m/MS0031`

| tree | what happened | verdict |
|---|---|---|
| `MS0031-r00` | 86 boundaries: `0x0000`, `0x0011`, `0x002C`, `0x002F`, `0x004A`, then 80 text starts from `0x006B`.  All predicted: the `1F 14` switch takes case 01 to `0x002F`, the `1F 79`s jump to `0x002C`/`0x004A`, both `18`s target `0x006B`.  The last token straddles into r01, which the engine then reads from `+0x0002`. | **`unreached`** — the walk stops at `0x0060`, in the third of three nine-byte blobs the `1F 79`s jump over |
| `MS0031-r02` | Six spans of dialogue, then the closing `18` at `0x008C` branches to `0x2B9D`, past the `0x2457` image end, and the process dies.  The model predicted `0x2B9D` exactly. | tiled (`straddle`), crash expected and confirmed |
| `MS0031-r03` | The same, one opcode over: the closing `16` at `0x0040` reads `rel16 = 0x1F00` (its own terminating `00` plus r04's leading `1F`) and branches to `0x2BDF`.  Model target `0x2BDF`, engine `pc = 0x2BDF`, trace ends. | tiled (`straddle`); **new**, and the same mechanism as r02 |
| `MS0031-r0B` | 284 boundaries, 283 on model token starts.  The one that is not is `0x00BA`, the target of the `10` at `0x00B6` whose `rel16` is 1 — the engine branches into the second byte of its own expression and draws 「それがまず…」.  The final `1F 04` measured **612 bytes**, ending at `r0C + 0x0196`, exactly as the model computes it. | tiled (`straddle`); the `pairs_ff` model confirmed to the byte |
| `MS0031-r0D` | 19 boundaries, all on model token starts. | tiled (`straddle`) |
| `MS0031-r17` | 63 boundaries, all on model token starts; the `10` at `0x0079` branches out of the record into `r19 + 0x0050`, which is inside a two-byte text token of r19's own phase. | tiled (`straddle`) |

### `m/MS0080` — five records nothing enters

All five behaved identically and **nothing was drawn**, which is the answer the
tree was built to get.  Entered at offset 0 the engine dispatches exactly two
tokens: `1F 00` (the two-byte no-op) and the pool call `02 1F` at `0x0002`,
whose program counter goes into `m/MS7F01`'s buffer.  The byte it returns to is
`0x0004` — `00`, the run-loop terminator — so the record ends after five bytes
and the shop dialogue at `0x0009` is never reached.  Both boundaries agree with
the model; the ~72/47/37/62/56 tokens after them were never executed by
anything, in this session or in any of the ten on disk.

So the nine-byte head is not a preamble to be entered past: **these five records
are unused**.  Nothing in any `m/` or `et/ID*` file carries file operand `0x80`,
no loader takes `0x0080` as an immediate, and the merge forms only `0x6000 + t`
and `0x6100 + t`.  They tile, the overlay may serve them, and no session will
ever ask.

### `m/MS610D`

| tree | what happened | verdict |
|---|---|---|
| `MS610D-c0` (broad) | The Pixie conversation ran on `m/MS610D`'s script as designed: 127 records observed, 1,357 boundaries, **0 disagreements**.  Only r00 of `m/MS610D` itself was entered, though — the conversation's own opening — so the 35 straddle-tiled records stayed unobserved. | the merge trick works; coverage was thin |
| `MS610D-c0-r1B` | The cave put the engine on r1B six times: `0x0000`, then the `12` at `0x0002` to `0x0052`, then `0x0057`, `0x0059`, `0x005A`, `0x005D` and out through a `0C`.  Every one predicted by the model. | **`unreached`** — the walk stops on the `0F` at `0x001C`, which the `12` jumps over |
| `MS610D-c0-rFF` | The cave fired, but in the merged slot-0 image record `0xFF` is one byte, not `m/MS610D`'s twenty: **no token was ever dispatched in rFF's bytes**.  The run went to the buffer's last byte and then through 610,910 virtual program counters before the process died.  (Those events are dropped by `tile observe` now: on a tree with no `overlay.dat` a program counter at or above the image end means the interpreter has left the script, and everything after it is the engine lost.) | **`dead`** — and the one record of the eight this session did not actually reach |
| `MS610D-c3-rCE` | Five entries, four boundaries each: `0x0000` (a six-byte `0E` with one kind-0 case), `0x0006`, `0x0009`, `0x000B` — where the `0D` leaves for another record every time.  The game later crashed on the last conversation. | **`unreached`** — rCE is the last record of container 3, so the `0E` at `0x00A4` the walk stops on has nowhere to terminate; the engine never reaches it |

### `m/MS6200` and `m/MS6500` — the 16-bit warp

The cave works: all seven records were loaded and entered.  What they are is the
other half of the answer — a file nothing loads, holding bytes that are not a
script any more.

| tree | what happened | verdict |
|---|---|---|
| `MS6200-r16` | one token, at `0x0000`; the trace ends there | **`dead`** |
| `MS6200-r18` | 6 boundaries, all on model token starts | tiled (`straddle`) |
| `MS6200-r1A` | 2 boundaries, both on model token starts; a falling sound, then the crash | tiled (`straddle`) |
| `MS6200-r1F` | six tokens.  The `0E` at `0x000B` is the session's one genuine kind-guard case: a table with keys `1F 54 0E 02 06 9F` (not ascending) and kinds `E5 09 12 1F 00 18`, which the engine read at a 4-byte stride and branched out of at its **sixth** entry to `0x0027`; the `18` there took it to `0x004E` and the process died | **`dead`** |
| `MS6200-r4F` | 3 boundaries, all on model token starts | tiled (`straddle`) |
| `MS6200-r55` | the `0C` in `m/MS0017` r01 jumped to its base, `0x0A00`, and that is the last event: **not one token was dispatched** | **`dead`** |
| `MS6500-rC7` | one token, at `0x0000`; the trace ends there | **`dead`** |

`MS6200-r1F` is why `vmops._read_switch`'s `kind > 1` refusal is documented as
*not* VM-faithful and kept anyway: the engine really does stride a table whose
kinds are anything at all (`0x004327C0` skips a non-matching entry with one
`READ_U8` and one `READ_U16` and never looks at the byte), but dropping the
refusal grows a 390-byte `0F` over `m/MS0031` c0 r00's dialogue — over 80
program counters the engine was observed drawing text at.  A table that covers
bytes the engine itself dispatched as tokens is not a table.
