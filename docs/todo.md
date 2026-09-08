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

### 3. 25 rows in `m/MS610D` ship English that still contains Japanese

e.g. `褫{01:00}襁Devil Buster襄`. Mojibake, not translation. Same file already
holds 24 of the overlay's 29 refusals (`0xFF` structural bytes), so it wants a
pass of its own.

### 4. ~~Finish the half-translated row in `m/MS000C`~~ — misdiagnosed

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

### 5. Opcode model: 7 containers, not 119 scattered errors

Re-measured 2026-09-08, and the old framing was misleading.

| | |
|---|---|
| records that tile | 20,617 of 20,690 — **99.65%** |
| corpus bytes inside a record we cannot tile | 3,927 of 1,688,491 — **0.23%** |
| branch targets landing on a token boundary | 20,150 of 20,269 — 99.41% |
| ...**in a container that tiles completely** | **100%** |

**All 119 misses sit in a container that also holds an untiled record; zero sit
in one that tiles cleanly.** So this is not 119 opcode errors scattered through
the corpus — it is 7 containers we cannot frame, and every branch in everything
else already lands where the model says.

The 7: `m/MS0031` c0 (6 untiled, 44 strays), `m/MS610D` c0 (36, 40) and c3,
`m/MS6200` c0 (6, 13), `m/MS6F00` c31 (10, 9), `m/MS6F1F` c0 (10, 9),
`m/MS6500` c0 (1, 2).

Do **not** re-open opcode `10` or `11` from this. Both were settled by warp
trace on 2026-09-06 — 145 of 148 logged token lengths matched and the three that
differed were branches whose logged PC was the target, on a boundary — and the
corpus-driven `['u8']` change that "made 41 records tile" must never be applied.
They emit 90 of the 119 because they are the branches *in the broken
containers*, not because their operands are wrong.

**The method, and where it stops.** `tools/make_warp.py` puts `0C 31 01` at the
start of `m/MS0017` r01 -- no save, no playthrough -- and the engine's own PC log
becomes ground truth. That is what settled opcodes 10, 11 and kind 13.

Checked 2026-09-08, because the first version of this entry assumed it would
generalise and it does not:

- **Verified:** `0C`'s handler `0x00430019` -> `0x00433E70` -> `0x00433D70`
  **calls `0x00433CA0` at `0x00433E06`** -- the resolver with the `0xE0..0xFF`
  branch. So `0C E0 rr` really does warp into conversation slot 0, and
  `0x0040E9BB` builds the merge on demand. That part works.
- **But `0C` takes two u8 operands**, so it can name `m/MS00xx` (0x00-0xDF) and
  the slots (0xE0-0xFF), and **nothing else**. It cannot reach `m/MS610D`,
  `m/MS6200`, `m/MS6500`, `m/MS6F00` or `m/MS6F1F`.
- **And `m/MS610D` is not in `et/ET0007`** -- the third column holds
  00,06,07,08,09,0B,0C, never 0D -- so it is not reachable through a slot either.
- The exe holds **no immediate** for 0x6200/0x6500/0x6F00. (An earlier search
  said otherwise; those bytes were inside the opcode dispatch table at
  `0x4318B0`, not code.)

**So the warp reaches one of the six files, `m/MS0031`, and that one is already
done.** The real question is the one nobody has asked: *how are these five files
loaded at all?* They have overlay entries and English, and nothing found so far
asks for them by name.

**Tested 2026-09-08, and it changes the shape of the problem.**

`m/MS6F00` and `m/MS6F1F` **are not script.** Every "text span" in them decodes
to `ÿ` and punctuation -- `b'ÿ P'`, `b'ÿ-ÿ'`, `b'ÿ'` -- and
0xFF is unassigned in cp932, so it is never text. Neither carries a single row of
English. 7,936 of `m/MS6F00`'s 7,987 records are the one-byte absent placeholder;
it holds 51 real records, and `m/MS6F1F` holds the *same* 51 (identical
record-length histogram). `0x1F` = 31, and `m/MS6F00` container **31** is
`m/MS6F1F` container 0 -- the same data, on disk twice. **20 of the 73 untiled
records are neither text nor unique**, like `m/MS7F05` before them.

`m/MS6200` and `m/MS6500` *are* script -- their spans hold real Japanese
(`大丈夫？`, `友好的`, `威圧的`) -- so those 7 records stay.

That leaves **53 real records**: `m/MS610D` 40, `m/MS6200` 6, `m/MS0031` 6,
`m/MS6500` 1.

**And they are not blocked by a missing opcode.** Asked why the tokenizer gives
up, the answers are `switch entry has kind 13 / 31 / 225 / 255 (not 0 or 1)`, and
then a scatter of `operand past end of record`, which only means the walk was
already out of step. The switch refusal is **deliberate**, and `vmops._read_switch`
says why: the engine's handler only tests `kind != 0`, so it would follow these,
but 0E/0F entries with kind >= 2 point at an instruction 8% of the time -- they
are bytes a lost walk reached. Relaxing it is the same trap as the `['u8']`
change that "made 41 records tile".

**So closing these needs ground truth about whether the walk is out of step, not
a better opcode table** -- and the only instrument for that is the engine's own
PC log, which reaches `m/MS0031` and nothing else. `m/MS610D`, the 40, is the
one that matters and the one still out of reach.

**What "100%" cannot mean:** 374 of the 768 dispatch slots never occur anywhere
in the corpus. Their handlers can be read, but nothing in the game exercises
them, so they can be modelled and never verified. 394 slots are used, the exe
implements 384 of them, and 10 are no-ops with 162 uses between them.

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
