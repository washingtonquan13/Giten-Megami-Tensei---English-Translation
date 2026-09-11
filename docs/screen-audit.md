# What the player actually saw in Japanese, and why

Written 2026-09-10 from two recorded sessions the player supplied: a long one
ending at My City (about 255,000 draw-string calls) and a shorter second run.

    python tools/screen_audit.py traces/2026-09-09-mycity-glyphs.bin --min 3

The tables say what *should* draw. `giten check` says what is unreviewed.
Neither says what a player actually saw, and the difference turned out to matter
more than either number: **most of the Japanese on screen is not untranslated
text.**

---

## 0. The answer

| cause | long session | second run |
|---|---|---|
| no extractor reads the source file | 60% | 92% |
| the row has English and Japanese drew anyway | 30% | 3% |
| the row exists and is untranslated | 7% | 4% |
| no table row carries the text | 3% | 0% |

Two causes account for about nine tenths of it, and **neither is a translation
gap**:

1. **The location strip has no extractor.** Every district name it draws lives
   in `et/ET000D.BIN`, which nothing reads. That alone is 369 of the 616
   Japanese draws in the long session.
2. **Rows that are already translated did not reach the screen.** 185 draws in
   the long session came from rows whose `en` column holds clean English.

Actually translating something new is the *smallest* of the three buckets.

---

## 1. The location strip -- `et/ET000D.BIN`

This was parked as P1 in [`todo.md`](todo.md) with the note "in no table -- found
by decoding every game file and searching the plaintext". It is now measured,
and it is the single largest visible defect in the patch.

Structure of chunk 1, which is the ordinary `et/` shape:

    u16  count = 221
    u16  offset[221]          -- from the start of the chunk body
    ...  221 NUL-terminated Shift-JIS strings, first at 453

Contents are real Tokyo neighbourhood names: 長崎, 南長崎, 東中野, 池袋, 西池袋,
東池袋, 南池袋, 目白, 目白台, 上落合, 中落合, 下落合, 雑司が谷, 高田馬場, 早稲田,
浅草, 上野, 湯島 and so on.

**Do not translate these by matching text against the script tables.** 新宿
appears in 148 dialogue rows and 市ヶ谷 in more than twenty files; a text match
credits one of those and reports a row the strip never reads. `screen_audit.py`
instead reads this file's own strings and checks each drawn fragment for
membership.

It is tempting to shortcut that by pinning the draw-string variant, and that
would be wrong: **variant 1 is not the location strip.** It is the general HUD
drawer -- party names, the MAG counter, numbers, and "Harajuku Shelter" in
English 1,932 times. What is true, and checked across both sessions, is that
every one of the 20 distinct *Japanese* strings variant 1 drew, 600 calls, is in
this file. Shelter names already translate through `mapnames.tsv`; the 221
district names are a separate table nobody wired up.

**Built 2026-09-10**: `giten/districts.py`, `tables/districts.tsv`,
`giten districts`, and `tests/test_districts.py`. 220 of the 221 names are
romanised; the identity build is byte-exact and container 0 is carried through
untouched.

Two things were settled while building it:

* **The loader** is `0x00412020`: file id `0x0D`, `0x00401C30` called exactly
  twice, handles at `ds:0x0047B724` and `ds:0x0047B728`. So the container count
  is fixed at two.
* **The accessor** `0x00412140` strcpy's the name into `ds:0x00491340` with no
  length limit, which looked alarming until the buffer's size turned up:
  `0x00403A0C` hands the same address to `0x00449710`, which passes it to a
  Win32 import along with `0x100`. **The buffer is 256 bytes**, so no name can
  overrun it.

What is still *not* settled is the strip's on-screen width. The widest thing the
game draws there itself is ten half-width cells; `BUDGET` is set to twelve so
that ordinary romanisations survive intact rather than becoming "Shirokaned"
and "GroundZero". If the strip clips, lower that one constant. The failure mode
is cosmetic and visible on sight.

---

## 2. Translated rows that drew Japanese anyway

This is the overlay-side fault already described in
[`overlay.md`](overlay.md) and in the `giten-overlay-lookup` note. The audit
gives it a size and a shape for the first time. Worst offenders in the long
session, by fragments:

| table | what drew |
|---|---|
| `m/MS6000` | negotiation: how will you speak, seems wary, the approach menu |
| `m/MS00DD` | battle: item obtained |
| `m/MS005D` | dialogue |
| `m/MS7F04` | the staircase prompt, 74 draws on its own |

The families are the tell: **pool files (`MS7F0x`) and merged files (`MS6xxx`)**,
which are exactly the two the overlay's record-index lookup is known to get
wrong. `m/MS7F04` row `0:07[1]` holds "Down: a staircase leads from here.
Proceed?" and the player saw 下へ続く階段がある 移動しますか 74 times.

Nothing needs translating to fix any of this.

---

## 3. What is genuinely untranslated

Small, and mostly the negotiation menus in `m/MS0066`, whose `en` column is
empty while a v0.05 draft sits unused in `ref_en`:

    威圧的に聞く      en: (empty)   ref_en: Ask aggressively
    あく{08:71}威圧的  en: (empty)   ref_en: Keep pressing
    威圧的に詰め寄る   en: (empty)   ref_en: Start pushing

The terminal text (`ダウンロードしています`, `＞ダウンロード正常終了しました`,
`しばらくお待ちください`) is in the same bucket.

One outright bad row, worth fixing on sight -- `m/MS0015` `0:02[25]`:

    jp: の左脚を手に入{08:60}。
    en: .

---

## 4. Gameplay

The player reports no gameplay problems across both sessions, which is the first
independent confirmation that the restored ATB step
([`combat-pacing.md`](combat-pacing.md)) holds up over hours rather than over one
fight.

---

## 5. How the tool works

Three details it gets right that a naive version gets wrong:

* **Pool calls are expanded, not stripped.** A drawn line is contiguous kana;
  the file stores `手に入{08:60}` and `{08:60}` is `れた`. Deleting the marker
  breaks the join and reports "no table row" for text sitting in a table. The
  first run of this audit made exactly that mistake and reported 45 fragments as
  having no row; the real figure is 22, and most of those are the strip. The
  same is true on the English side, which is why the verdict is taken from
  `check_v2.render_english` and not from the `en` cell -- English that splices
  an untranslated pool call reaches the screen in Japanese.
* **Some draw-string variants are typewriters**, one call per glyph. Counting
  those calls separately shreds every sentence into single characters, and the
  first run reported `し`, `た`, `く`, `す` as untranslated Japanese.
* **The glyph code is a `u16` in a `u32` field.** The tool used to read the raw
  dword; `textlog.Rec.ch` masks it. On the Roppongi log about one glyph in nine
  carried something in the high half, and the unmasked read prefixed each of
  those with a spurious `\x00` -- corrupting exactly the one-byte glyphs (ASCII,
  half-width katakana), because a two-byte character survives the mistake by
  luck. It now reads through `giten.textlog`, the same reader
  `giten trace textout` uses.

## 6. Attribution: `--trace`

**Done 2026-09-11.** The tool used to match text, so a fragment appearing in
many rows was credited to the shortest one, and a hard-coded `UNEXTRACTED` list
was the only escape hatch -- a list that still claimed `et/ET000D` had no
extractor months after §1 shipped one.

Both are gone:

* The sets of strings that belong to something *other* than the script are read
  from the things themselves -- `etdb` (skills, map labels), `districts`,
  `racenames`, `itemdb`, `mapnames.tsv`, and the exe's own `.rdata` via
  `giten/exe/menus.py` and `names.py`. A file that gains an extractor stops
  being reported as lacking one without anybody editing a list. Those get a
  `DATA ...` verdict naming the source, so the fix is never confused with a
  script translation.
* With `--trace`, a fragment is attributed to the **event that drew it**: the
  fragment's cp932 bytes are searched for in the trace's own `ch` stream, and
  that event's `(rec, idx_len, rec_hash)` -- the same content key overlay v6
  uses -- resolves to a record, an offset inside it, and the table row that owns
  that offset (through `overlay.plan`'s `sources` where a span covers it).

Two things that had to be got right:

* **The whole fragment is usually not contiguous in the `ch` stream.** What is
  contiguous on screen can be three tokens in the file: `へ続く階段が{08:7B}ある`
  draws as one run and the pool call sits in the middle of it. Matching walks
  down from the whole fragment to its longest contiguous prefix; the event that
  drew the first characters is the event standing in the record that owns the
  line.
* **`pc0` is one past the token it logged.** The character's own offset in the
  record is `pc0 - idx_off - len`. The tool tries both readings and takes the
  one the record's bytes agree with, so the *check* decides rather than the
  comment -- and a hit whose bytes agree is preferred over one whose do not,
  which is what separates the events a v4 trace charged to the right record from
  the ones its stale `RECID` did not.

**Validated on the 2026-09-11 Roppongi session** (a v4 trace, 272,405 events,
156,757 draw-string calls): 23 distinct Japanese fragments, and every one of
them resolves. 20 attribute to a script row, 17 of those with the record
confirmed by content; 3 are the analyze box's Mood values in `dds.exe`. The six
records the inspection named are all among them -- `m/MS7F04 0:07`,
`m/MS00DD 0:55`, `m/MS003D 0:0F`, `m/MS003E 0:01`, `m/MS0018 0:0E`,
`m/MS00DE 0:36` -- and so are the four rows that were blank, including
`は逃げ出した`, which substring matching had credited to `m/MS000F 0:0E[54]`
and which the trace attributes to `m/MS7F04 0:10[0]`.

Without `--trace` the tool falls back to substring matching and says so in its
own output.
