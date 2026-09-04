# Translation pipeline

Extract the game's text into editable tables, translate the tables, build patched
`.BIN` files, validate them, install them. Python 3.8+, standard library only, no
dependencies.

The game folder is **read-only** to everything here except `install`, and
`install` backs up every file it touches before writing.

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

## Known limitations

* **No length framing for the event scripts.** `m/MS0*`..`m/MS1*` and
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
  container.py    the [u16 header][chain-XOR body] wrapper
  framing.py      frames, and which own a length field
  spans.py        where the translatable byte runs are
  tokens.py       the reversible text <-> bytes codec
  dictionary.py   the 08 nn macro table (m/MS7F07.BIN)
  files.py        families and file enumeration
  tables.py       TSV read/write
  extract.py build.py check.py install.py stats.py
  cli.py __main__.py
tools/bin_tools/  the original exploration scripts; giten.py, giten_pack.py,
                  giten_text.py and giten_lines.py are now thin wrappers over
                  the package and keep their old public names and CLIs
tests/            python -m tests.run
```
