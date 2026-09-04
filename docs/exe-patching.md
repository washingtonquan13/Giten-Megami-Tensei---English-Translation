# Patching strings in `dds_en.exe`

The story text lives in the `.BIN` files and is handled by `tools/giten`. This
document covers the other half: the strings compiled straight into the game
executable — status names, the Analyze panel, shop totals, menu labels, error
dialogs, the party roster.

Tool: `tools/exepatch`, Python 3 standard library only.

```
python -m tools.exepatch extract     # rebuild text_v2/exe/strings.tsv from the exes
python -m tools.exepatch check       # validate the table; no binary is touched
python -m tools.exepatch build       # write build/dds_en.exe
python -m tools.exepatch verify      # re-parse the build and prove the edits landed
```

Set `PYTHONIOENCODING=utf-8` before running these on Windows, or the console
will choke printing Japanese.

Nothing in the package ever opens a file inside the game folder for writing.
`dds_en.exe` (the v0.05 fan patch, used as the patch base) and `dds_org.exe`
(the pristine 1999 Japanese build, used as the source of the untranslated text)
are read; the output always goes to `build/dds_en.exe`. Override the game
location with the `GITEN_DDSWIN` environment variable.

---

## 1. Why the exe needs its own tool

`dds_en.exe` is a 1999 PE32 image, ImageBase `0x400000`, four sections:

| section | VA        | file      | raw size   |
|---------|-----------|-----------|------------|
| `.text` | `0x401000`| `0x400`   | `0x62400`  |
| `.rdata`| `0x464000`| `0x62800` | `0x3400`   |
| `.data` | `0x468000`| `0x65C00` | `0x9200`   |
| `.rsrc` | `0x493000`| `0x6EE00` | `0xBA7A00` |

The one fact everything else follows from: **there is no `.reloc` section.**
The image can never be rebased, so every reference to a string is a literal
absolute address baked into an instruction — almost always `push imm32`. That
is a problem when you need more room (nothing can shift), and a gift when you
want to relocate one string (there is exactly one 4-byte number to rewrite, and
it is findable by scanning for the value).

Of the 217 Japanese strings in the original, 209 are reached through exactly one
such pointer. The rest sit in fixed-stride record tables the code indexes by
record number, with no pointer anywhere — those can only be edited in place,
inside their record.

Two regions must never be written:

* **`0x69E30`–`0x6AA30`** — the exe's own 8×16 bitmap font, used for every
  half-width ASCII glyph. It looks like plain data and even decodes as CP932 in
  places; overwriting any of it destroys the UI.
* **`0x509A8`** — `6A 80`, the `push SHIFTJIS_CHARSET` handed to `CreateFont`
  for the double-byte GDI path. Japanese text that is still on screen (and the
  fullwidth digits the patch deliberately keeps) is drawn through it.

`build` refuses to write inside the font table, and `verify` re-checks both
regions byte-for-byte after the fact.

---

## 2. The table: `text_v2/exe/strings.tsv`

UTF-8, tab-separated, one header row, one row per NUL-terminated string found
in `.rdata`/`.data` of `dds_org.exe` (844 rows). Text columns are escaped so a
row is always one physical line: `\\`, `\t`, `\n`, `\r`, and `\xNN` for any
other control byte.

| column | meaning |
|---|---|
| `id` | stable key, `<section>_<file offset>`, e.g. `data_06691c`. Survives re-extraction. |
| `file_off` | hex file offset in `dds_org.exe` / `dds_en.exe` (identical layouts). |
| `va` | hex virtual address of the string. |
| `section` | `.rdata` or `.data`. |
| `slot_bytes` | writable extent: the string's own bytes **plus the NUL run that follows**, i.e. the distance to the next live byte. A replacement of this many bytes *including its terminator* always fits. |
| `refs` | comma-separated VAs of the `imm32` locations that hold this string's address, found by scanning `.text`/`.rdata`/`.data`. Empty means nothing points here. |
| `record_width` | set when the string lives in a fixed-stride record table (see below). A replacement may not exceed it. |
| `max_cols` | rendered-width budget in half-width cells, seeded from the slot. Hand-editable. |
| `jp` | the original 1999 text, decoded CP932. |
| `en` | the English text. **Empty means untranslated.** |
| `note` | free text plus `@`-flags. |

`en` is seeded from what `dds_en.exe` shows today — following the pointer when
the v0.05 patch relocated the string, which it did for eight character names
parked in a cave at the end of `.rsrc` (file `0xC166B4` / VA `0x103A8B4`). If the
exe still shows Japanese there, the column is left empty rather than filled with
the Japanese, so "empty" always means "needs work".

Only `@skip` changes behaviour: it tells `check` to stop demanding a
translation and tells `build` never to touch the row. Everything else in `note`
is a comment. `extract` adds `@skip` automatically in three cases: bytes inside
the bitmap font table, the developers' `…でない場合は連絡して下さい`
assertions, and strings with neither a reference nor a record width (nothing can
reach them).

### Re-running `extract` is safe

`extract` merges: hand-written `en`, `note` and `max_cols` values already in the
table win over the freshly scanned ones. Deleting the file and re-running gives
the same 844 rows back, minus the translation work. `--reseed` deliberately
throws the hand-written values away.

### Fixed-stride record tables

The status-effect table at file `0x62FE8` is the clearest case: 8-byte records
of `[id byte][name, NUL-padded]`, indexed by status id, with no pointer to any
individual name. The id byte reads as a control character, so it is part of the
row's `jp`/`en` text and must be preserved verbatim:

```
rdata_063078   record_width 8   jp \x12混乱   en \x12Confus
```

One id byte plus a terminator leaves six characters. That is why several names
are abbreviated with a trailing period (`Paral.`, `Posse.`, `Suffo.`).

`extract` detects these tables structurally rather than from a hard-coded list:
a run of four or more consecutive strings sharing one start-to-start stride, of
which almost none are referenced by an `imm32`. The reference test is what keeps
pointer-addressed pools (the character-name table looks just as regular) out of
the set — those are freely relocatable.

---

## 3. How `build` places a string

For every row with a non-empty `en` that differs from what the base exe already
shows, in order:

1. **Fits its budget** (`record_width` if set, otherwise `slot_bytes`) — written
   in place and NUL-padded across the whole slot. Nothing moves, no pointer
   changes.
2. **Too long** — appended to a new `.eng` section, and every `imm32` that
   pointed at the old address is rewritten to the new one. Identical
   replacement texts share a single copy.
3. **Too long, and no reference to redirect** — refused with an error. A row in
   a record table that overflows its record is refused for the same reason:
   there is nowhere for it to go.

A string the v0.05 patch already relocated into its `.rsrc` cave always takes
route 2 when it changes, rather than trying to reuse the cave.

The original bytes of a relocated string are left where they are. They become
dead data, which is exactly what v0.05 did with the eight cave names.

### The `.eng` section

| field | value |
|---|---|
| Name | `.eng` |
| VirtualAddress | `0xC3B000` (the image's old `SizeOfImage`, already section-aligned) |
| PointerToRawData | `0xC16800` (the old end of file, already file-aligned) |
| Characteristics | `0x40000040` — initialised data, readable, not writable, not executable |
| Contents | packed NUL-terminated CP932 strings, each 4-byte aligned |

The section header goes at `0x260`, in the zeroed slack between the end of the
existing four-entry section table and `SizeOfHeaders` (`0x400`) — 416 bytes
free, room for ten more sections. `NumberOfSections` becomes 5,
`SizeOfImage` becomes `0xC3C000`, and `SizeOfInitializedData` is bumped to stay
honest. `CheckSum` was already 0 and stays 0; Windows does not verify EXE
checksums.

Strings reach VA `0x103B000` onward (`ImageBase + 0xC3B000`).

### What `verify` proves

* The built image parses, has the expected sections, and no section's raw range
  runs past EOF; the pre-existing four section headers are byte-identical.
* Every patched string reads back as exactly the `en` the table asked for —
  relocated ones by following the rewritten pointer, not by trusting it.
* Every byte that differs from the base exe falls inside a range the plan
  authorised: a patched slot, a rewritten 4-byte pointer, the three PE header
  fields the append touches, or the new section header. Anything else is
  reported with its offset.
* The bitmap font table and the `SHIFTJIS_CHARSET` push are unchanged.

---

## 4. Adding a string

1. `python -m tools.exepatch extract` if the table is missing or the exes
   changed. Existing translations survive.
2. Find the row — by `id`, by `file_off`, or by grepping `jp`.
3. Fill in `en`. Escape tabs/newlines as `\t`/`\n`; keep a leading `\xNN`
   record-id byte exactly as it appears in `jp`; keep every `printf` specifier
   in the same order with the same conversion and length modifier.
4. If you are deliberately leaving it Japanese, put `@skip <reason>` in `note`
   instead.
5. `python -m tools.exepatch check` — this must report 0 errors.
6. `python -m tools.exepatch build && python -m tools.exepatch verify`.
7. `python -m tests.run` for the regression suite.

`check` reports as **errors**: text that will not encode to CP932, `printf`
specifiers that differ in kind or order between `jp` and `en`, an empty `en` on
a Japanese row with no `@skip`, a replacement that overflows its record width,
a replacement too long for its slot with no reference to redirect, and any row
inside the font table.

It reports as **warnings**: `printf` field widths that differ (`%10ld` vs
`%6ld`), a replacement that overruns its `max_cols` budget while still staying
in place, a replacement more than three cells wider than the original, and two
different `jp` values sharing one `en` inside a record table.

### The width budget

Half-width ASCII is drawn from the exe's own bitmap font at exactly 8 px per
character; double-byte glyphs go through GDI at 16 px. So `合計` is four cells
wide and `Total` is five — which is why the shop-total lines drop one leading
space to keep the column where it was. `check` measures with `printf`
specifiers and newlines removed, since both sides carry the same ones.

`max_cols` is seeded from the slot, so it only describes a real budget for a
string that stays home; the budget warning is suppressed for anything long
enough to be relocated. When a relocated string does sit in a known-width
column, set `max_cols` by hand — it survives re-extraction.

---

## 5. What was translated

31 rows, 27 in place and 4 through `.eng`.

**Status table** (`.rdata`, 8-byte records)

| offset | jp | en | note |
|---|---|---|---|
| `0x62FE1` | 灰 | `Ash` | status id 0, never touched by v0.05 |
| `0x63078` | 混乱 | `Confus` | was a second `Panic`, duplicating id `0x0E` 恐慌 |

The brief asked for `Confus.`; the field is six characters (8-byte record minus
the id byte minus the terminator), so the period does not fit.

**Demon attitude words** — shown on the Analyze panel's `Mood` line

| offset | jp | en | placement |
|---|---|---|---|
| `0x66858` | 哀願的 | `Pleading` | `.eng` |
| `0x66860` | 友好的 | `Friendly` | `.eng` |
| `0x66868` | 超敵対的 | `Very Hostile` | `.eng` |
| `0x66874` | 敵対的 | `Hostile` | in place |
| `0x6687C` | 通常 | `Normal` | in place |

The first three do not fit their 8- and 12-byte slots. Each has exactly one
pointer (an array at VA `0x468BF8`), so they relocate cleanly rather than being
squeezed into `Pleadng`/`V.Hostl`.

**Analyze panel** — all in place

| offset | jp | en |
|---|---|---|
| `0x6688C` | ＤＡＳがインストゥールされていません | `DAS not installed` |
| `0x668BC` | アナライズデータがありません | `No analysis data` |
| `0x668DC` | 属性　 %c/%c | `Align  %c/%c` |
| `0x668EC` | レベル L%2d | `Level  %2d` |
| `0x668FC` | ＨＰ   %d/%d | `HP     %d/%d` |
| `0x6690C` | ＭＰ   %d/%d | `MP     %d/%d` |
| `0x6691C` | 態度   %s | `Mood   %s` |
| `0x66928` | 状態   %s | `Status %s` |
| `0x66934` | 詳細アナライズしますか？ | `Run detailed analysis?` |

Every label is padded to a 7-cell column, matching the original's 56 px, so the
values stay in line. `DAS not installed` follows the wording v0.05 already uses
for DDS/DCS/AMS. `Mood` rather than `Attitude` because the column is seven
cells. The literal `L` in `レベル L%2d` is dropped — `Level  L 5` reads as a
typo in English.

**Shop totals** — all in place

| offset | jp | en |
|---|---|---|
| `0x669AC` | `                合計 %10ld   ` | `               Total %10ld   ` |
| `0x669CC` | `                合計 ` | `               Total ` |
| `0x669E4` | `合計 %10ld   ` | `Total %10ld   ` |

`Total` is one cell wider than 合計, so the two indented forms lose one leading
space and the number column does not move.

**Currency** — in place, per `translation/glossary.tsv`

`0x67408` and `0x67418` マッカ → `Macca`; `0x67410` and `0x67420` ＭＡＧ →
`MAG` (the glossary's tight-UI form; `Magnetite` is for prose).

**Roster names**

| offset | jp | en | placement |
|---|---|---|---|
| `0x67BD8` | 惣厳 | `Sougon` | in place — repairs the empty string v0.05 shipped |
| `0x67BE0` | 立川 | `Tachikawa ` | `.eng` |

The call site at VA `0x43CB35` pushes these as a (given name, surname) pair for
roster slot 9, matching slot 8's (カズミ, 山田) → (`Kazumi`, `Yamada `). The
trailing space on the surname is the separator convention v0.05 established for
every other surname slot.

**Gem socketing** — in place. The message routine draws the gem name and then
this text immediately after, so both are written as suffixes.

| offset | jp | en |
|---|---|---|
| `0x680D4`, `0x680FC` | をはめ込んだ | ` was socketed` |
| `0x680E4`, `0x6810C` | と%sを付け替えた | ` replaced %s` |

**DirectX startup failures** — in place

`0x69DD4` ＤｉｒｅｃｔＸ初期化に失敗しました。 → `DirectX initialization failed.`
`0x69DFC` 初期化に失敗しました。 → `Initialization failed.`

---

## 6. What was left Japanese, and why

250 rows carry `@skip`; 125 of them hold Japanese text (the rest are ASCII
fragments inside the bitmap font table or otherwise unreachable). The
Japanese ones fall into five groups.

**Developer assertions (auto-skipped).** The `…でない場合は連絡して下さい。Takubo`
family and `邪教のところ以外このメッセージをみたらお知らせください S.Iseki` —
47 strings naming specific shops and hospitals, printed when the
developers' own location checks fail. They should never reach a player, and
translating them would destroy their value to anyone debugging the game.

**The debug menu**, 23 strings (`0x65C54`–`0x65D38`, plus `0x66068` コンディション影響フロー
and `0x66218` 敵行動フロー). `<デバッグメニュー>`, `<魔法デバッグ>`, 悪魔全滅
("wipe all demons"), フラグ変更 ("edit flag"), ＋１/－１/＋１０… and the rest of
the cheat controls. Not reachable in normal play. `\nきたべ` at `0x66284` is a
developer marker in the same class.

**Fullwidth Latin that already reads as Latin.** The alignment letters
Ｄ/Ｎ/Ｌ/Ｃ at `0x66BFC`–`0x66C10` and the blood types Ａ/Ｂ/ＡＢ/Ｏ at
`0x66D88`–`0x66D98`. GDI already draws them as `D`, `N`, `L`, `C`, `A`, `B`,
`AB`, `O`. Converting to half-width would halve each cell from 16 px to 8 px and
shift whatever column they sit in, for no gain in legibility.

**Fullwidth numerals.** ０–９ at `0x67EDC` and １０–３９ at `0x67F04`, forty
strings reached through a pointer array indexed by value. Same reasoning: they
render as digits already, and half-width would move the column.

**Unreachable strings (auto-skipped).** Strings with neither an `imm32`
reference nor a record width. There is no code path that can be redirected and
no fixed record to overwrite, so the tool declines rather than writing an edit
that would silently do nothing.

Also deliberately untouched, and *not* flagged as needing work: the fullwidth
punctuation tables at `0x68214`/`0x68238` (`’”）〕］｝…` / `‘“（〔［｛…`), which
are the kinsoku line-breaking sets the renderer tests characters against, and
the fullwidth solidus in already-translated strings like `Demon%5d／%2d`.
`check` treats fullwidth *punctuation* as finished work and only fullwidth
letters and digits as Japanese typography.

---

## 7. Known limits

* The reference scan finds absolute `imm32` values anywhere in
  `.text`/`.rdata`/`.data`. A false positive — four bytes of unrelated data that
  happen to equal a string's VA — would be rewritten along with the real
  pointer. None of the 31 patched rows has more than one reference, and `verify`
  reports every changed byte, so a stray rewrite would show up as a diff in a
  place you did not expect. Read the `refs` column before translating a row with
  several.
* `record_width` detection is structural, not a hand-maintained list. A record
  table of fewer than four entries, or one where most entries also happen to be
  pointed at, will not be detected. Set `record_width` by hand if you find one.
* The string scanner rejects candidates that look like binary — pointers,
  half-width katakana mixed with ASCII, one- and two-character ASCII/double-byte
  mixtures. It is possible for a real one-character string in an unusual place
  to be filtered out. Everything the earlier `tools/exe_analysis/sjis_inventory.md`
  pass listed is present.
* The build has not been run: verification is entirely static.
