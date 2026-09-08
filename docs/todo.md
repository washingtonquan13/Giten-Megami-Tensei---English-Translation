# Open work, newest findings first

Kept because the same items kept being rediscovered from scratch. Each one says
what is *measured*, so nobody has to re-derive the number before deciding
whether to do it. Tick items here when they land; delete nothing.

---

## Done

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

### 1. `m/MS6xxx` gets no English — designed and built, NOT YET SHIPPED

**The design is proven offline; the C hook is written and compiles but has not
been verified, so nothing is installed.**

The mechanism: `rebind()` asked two questions a merged buffer cannot answer.
*Which file is this?* — by hashing the whole 1024-byte record index, which
belongs to a merge of up to five files. *Where does this span go?* — from our
model of one file's layout, which the merge moves. So it returned 0 and 7,943
spans were never served.

overlay.dat **v5** asks neither. A span carries the record it lives in, its
offset inside that record, and a hash of the Japanese it replaces:

    addr = live_index[rec].offset + rec_off
    serve only if fnv1a(live[addr : addr + jp_len]) == jp_hash

Measured against the real merges (25 `et/ET0007` rows x 16 slots):

| | |
|---|---|
| m/MS6000's spans that resolve | **7,310 of 7,400 (98.8%)** |
| every merged file's spans | **18,024 of 18,192 (99.1%)** |
| the 90 that do not | records another file replaced — refused, not mis-served |
| m/MS6000's spans against a *wrong* buffer | **0 of 109** |

Virtual addresses now follow the live image end, because a merged buffer is
longer (`m/MS6000` c0: 0x1D7B alone, 0x23D4 merged) and tails handed out from
the old end would land on records that only exist in the merge.

Done: `giten/overlay.py` (v5 + `resolve`), `giten/exe/hook.c`, and
`tests/test_merged_overlay.py`. `parse` still reads v4 so recorded traces keep
their meaning.

**What is left, and it is the risky half:**

- `tests/test_overlay.py::test_c_hook_serves_the_same_bytes_as_the_model` walks
  the real C against the model, and **this machine refuses to execute a freshly
  linked binary** (`PermissionError`, from every directory tried). The test now
  prints `NOT RUN ... the C hook is UNVERIFIED` rather than passing quietly.
  Run it somewhere that allows it before building an exe.
- Then rebuild the exes and install a v5 `overlay.dat`. **Until both happen the
  installed exe and overlay stay v4** — which is why the game still works. A v5
  file under a v4 hook is not a crash: the hook sets `state = -1` and everything
  plays in Japanese.
- The exe budget moved 2048 -> 3072 bytes of cave for the two verification
  bitmaps and the second binary search. **The in-place count is still 38 bytes**,
  which is the number `test_the_exe_is_only_as_patched_as_the_documentation_says`
  exists to hold still.
- Only `m/MS6000`'s entry is reachable for a merged buffer today (`rebind` maps
  `0xE0 + slot` to its container). The demon-specific files' own spans need the
  hook to try more than one entry per buffer — a follow-up, worth roughly the
  difference between 7,310 and 18,024 above.

### 2. Finish the untranslated ordinary rows — 216 of 854 done

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

### 3. Why did `ムールムール：` draw in Japanese?

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

### 4. 25 rows in `m/MS610D` ship English that still contains Japanese

e.g. `褫{01:00}襁Devil Buster襄`. Mojibake, not translation. Same file already
holds 24 of the overlay's 29 refusals (`0xFF` structural bytes), so it wants a
pass of its own.

### 5. ~~Finish the half-translated row in `m/MS000C`~~ — misdiagnosed

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

## Carried over from before this list existed

- 73 untiled records; 119 of 20,269 branch targets missing a boundary (99.413%);
  10 opcode slots used but marked no-op (162 uses).
- `m/MS6012` `4:14[0]` duplicate table-key collision — the record's occurrence
  has to go into the key before that file is safe to translate.
- Restore the 8 lost / 4 changed translations in
  `docs/recovery/2026-09-07-1ebe-reextract.tsv`.
- `m/MS006A` r00 is 34,424 bytes against the loader's 32,767 cap — blocks the
  byte-build path only, not the overlay.
