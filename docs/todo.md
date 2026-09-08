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

### 1. The `m/MS6xxx` family gets no English at all — 7,943 spans

297 of 449 overlay entries. The runtime image is a merge of up to five files
picked at runtime, and the engine reports it as file id `0xE0 + slot`, so both
halves of the hook's `(FILEID, fnv1a of the record index)` lookup miss and
`rebind()` returns 0. Modelling the merge statically is necessary and **not
sufficient** — one record (`0x97`) is 976 bytes at runtime against 82 on disk,
so no static hash of the index can ever match.

The fix direction is to learn the merge from the engine rather than guess it
from content: `0x0040EB00` is handed the file id and kind on every load.

Mechanism and evidence: `tests/test_negotiation_image.py`, `docs/limits.md`
(overlay), the `giten/records.py` docstring.

### 2. Translate the 854 ordinary untranslated rows

854 of 36,243 rows outside the pools and outside `m/MS6xxx`. These are safe:
the overlay never moves an address, script files stay byte-identical, and
virtual space is not a constraint (median file uses 0.1% of its room, the worst
— `m/MS0030` — 56%).

Concentration: `m/MS00D1` 221, `m/MS0000` 87, `m/MS001B` 49, `m/MS0064` 48,
`m/MS006C` 31, `m/MS002B` 30, `m/MS000F` 29, `m/MS0003` 24.

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

### 5. Finish the half-translated row in `m/MS000C`

`全てが夢だったのかとすら思えてしまう` still shows inside an otherwise English
line (`A happy moment.........`).

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
