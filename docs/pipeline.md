# Translation pipeline

Extract the game's text into editable tables, translate the tables, build patched
`.BIN` files, validate them, install them. Python 3.8+, standard library only, no
dependencies.

The game folder is **read-only** to everything here except `install`, and
`install` backs up every file it touches before writing.

> **Two engines.** `--engine v1` (the default) is the original span scanner over
> `text/`; `--engine v2` is the opcode-aware pipeline over `text_v2/`, built on
> the verified format in `docs/format-notes.md`. v1 is kept running only because
> translators are working in `text/` right now — **v2 is the one to build a
> release from**, and everything v1 does wrong is listed under
> [The v2 engine](#the-v2-engine). Migrate finished work forward with
> `python -m tools.giten migrate --from text --to text_v2`.

```
game ddswin/  ──extract──▶  text/*.tsv  ──(you translate)──▶  text/*.tsv
                                                                   │
game ddswin/ ─────────────────────── build ◀───────────────────────┘
                                       │
                                 build/ddswin/  ──check──▶ findings
                                       │
                                    install ──▶ game ddswin/  (+ build/backup/)
```

---

## Quick start

```sh
export PYTHONIOENCODING=utf-8        # Windows consoles default to cp1252

python -m tools.giten where          # show the paths it resolved
python -m tools.giten extract --family all
#  ... edit the `en` column of the files under text/ ...
python -m tools.giten check
python -m tools.giten build
python -m tools.giten install --from build/ddswin --to "<path>/ddswin"        # dry run
python -m tools.giten install --from build/ddswin --to "<path>/ddswin" --yes  # for real
python -m tools.giten stats
```

Run everything from the repository root. Tests: `python -m tests.run`
(or `python -m pytest tests` if pytest is installed).

### Finding the game folder

In order: `$GITEN_ROOT` (pointing straight at `ddswin`), otherwise a `ddswin`
directory found by walking up from the repository root and looking in each
ancestor and its immediate children — the game folder is normally a sibling of
the repo. A `ddswin` **inside** the repo (i.e. `build/ddswin`) is never accepted;
otherwise a build would shadow the game and the identity test would compare a
build against itself.

---

## Commands

### `extract [--family ms|id|et|p|m|all]`

Writes one table per game file under `text/`. Families:

| family | files                    | count |
|--------|--------------------------|-------|
| `ms`   | `m/MS*.BIN` event scripts, negotiation pools, word pools | 200 |
| `id`   | `et/ID*.BIN` demon-negotiation menus | 17 |
| `et`   | `et/ET*.BIN`             | 86 |
| `p`    | `p/P*.BIN` character records (names) | 432 |
| `m`    | `m/M*.BIN` map data (no recognised text; extracted for completeness) | 109 |
| `all`  | `ms` + `id` + `et` + `p` | |

Re-running `extract` is safe and idempotent: `jp`, `off` and `tag` are always
re-derived from the game files, while any `en` a translator has written is
carried over, matched on the row identity. Rows never change identity, so tables
can be merged with an ordinary three-way merge.

`m/MS7F07.BIN` is deliberately **not** extracted — it is the `08 nn` macro
dictionary, not display text. Its entries are expanded inline into every `jp`
that references them, so editing it would change the source text of unrelated
spans. It is still rebuilt (byte-identically) like every other file.

### `build [--out build/ddswin] [--family ...] [--identity]`

Rebuilds **all 844 encoded files** from the game folder, substituting spans whose
`en` is filled in. Files with no table, and files whose rows are all no-ops, come
out byte-identical. `--identity` ignores the tables entirely.

The source of truth is always the game file, never a previous build.

### `check [--width-scale F] [--max-line-width N] [--skip-identity] [--show N]`

Runs the validators (below). Exit status is non-zero if there are errors;
warnings do not fail the run.

### `install --from build/ddswin --to <ddswin> [--yes]`

Copies differing files over the game folder. **Dry run by default** — `--yes` is
required to write. Every original is copied to
`build/backup/<YYYYmmdd-HHMMSS>/` and the copy is re-read and verified *before*
the original is overwritten. A built file with no counterpart in the game folder
aborts the whole install: the pipeline replaces shipped files, it never adds new
ones.

### `stats [--no-per-file]`

Spans translated / remaining, per file and per tag.

### `migrate [--from text] [--to text_v2] [--report P]`

Extracts a fresh set of v2 tables and carries every finished translation over
from another table set. Reads `--from`, writes only `--to` and the report
(default `build/migrate-report.txt`). See
[`migrate --from text --to text_v2`](#migrate---from-text---to-text_v2).

### `verify [--dir build/ddswin_v2]`

Reference-decodes every file of a build with `tools/giten/refdecode.py` — an
independent transcription of the engine's reader — and re-tiles every record,
comparing against the source. Passes when the build decodes and tiles *exactly
as well as* the originals: same record count, same set of untileable records.

### `--engine v1 | v2`

`extract`, `build` and `check` take `--engine`. `v1` (default) is the original
span scanner over `text/`; `v2` is the opcode-aware pipeline over `text_v2/`.
`check --engine v2 --verify --out DIR` also runs the build verification above.

---

## The TSV schema

UTF-8, tab-separated, LF line endings, one header row, `#` comment lines ignored.
One row per text span.

| column | meaning |
|--------|---------|
| `file` | game-relative key, `m/MS0000.BIN` |
| `rec`  | frame identity: `R7:AA` = record 7 of a record pool, id `0xAA`; `F0` = a file with no record framing |
| `idx`  | index of the span within its frame |
| `off`  | byte offset of the span in the decoded body — informational only, it moves when an earlier span changes length |
| `tag`  | `1FD3`, `1FB2`, `DATA`, `NAME`, … (see below) |
| `jp`   | the source text, dictionary-expanded and escaped |
| `en`   | your translation |
| `note` | free-form; the extractor pre-fills warnings here |

**`(file, rec, idx)` is the row identity** and is stable across re-extraction.

**`en` semantics.** Empty means "use the source bytes unchanged". `en` equal to
`jp` also means that — the extractor pre-fills `en` for spans that are already
English, and those rows are no-ops, so a fresh extract followed by a build
reproduces the game byte for byte.

**Tags.** `1FD0` narration window open · `1FD1` window close (occasionally
carries a prompt) · `1FD2` speaker name · `1FD3` speech line · `1FB2` choice
option · `1FBA` narration continuation · `1FFA`/`1FFB` styled run ·
`DATA` a record payload that begins with bare text (negotiation and word pools) ·
`NAME` the fixed-width name field of a `p/` character record.

**`p/` names share one table**, `text/p/_P_NAMES.tsv`. 432 files with a single
16-byte name each would otherwise be 432 two-line files. The `file` column makes
each row unambiguous.

---

## Escaping rules

`jp` and `en` use one reversible token language. Nothing else is legal; anything
else is a `check` error.

| in the table | means |
|--------------|-------|
| `\n`         | a line break (byte `0A`) |
| `<wait>`     | the page-wait control (`1E 10 01 01`) — the game waits for a keypress |
| `{XX}`       | a runtime-insert control byte, `XX` in hex (`{01}`, `{02}`, `{03}`, `{0B}`, `{0C}`) |
| `{DICT:nn}`  | an `08 nn` macro whose dictionary entry could not be resolved |
| `\\`, `\{`, `\<` | a literal backslash, brace or angle bracket |
| `\t`, `\r`   | tab / carriage return (they do not occur in the shipped data) |

Rules for translators:

* **Keep every `{XX}` token, in the same order.** They are runtime substitutions —
  a character's name, an item — not decoration. `{01}{03}：` is a speaker line
  whose name the game fills in. Reword around them; never drop or reorder them.
* **`{DICT:nn}` must not survive into `en`.** It means the macro table did not
  have that entry. Ask before guessing.
* **Never type a raw `{` or `<`** — write `\{` and `\<`.
* `\n` where the original breaks a line. `<wait>` where the original pauses.
* Text is encoded as **cp932**: ASCII, half-width katakana and full-width
  characters are all fine; anything outside cp932 (curly quotes, en dashes, `€`,
  emoji) is an error. Use `'`, `"` and `-`.

The `08 nn` dictionary macro never appears in `en`: `jp` is already expanded, and
the builder writes literal bytes.

---

## Validators

`check` runs these. **Errors** must be fixed before a build is trustworthy;
**warnings** are work items and judgement calls.

| rule | level | what it checks |
|------|-------|----------------|
| `identity` | error | building with every `en` empty reproduces all 844 source files byte-exactly |
| `dict`     | error | no `{DICT:nn}` survives in an English span |
| `format`   | error | printf specifiers (`%s`, `%d`, `%5d`, `%-16.16s`) match between `jp` and `en` |
| `tokens`   | error | `{XX}` tokens match `jp` exactly, in order |
| `cp932`    | error | the English text encodes in cp932; escapes are well-formed |
| `pname`    | error | a `p/` name is at most 15 bytes (16-byte field, NUL-terminated) |
| `encode`   | error | any other failure while encoding a span during the trial build |
| `width`    | warn  | a line exceeds the width budget |
| `width-choice` | warn | ditto, for `1FB2` choice options |
| `missing`  | warn  | non-empty `jp`, empty `en` |
| `resize`   | warn  | an edit changed the byte length of a span in a frame with no known length field (see below) |

`identity` is the load-bearing one. If it fails, nothing else the pipeline
reports means anything.

**Silencing `missing`.** Put one of `@keep`, `@skip`, `@no-tl`,
`@untranslatable` in the row's `note`. The markers are `@`-prefixed so ordinary
prose in a note — including the extractor's own hints — can never switch a check
off by accident.

**The width budget.** The game draws half-width ASCII from an 8×16 bitmap font
and full-width Shift-JIS at 16 px, so a line's width is measured in half-width
units: ASCII and half-width katakana count 1, everything else counts 2. The real
per-window budget is *not known yet*. The default is conservative: a translated
line may be as wide in pixels as the widest line of its own `jp`, i.e.
`--width-scale 1.0`, which is exactly "twice the Japanese character count".
Raise it with `--width-scale`, or impose a hard cap with `--max-line-width N`,
once the real figure is known. The validator **reports**; it never truncates.
Width is only checked on rows you actually edited (`en` differs from `jp`), so
pre-existing English does not drown the report.

---

## How the formats are handled

### Container

```
raw  = [u16 LE header][encoded body]
enc[i] = plain[0] ^ plain[1] ^ ... ^ plain[i]      (a running XOR, no key)
plain[i] = enc[i] ^ enc[i-1]
```

Byte-exact on all 844 encoded files (`m/` 309, `p/` 432, `et/ET*`+`et/ID*` 103).

The header word equals `len(body)` for 783 of them. For 38 `m/MS6xxx`, all 17
`et/ID*` and a few `et/ET*` it is something else, still under investigation.
Policy (`container.recompute_header`, the single place to change it): if the
source header was `len(body)`, emit the new length; otherwise preserve it
verbatim. Unmodified rebuilds are byte-identical either way.

### Frames — where a length field is known, and where it is not

A decoded body is divided into *frames* that tile it completely. A frame either
owns a u16 length field the builder rewrites when the payload's size changes, or
it owns none and is spliced in place.

**Record pools** (`record` frames) — some `m/MS6*` and `m/MS7F*` files are pools
of `[id:u8][len:u16 LE][data:len]` records whose `data` ends with `00`. The walk
is verified, not assumed: a fresh chain must parse three records in a row before
it is believed, and a record is only kept if its payload is at least 60% text.
If fewer than half the walk's records pass that test, the file is not a pool at
all. 29 files qualify — the negotiation pools (`MS6007`–`MS6016`,
`MS6106`–`MS610C`) and the word/name pools (`MS7F00`–`MS7F02`, `MS7F06`,
`MS7F07`). Editing a line in one of these is fully safe: the record's `len` is
recomputed. Runs between record blocks that are not records (e.g. the four bytes
`5F 6A 66 00` between the `A*` and `4*` id blocks of `MS6007`) become `gap`
frames and are copied through untouched.

`MS6300`, `MS6400`, `MS6F00`, `MS6800`, `MS6801`, `MS6F1F` are binary lookup
tables. They yield no text spans and are copied through verbatim.

**Flat frames** — everything else: the `m/MS0*`..`m/MS1*` event scripts, the
non-pool `MS6*`, and `et/ET*` / `et/ID*`. These are raw opcode streams with the
text inlined between `1F xx` tags, and **no length framing has been established
for them**. Details in "Known limitations".

### Spans — what is exposed for editing

A span may only start where we know text begins:

* immediately after one of the text tags `1F D0/D1/D2/D3/B2/BA/FA/FB`;
* at the first byte of a record payload in a record pool.

The tag list is derived by counting, for every tag in the corpus, how often it is
followed by at least two text characters: `D2` 99%, `B2` 93%, `D3` 91%, `D0` 53%,
then `FA`/`FB`/`BA`/`D1` lower but with unmistakable real lines among them. Every
other tag scores about 0% and is treated as an opcode.

A span stops at the first byte that is not part of the text grammar: ASCII
`20..7E`, half-width katakana `A1..DF`, a valid Shift-JIS pair, `0A`, `08 nn`,
`1E 10 01 01`, or one of the five inline control bytes `01 02 03 0B 0C`. That
inline set is empirical: counting control bytes that sit surrounded on both sides
by at least three text characters gives a sharp split — `02` (592), `01` (229),
`03` (175), `0C` (127), `0B` (66), then a long tail of ones and tens that are
plainly neighbouring opcodes (`18`: 21, `1E`: 13, …).

Two details that are easy to get wrong and are covered by tests:

* **Shift-JIS trail bytes are `40..FC` (excluding `7F`)**, which overlaps ASCII
  and the control range. A scanner that classifies bytes without tracking the
  lead byte will read the second half of a kanji as an opcode.
* **The `1F` scan advances one byte at a time.** `08 1F` (dictionary entry 0x1F)
  is a legal pair and occurs immediately before `1F D2` in several files; a
  scanner that consumed two bytes per `1F` would swallow the real tag and
  silently drop the speaker name.

Everything outside a span — opcodes, operands, jump targets, tables, record
headers — is never shown to a translator and is re-emitted from the source.

### `p/` character records

124 bytes (16 files are 123): a 2-byte header and a 122-byte body. The display
name is a fixed 16-byte NUL-padded field at body offset `0x36`, edited in place.
Names may be at most 15 bytes plus the terminator; the builder refuses a longer
one and keeps the original bytes, and `check` reports it.

---

## The v2 engine

Everything below supersedes the v1 sections above wherever they disagree. It is
built on `docs/format-notes.md` (each claim there tagged VERIFIED / CODE /
HYPOTHESIS) and `docs/opcodes.json` (768 opcode entries plus the expression
grammar), both recovered from `dds_en.exe`.

```sh
python -m tools.giten migrate --from text --to text_v2   # carry translations over
python -m tools.giten extract --engine v2                # refresh text_v2/ from the game
python -m tools.giten build   --engine v2 --text text_v2 --out build/ddswin_v2
python -m tools.giten check   --engine v2 --text text_v2 --out build/ddswin_v2 --verify
python -m tools.giten verify  --dir build/ddswin_v2      # reference-decode a build
```

### What v1 gets wrong, and why v2 exists

| v1 | reality | consequence |
|---|---|---|
| a file is one container, cipher seed 0 | a file is a **sequence** of containers, and the seed is derived from each container's header word | byte-exact for an unmodified file; **wrong for any container whose length changes**, and wrong past the first container in the 51 multi-container files |
| record framing guessed by a resync walk | `[u16 count][u8 id][u16 len][data]`, exact | v1 mis-framed the event scripts entirely and treated them as one flat blob |
| text found by scanning for `1F xx` tags and stopping at "unknown" bytes | text is **bare**; a byte `< 0x20` is an opcode with typed operands | operand bytes leaked into text (`{0B}ｼ`, `{02}じゃd`) and resyncs invented `{DICT:92}` |
| no branch handling | 123 opcodes carry a **PC-relative** `rel16` | any length change silently broke every branch spanning the edit |
| width budget = "as wide as the Japanese line" | 74 columns per line, 4 lines per page, menu option width declared by `1F B1` | the budget was a placeholder with no relation to the engine |

### Container and cipher seed

```
container := u16 hdr (plaintext) , hdr bytes of ciphertext
file      := container+

seed  = (hdr >> 8) ^ (hdr & 0xFF)          # 0x401B20
plain = c ^ prev ; prev = c                # 0x401B40, prev starts at seed
```

The engine never validates `hdr` as a length — its only functional role is to
**seed the cipher** (`0x43AA90` keeps `hdr - 2` in a local and never reads it).
By convention it equals the body length, and every shipped container satisfies
that, so on rebuild `hdr = len(new_body)` and the body is re-encrypted with
`seed_of(hdr)`. **Header and cipher must agree**: change the length and you
change the seed. Getting this wrong corrupts `body[0]` — the low half of the
record count — which is exactly the bug v1 has the moment anything resizes.

All 844 files the pipeline handles are container chains that land exactly on
EOF. (`docs/format-notes.md` §0 says 842 of 844 over a slightly different file
set that includes `et/A0000` and `et/A0001`; those two are the only non-chains in
the game folder and are not in the pipeline's families.)

`tools/giten/refdecode.py` is a second, independent transcription of the
disassembly — a byte-at-a-time stream reader that shares no code with the
builder. The tests and `verify` check builds against *it*, not against the
pipeline's own idea of the format.

### Record layer

```
body   := u16 record_count , record * record_count
record := u8 id , u16 len , len bytes
        | u8 id , 0xFFFF , u8 cond , u8 param , u16 len , len bytes
```

At runtime the loader allocates `0x500` bytes: a `0x400`-byte, 256-entry
`{offset, length}` index followed by the record data **in id order**, with one
`0x00` standing in for every absent record. So

```
base(id) = 0x400 + sum(length(j) for j < id)         # length(j) = 1 when absent
```

and that is the coordinate space the script PC — and every branch — lives in.
**Changing the length of record k shifts every record with a higher id.**

`records.is_record_layer()` decides whether a file really has this layer: at
least one record somewhere, and no container that has trailing bytes *and* no
records. That accepts exactly `m/MS*` (200 of 200) and `et/ID*` (17 of 17), and
rejects `m/M*`, `et/CA*`, `et/ET*` and `p/P*`, which put other structures in the
same container. It is two files better than the strict reading in the notes,
which rejected four files over a record **count word that overstates its own
body** (`m/MS600A` container 4 declares 217 records where 163 fit;
`et/ID00A2`/`et/ID00A3` declare 169 where 1 fits) and one that has 4 158 bytes
after its last record (`m/MS610B` container 15). Both the bogus count and the
trailing bytes are re-emitted **verbatim**; rewriting the count would only change
which garbage an engine that trusts it reads. Those records carry the advisory
`@partial` marker.

Each container is its own runtime image. 35 files repeat record ids *across*
their 16 containers, so the containers cannot all be installing into one
256-entry index; `0x43AA90` loads exactly one container per call. Relocation
therefore never crosses a container boundary.

### Tokens: what `jp` and `en` contain

A record is tiled into typed tokens by `vmops.tokenize`, driven entirely by
`docs/opcodes.json`. A byte `>= 0x20` is text (two bytes after a Shift-JIS lead
byte); `0x1D`/`0x1E`/`0x1F` are escape prefixes; everything else is an opcode
whose operands are an ordered list of `u8` / `u16` / `u32` / `rel16` / a
recursive `expr` tree / a `0xFF`-terminated `list_ff` / the one data-dependent
`rule:wait_1E10`. **If the table cannot tile a record, tokenizing fails** — it
never resynchronises, because resynchronising one byte late is what produced
v1's phantom tokens.

A **span** is a maximal run of *inline* tokens containing something that draws.
Inline means: literal text, `0A` (newline), the eight pool calls `01`–`08`, and
`1E 10` (page wait). Every other opcode ends the span and is copied through byte
for byte, so **a translator never sees an operand and cannot type a branch
displacement.**

| rendered | bytes |
|---|---|
| `\n` | `0A` |
| `<wait>` | `1E 10 01 01` |
| `{01:03}` … `{08:1F}` | a pool call: the opcode plus its `u8` record number |
| `{1E10:010005}` | any other `1E 10` form, operands folded in |
| `{=E9}` | one literal byte that is not valid cp932 on its own |
| `\\` `\{` `\<` | literal backslash / brace / angle bracket |

**Operands are folded into their opcode's token.** `{01:03}` is one token
meaning "opcode `01`, operand byte `03`" — never `{01}` followed by `{03}`, and
never `{01}` followed by a stray `0x03` pretending to be text. A token's payload
is exactly the operand bytes the engine will consume, and `codec.encode` re-tiles
each token to prove it before accepting it.

`{=HH}` is deliberately spelled differently from an opcode token: the engine
takes the byte after a Shift-JIS lead unconditionally, so a run like `E9 00` is
two *text* bytes that happen not to decode — and its second byte would otherwise
render as `{00}`, the record terminator, and re-encode into a broken record.

`jp` stays **byte-faithful**, so a macro call shows as `{08:25}` rather than the
Japanese it splices in. The readable form goes in the `note` column as
`reads: …`, with every pool call expanded (recursively — pool records may call
other pool records). Translators normally *drop* pool calls and write the English
word out; that is expected, and only an **added** call is reported.

`{DICT:nn}` no longer exists. It was never in the data.

### Relocation

`rel16` operands are PC-relative and measured from the byte immediately after
the operand, in runtime-buffer coordinates:

```
target = (offset_after_the_operand + imm16) & 0xFFFF
```

Relocation is generic and derived from the token stream, never from a per-opcode
rule:

1. build the old runtime image (`base(id)` over the container's records) and note
   where every token lands;
2. substitute the edited spans, tracking each record's unchanged runs and the two
   **anchors** of every replacement — its first byte and the byte just past it;
3. build the new image;
4. rewrite each `rel16` so it points at *the same instruction* it used to.

With no edits every delta is zero, every displacement recomputes to the value it
already had, and the rebuild is byte-identical — which is the identity test.

Two cases get reported rather than guessed at:

* **a branch that lands strictly inside an edited span.** The replacement text
  has no byte corresponding to that target, so the *edit is skipped* and the
  source text kept, with an error naming the row. (27 rows in the current
  `text_v2`.) Leaving the displacement and shipping it would point a jump into
  the middle of a new English sentence.
* **a branch that already pointed outside its container's runtime image** — 308
  of about 20 000 branches in the shipped data, all in files with wild
  immediates (dead code, or a mis-tiled opcode reading text as a displacement).
  Their displacements are left alone and counted.

### Width budgets

From `docs/format-notes.md` §3, all VERIFIED. One column is 8 px; half-width is
1 column, full-width Shift-JIS is 2. `0x453C50` **auto-wraps** — it breaks the
line when `cur_col + width > max_cols + slack`, with `slack = -2` for ordinary
characters — so the effective budget is `max_cols - 2`.

| context | budget |
|---|---|
| narration / speech line | **74 columns** (the 76-column bottom message box, window type 1/12, minus the 2-column kinsoku slack) |
| lines per page before a `<wait>` | **4** (6 in the tall box, window type 0) |
| menu option | the width the menu's `1F B1 <expr>` **declares** — 20 in 1 690 of 1 752 menus; the extractor reads the literal and records it in the `note` |

Every width finding is a **warning**, not an error: the engine wraps rather than
clipping, so an over-wide line breaks where the engine chooses instead of where
the writer meant. About 500 lines of the shipped English already exceed 76
columns.

### `migrate --from text --to text_v2`

Strictly additive and one-way. It reads `text/`, extracts a fresh set of v2
tables, copies the finished work across, and writes **only** under `text_v2/`
plus a report at `build/migrate-report.txt`. Nothing under `text/` is touched —
there is a test that asserts it.

Rows are matched strongest key first, each v2 row claimed at most once:

1. **byte offset** — both extractions read the same shipped bytes, and a v1 `off`
   into `unxor(raw[2:])` resolves to the same byte as a v2 span's
   `container.off + record data offset + span offset`. This matches 35 307 of
   35 338 v1 rows, so it is an identity rather than a similarity guess;
2. **(record id, span index)** — only where v1 actually had a record framing
   (its `R7:AA` rows); in a v1 `F0` flat file `idx` counts spans across the whole
   file, so keying on it would manufacture confident nonsense;
3. **identical text within the same record**, the v2 span rendered the way v1
   rendered it (`08 nn` expanded, tokens stripped);
4. **identical text, unique within the file.**

Only real translations are carried — a v1 row whose `en` equalled its `jp` was a
pre-fill of already-English source, which the v2 extractor re-derives itself.
Carried text has its control tokens **re-bound**: a v1 `{01}` becomes the k-th
`{01:nn}` of the corrected source line. Four things are reported instead of being
carried silently:

* `could not be ported` — the `en` was written against bytes v1 read wrongly (it
  contains `{0B}`, `{0C}` or a `{DICT:nn}`); the line needs re-translating;
* `landed on a @noedit row` — the record is one the builder will not edit; the v1
  English is preserved in the `note` rather than parked where it can never build;
* `@operand rows re-opened` — the 900 rows v1 marked `@operand`. Their `en` is
  deliberately **not** carried: the v2 `jp` for that place is a different, correct
  string. The report prints v1's `jp` against v2's `jp` for every one, e.g.
  `{02}じゃd` → `{02:08}‥` and `{02}データ<wait>` → `{02:08}\n<wait>` (the
  "データ" was the operand of `1E 10`);
* `no v2 row at all` — nearly all inside `@untiled` records.

### Non-editable records

Four markers can appear in a `note`. `@noedit` is the one to test for — it is
present whenever the builder will refuse an edit, whatever the specific reason.

| marker | meaning | editable? |
|---|---|---|
| `@untiled` | the opcode table cannot tile this record (123 of 20 278, cause identified in `format-notes.md` §2.10). One row per record carries a best-effort reading so the text can still be *read*; the record is copied through verbatim. | no |
| `@dupid` | two records share an id inside one container, so `base(id)` is ambiguous. Blocked only in the four such containers that actually branch (`m/MS6000` 0/1/8, `m/MS6800` 0); the other five are flat string pools where nothing measures against `base(id)`, so they stay editable. | mixed |
| `@partial` | the container's count word disagrees with its body, or the body has trailing bytes. Advisory: the record list itself is complete and self-consistent. Verify those files in game. | yes |
| `@noedit` | set alongside whichever of the above blocks the edit. | no |

### TSV schema differences

Same eight columns. `rec` is now `"0:3A"` (container 0, record id `0x3A`) or
`"NAME"` for a `p/` display name; `idx` is the span's index **within that
record**; `off` is the span's byte offset inside the record's data; `tag` is the
encoding of the opcode immediately before the span (`1FD3`, `1FB2`, `1E12`, …) or
`DATA` when the span opens the record.

### Current state

```
84 tests pass (38 v1, 46 v2)
identity build byte-exact on all 844 files
migrate: 7 914 translations carried, 338 re-bound, 900 @operand rows re-opened
build:   92 files changed, 7 888 spans in 4 828 records,
         1 323 branch displacements relocated
verify:  20 278 records in source and build; 20 155 tile in both;
         123 untiled in both; 0 decode regressions, 0 tiling regressions
check:   0 errors, 7 028 warnings (6 929 untranslated, 77 over-wide lines,
         22 over-wide menu options)
```

---

## Known limitations

* **v1 only — no length framing for the event scripts.** `m/MS0*`..`m/MS1*` and
  `et/ET*`/`et/ID*` are opcode streams. A general `[id][len]` walk does not
  describe them — only 60 of 303 script files parse strictly to the end, and
  inspecting those shows the matches are coincidental (`m/MS0000.BIN` "parses"
  as two 13 KB records). There *is* evidence of a `0B <u16 len>` show-message
  opcode: in `m/MS0003.BIN` three consecutive message blocks match their declared
  length exactly, and the count includes the trailing `18 xx 00` opcode. But a
  scan for `0B`-prefixed blocks covers only 15–80% of the text tags depending on
  the file, so no framing that reproduces a whole stream has been found. Until it
  is, the builder splices edited spans in place and `check` raises the `resize`
  warning for any edit that changes a span's byte length in one of these files.
  Such an edit shifts every later byte in the file and cannot be proved safe from
  outside — **verify those in game**. (The existing v0.05 English does contain
  lines of a different length from the Japanese, so the format evidently tolerates
  this to some degree; that is an observation, not a guarantee.)
  When the framing is pinned down, add a parser to `tools/giten/framing.py` and
  register it in `FRAMINGS` — that is the whole change.
* **The header word for 61 files is not understood** and is preserved verbatim.
  Hook: `container.recompute_header`.
* **The width budget is a placeholder.** See "The width budget" above.
* **`suspect` rows.** About 500 spans render as short fragments that are probably
  misread operand data rather than dialogue. They are extracted anyway (a filter
  strict enough to exclude them also excluded genuine untranslated Japanese such
  as `{01}{03}：`), flagged in `note`, and counted separately by `stats`. Check a
  suspect row against a hex dump before translating it.
* **NUL-terminated string tables are not extracted.** The span detector only
  starts a span after a known text tag or at a record payload, so plain
  `\0`-terminated string arrays are invisible to it:
  * `m/M*.BIN` map files hold map names (`Hatsudai Shelter`) — already English;
  * `et/ET0000.BIN` holds the demon race table (`Deity`, `Goddess`, `Avian`, …)
    — already English;
  * `et/ET0018.BIN` (608 entries), `et/ET0040.BIN` (878) and `et/ET7F00.BIN`
    (486) still hold Japanese (`初台壊滅前`, `原宿緊急応援出動`, `＠辞書０`).
    These look like event/flag labels padded to a fixed width with full-width
    spaces rather than player-facing text, so they were left alone rather than
    guessed at — someone should confirm in game before spending effort on them.

  Adding them is a contained job: the `Span.fixed_len` mechanism that handles
  `p/` names already does fixed-width, NUL-padded, edit-in-place fields, so a
  string-table scanner plus a family entry is all that is missing.
* **Text baked into `dds.exe`** (menus, item names, system messages) is out of
  scope here; see `tools/exe_analysis/`.
* `install` has never been run against the real game folder by the tooling
  author; it has been exercised end to end against a throwaway copy.

---

## Package layout

```
tools/giten/
  paths.py        game/repo locations, ddswin discovery
  files.py        families and file enumeration
  tables.py       TSV read/write
  container.py    the container chain and the header-derived cipher seed
  cli.py __main__.py

  # v2 -- the opcode-aware pipeline (text_v2/)
  refdecode.py    an independent transcription of the engine's reader, for tests
  records.py      [u16 count][u8 id][u16 len][data] and the runtime buffer
  vmops.py        the tokenizer, driven by docs/opcodes.json
  codec.py        tokens <-> the editable jp/en string
  pool.py         the eight m/MS7F0*.BIN macro pools (gloss + width)
  script.py       spans, the edit/relocate builder, @untiled/@dupid/@partial
  width.py        the real column budgets
  extract_v2.py build_v2.py check_v2.py migrate.py

  # v1 -- the original span scanner (text/), kept while translators use it
  framing.py      frames, and which own a length field
  spans.py        where the translatable byte runs are
  tokens.py       the reversible text <-> bytes codec
  dictionary.py   the 08 nn macro table (m/MS7F07.BIN)
  extract.py build.py check.py install.py stats.py
tools/bin_tools/  the original exploration scripts; giten.py, giten_pack.py,
                  giten_text.py and giten_lines.py are now thin wrappers over
                  the package and keep their old public names and CLIs
tests/            python -m tests.run
```
