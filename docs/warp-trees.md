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
開店してねーんだ。」 then `02 1F` is not a pool call and `partial.tokenize_prefix`'s
reading of the head is wrong in a way that has been guessed at since the file
was opted into prefix tiling.

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
