# The translation pass: rulebook and detectors

The single source of truth for every writer and reviewer agent on the pass.
Read it whole before touching a table. **Agents may append to it** (a new
detector, a new decision) in the same commit as the file that taught it; never
delete a rule, strike it through with the date and reason.

Repository: `C:\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English Translation`
(never the shell's default directory; use absolute paths). Play install (never
touched by the pass): `C:\Giten Megami Tensei - English - v0.05\play\en\ddswin`.

## 0. What the pass is

Fit Sneik's v0.05 English (column `ref_en`) into this version of the game with
**nothing lost**. His voice and register stay. Each row is read against its
Japanese, corrected where it drifts, and fitted to the tokens, seams, splits and
widths this version has. Nobody rebuilds or installs until every file on the
route is written and reviewed (owner's order, 2026-09-11).

Roles: **writers** (Sonnet) edit table files and reports only, never git.
**Reviewers** (Opus) read every changed row of one file against the Japanese,
fix, run the check, and commit that one file. The lead dispatches
`build/tl-dispatch.tsv` (file -> batch -> queued / writing / review /
committed) in route order (`build/tl-route.tsv`).

## 1. Owner decisions (style-guide correction 6 and after)

- **Honorifics are kept**, romanised, for humans, both at name seams and
  inside lines: 英美さん "Emi-san", 早坂さん "Hayasaka-san", 渡邊さん
  "Watanabe-san", 上総様 "Kazusa-sama" (human), 葛城くん "Katsuragi-kun",
  美莉ちゃん "Miri-chan", お兄ちゃん "Onii-chan". Demons with 様 take
  "Lord"/"Lady" ("Lord Bael"). Never add one the Japanese lacks. 君 as a bare
  pronoun is "you"; 父さん/母さん are kinship terms ("Dad"/"Mom"); 様 inside
  様子 is grammar.
- **Profanity is not a register problem.** Adult game. Swearing stays unless it
  REPLACED what the Japanese says; then restore the meaning in the same voice.
- **Place names are romanised Japanese**; district strip and glossary stand.
- **Statuses.** `checked` = read against the jp and kept `ref_en` VERBATIM.
  `draft` = changed or written fresh, with `@tl:<fit|accuracy|style|new>` in the
  note. `reviewed` = the owner only; agents never set it. A row written from
  the jp is `draft`, never `checked`. Never reword a line merely to make `en`
  differ from `ref_en`.
- **Our own earlier drafts are in scope too.** A row with `en` set, status
  `draft` and no `@tl:` marker is an unread draft of ours (ref_src `ours`, or
  no ref at all): read it against the jp like any other row. If it is right,
  keep the status `draft` and append `@tl:verified` to the note so the
  reviewer knows it was read; if it is wrong, fix it with `@tl:accuracy`.
  "Left as pre-existing draft" is not an outcome the pass accepts (added
  2026-09-12 after a writer left 513 such rows unread in two files).
  Reviewers read every row carrying an `@tl:` marker, `@tl:verified`
  included, not only rows whose text changed.
- **Writers never blank an `en`; never edit `jp`, `ref_en`, `ref_src`, `off`,
  `tag`, `idx`.** A file's count of translated rows may never go down
  (`tests/test_translation_floor.py`).

## 2. Glossary decisions made during the pass (binding; also in glossary.tsv)

| Japanese | English | note |
|---|---|---|
| バエル | **Bael** | the demon lord; "Lord Bael", "Bael's forces" |
| バール | **Baal** | the cult only: "Baal Cult", "Baal Soldier", "Baalite", "Baalite Base/Temple" -- never merged with Bael |
| both in one sentence | keep both | the Gabriel myth (m/MS0006) says Bael was once worshipped *as* "Baal"; never regex one into the other blindly -- decide per row from `reads:`, and mind compounds ("Baal Zephon", "Baal Hadad") |
| ＤＤＣ / ＤＣＳ / ＤＤＳ / Ｄ.Ｄ.Ｍ | DDC / DCS / DDS / D.D.M. | distinct terms; dotted where the Japanese dots ("D.D.C.") |
| 隊長 | Commander | never "Captain" |
| 悪魔撃退プログラム | Demon Repel | |
| マグネタイト | Magnetite | capitalised; 生体マグネタイト "bio-Magnetite" |
| 仲魔 | ally (lowercase, prose) | HUD counter keeps "Demon" |
| 悪魔人 | Demonoid | tag "Demonoid:", never "Cambion:"/"Tainted:"/"demon-man" |
| 学者 / 科学者 | Scientist: | never "Scholar:" |
| ＤＢ隊員： / ＤＢ男性隊員： | Devil Buster: / Devil Buster (Male): | never "DB Member:" |
| オートマッピング | Auto Mapping | not "Auto Mapper"/"Auto-Mapping" |
| ペンタグランマ, 合体, マッカ | Pentagramma, Fusion/fuse, Macca | |
| names | p/_P_NAMES.tsv and corpus majority | Belberith, Sherry, Chita, Phanuel, Baal Zephon, Togo Shrine |
| ellipses | mirror the Japanese run length | six dots stay six; ASCII dots |
| full-width Latin / digits / ideographic space in English | ASCII | after a switch-table digit strip, `giten audit` a build: no control-flow differences |

Speaker tags (tag `1FD2`) end in a colon, no trailing space, and use the
corpus-wide majority form: grep the tag across `tables/m/*.tsv` before choosing.

## 3. Fitting rules

- Width 74 columns per line, 4 lines per page (text between `<wait>`s);
  half-width ASCII = 1 column, kana/kanji = 2. Rows noted `menu option,
  declared width N columns` must fit N.
- Every pool call `{0k:xx}` the jp has stays in `en` in the same slot, EXCEPT
  that a caller may DROP one and spell the word when the pool word (a
  capitalised game term: "Attack", "Magic", "Shelter") would render mid-sentence
  in the wrong case. Never ADD a pool call the jp lacks (v0.05 tokenised `1F01`
  short and read its operand bytes as a call; the draft tree now refuses such
  references). Never drop a name-printing macro (`{01:xx}`-`{04:xx}` that
  prints a runtime name).
- `\n` and `<wait>` counts match the jp unless the English needs fewer.
- **`1F01` name seams.** The engine prints a runtime name at the seam. The row
  before ends with a trailing space; the `1F01` row begins mid-sentence and
  NEVER repeats the name; if its jp opens くん。/さん。/ちゃん/殿 the `en` opens
  with the honorific ("-kun. There's no time...").
- `@split` / `@split-tail` rows are the two halves of one line cut where a jump
  lands: the head reads alone, head+tail reads as the full line. Alternative
  fragments that jump to a shared tail (an `18 xx 00` in the record's bytes)
  must assemble grammatically on every path; the record's own bytes settle
  which rows share a tail.
- Pool files (`m/MS7F0x`, called as `{0k:xx}` with k = file id + 1): a
  fragment's English must read in every caller (grep the token); a fill no
  caller renders stays blank; whole-sentence rows (battle messages) are fine;
  ＹＥＳ/ＮＯ-type rows that callers keep are filled.
- Cells cp932-encodable, no raw tabs/newlines; the ONLY escapes are the
  two-character `\n` and `<wait>`. A literal backslash followed by any other
  letter breaks the validator for everyone.

## 4. Detectors -- every review runs all of them

1. **Seam class**: a `1F01` row whose jp opens くん。/さん。/ちゃん/殿/**君** must
   start with the honorific and must not repeat the name; the row before ends in
   a space. Kanji **君** straight after a name-print is the suffix, not the bare
   pronoun -- `{name}君を医療施設まで運べ` is "carry <name>-kun to the medical
   ward", and §1's "君 as a bare pronoun is 'you'" does not reach it
   (m/MS001D 0:0D[41], 2026-09-12).
2. **Mid-line honorifics**: a name+honorific inside a line keeps it.
3. **Misattached `ref_en`**: a fluent line from the wrong row, scene or
   character -- shifted by an offset, duplicated across near-identical scene
   variants, swapped with a neighbour, a whole block from elsewhere. Read each
   row against jp; mirrored branches (Hayasaka/Emi) must agree; a twin row
   elsewhere often proves the reading; Newton is a dog and never gets a
   sentence; "TEST" strings are debug artefacts.
4. **Bare-`n` corruption**: `.n<wait>` where `\n<wait>` belongs (a newline is
   stored as `\` + `n`, so split on `\n` before word-boundary matching).
5. **Short row**: English badly short against its Japanese -- a fluent line that
   stops early. Compare lengths, read anything short.
6. **Doubled seam punctuation**: `{04:00}!\n` plus a literal `!\n`.
7. **Needless rewording**: a draft that differs from `ref_en` with no gain in
   meaning is restored as `checked`.
8. **`en` that merely repeats its own jp token** ships whatever the pool
   record holds: fine when that pool row has English (a `{05:00}` Yes/No
   pass-through), Japanese when it does not -- check the pool row before
   accepting it; a status of `checked` is right only when the rendered result
   is English. A row whose fixed `en` ends up equal to `ref_en` is `checked`.
9. **Shared-tail assembly**: alternative fragments must read on every path.
   The `@split-tail of [n]` note names only the fall-through head; a `0E` switch
   or a run of `18 xx 00` jumps can send *several* alternatives to that same
   tail, and the note says nothing about them. Resolve the jumps before judging
   a tail: in m/MS001D 0:05 all five dish names converge on `ですぅ！`, so four
   of them ended their own sentence and then assembled as "...cream sauce!, it
   is!". Read the gaps between spans, not the note.
10. **Branch-chosen referents may not be gendered**: when who a scene is about is
    picked by a name branch that can be either a man or a woman (早坂/桐島 in
    m/MS001D), every unbranched row about them must stay ungendered in English --
    the Japanese always is. The tell is one file saying "she" in one record and
    "he" in another for the same person.
11. **Numbers**: prices and counts must match the Japanese digits.
12. **Pool callers** (see §3).
13. **Structural scans** before and after applying: bad escapes, `<wait>`
    counts against jp, cells reduced to whitespace, full-width Latin. The
    `<wait>` half is not pedantry: condensing an over-long page is the moment a
    writer drops the page-wait with the fifth line (m/MS001F 0:05[48], [50],
    2026-09-12) and no other rule sees it.
14. **A mid-sentence span break that is not a `1F01`.** Spans concatenate raw,
    and a switch or a jump can cut one sentence into several spans of
    *different* tags with nothing inserted between them: m/MS001F 0:02 prints
    西野 (`1FD3`), ‥‥ (`1FFA`) and と言いましたね (`1FFA`) as one sentence, so the
    English pieces carry their own spacing ("Nishino", `... `, "that was your
    name, yes?") exactly as a `1F01` seam does (2026-09-12). Detector 1 is the
    common case of this, not the whole of it.

## 5. Procedure

Writers, per file: select rows (status != reviewed; `ref_en` set with `en`
empty or == jp, or `en` set with status draft; untranslated rows from jp as
`new`; skip `@noedit`/`@untiled`/`@dead` and rows whose reading has no
Japanese), work through a Python script using `giten.tables.read/write` (Write
tool, absolute paths, `PYTHONIOENCODING=utf-8`; heredocs mangle backslashes),
scans before and after, then `python -m giten check --skip-identity --show
999999` -- **a run that ends in a traceback reports nothing and is NOT a pass**
-- zero ERRORs on lines naming the file, then a report `build/tl/<NAME>.md`
(rows by reason; every meaning change with key, ref_en, en, why; rows left and
why; glossary decisions). No helper agents. If the content filter refuses a
record, skip it, log the key, move on.

Reviewers, per file (a fresh agent per file): compare rows against HEAD with
`giten.tables.read` on the working file and on `git show HEAD:tables/m/<NAME>.tsv`
(line-ending changes make `git diff` show the whole file), read every changed
row against jp, run every detector in §4, fix, check (zero ERRORs; `m/MS0031`
keeps 10 pre-existing `overlay` errors that are engine limits), regenerate
`tests/data/tl-floor.json` (counts from HEAD for every file except this one,
which comes from disk), `python -m tests.run translation_floor`, then commit
`tables/m/<NAME>.tsv tests/data/tl-floor.json` (and this rulebook if amended)
ONLY -- never `git add -A`/`.`, never stash/checkout; other writers have
uncommitted tables in the tree. Message: rows read / corrected with examples /
restored / meaning fixes; end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
Never push. Report per file to the lead: rows read, corrected (three examples),
restored, check result, commit hash, disagreements with the writer, anything
for the owner.

## 6. Follow-ups not blocking the pass

Kept in `build/tl-followups.md` (corpus sweeps for the end of the route:
Bael/Baal by jp, ＤＢ隊員 tags, Watanabe-san, Cambion, City Hall/都庁, DDS
dotting, Auto-Mapping, the `en == own token` class, the `.n<wait>` guard at
extract, MS003B's 699 full-width floor labels, width-choice menu pass,
**ellipsis run lengths** -- §2 says mirror the Japanese, and the inherited
English does not: m/MS001D alone has 37 rows where a `‥‥‥` reads "..." or
".........", none of them wrong in meaning. A corpus sweep, not a per-file
review job, and not something `giten check` sees).
