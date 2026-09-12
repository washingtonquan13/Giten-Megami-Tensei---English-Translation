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
  様子 is grammar. Generic address nouns that merely contain an honorific
  character and name no individual (巫女さん "priestess", おばさん "ma'am",
  a stranger's 御兄ちゃん "mister") are translated naturally, without a
  suffix (settled 2026-09-12). Where the Japanese itself writes the demon
  lord's name as バール, keep "Baal" literally -- never merge by referent.
  Item names follow tables/itemdb.tsv over a table's own ref_en.
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
| シャンシャンシティ | **Sunshine City** | owner decision 2026-09-12: the Ikebukuro tower; "Shan Shan"/"Sanshan"/"Shanshan"/"Xanxan City" are retired (also mapnames.tsv) |
| 臨海新交通 | **Rinkai** | mapnames.tsv 0048 "Rinkai Line"; v0.05's "Waterfront" is invented English, which §1 forbids for a place name (m/MS0044 review, 2026-09-12). **Still open, a corpus sweep not a per-file fix:** 臨海コロシアム is "Waterfront Colosseum" in m/MS0008, "Seaside Colosseum" in m/MS0035 and "Rinkai Colosseum" in mapnames.tsv 0056 -- three renderings of one place; glossary.tsv has no 臨海 entry yet |
| 芝浦埠頭 | **Shibaura Pier** | mapnames.tsv 0046 "Shibaura Pier Stn"; v0.05's "Harbour" names no place at all |
| 駅 names | m/MS0036 and the district/mapnames tables | 東池袋 is **Higashi-Ikebukuro**, never "Ikebukuro"; 明治神宮前 is **Meiji-Jinguumae**, never "Meiji"; 代々木公園 is **Yoyogi Park**, never "Yoyogi" -- v0.05 clipped all three in m/MS0044 while spelling them in full in the same file's own 方面 menus |
| names | p/_P_NAMES.tsv and corpus majority | Belberith, Sherry, Chita, Phanuel, Baal Zephon, Togo Shrine |
| ellipses | mirror the Japanese run length | six dots stay six; ASCII dots |
| full-width Latin / digits / ideographic space in English | ASCII | after a switch-table digit strip, `giten audit` a build: no control-flow differences |

Speaker tags (tag `1FD2`) end in a colon, no trailing space, and use the
corpus-wide majority form: grep the tag across `tables/m/*.tsv` before choosing.

## 3. Fitting rules

- Width 74 columns per line, 4 lines per page (text between `<wait>`s);
  half-width ASCII = 1 column, kana/kanji = 2. Rows noted `menu option,
  declared width N columns` must fit N.
- ~~Every pool call `{0k:xx}` the jp has stays in `en` in the same slot, EXCEPT
  that a caller may DROP one and spell the word when the pool word would render
  in the wrong case.~~ (Struck 2026-09-12, m/MS0018 review: it states the
  practice backwards. Measured over the whole tree that day, only **334 of the
  10,275** rows whose jp carries a `{01:xx}`/`{02:xx}`/`{03:xx}` call keep one
  in `en`.) **A pool call is DROPPED and its word written out in English unless
  the pool row's own English is a real word the sentence can use.** Dropping is
  the norm because most pool words are Japanese grammar fragments -- され,
  そうだ, ならば, ません, ‥‥ -- that have no slot in an English sentence at all.
  KEEP the call, in the same place the jp has it, when the pool row renders a
  real word or name the sentence needs -- "Bael", a place, a game term ("Devil
  Buster", "Magnetite"), a ＹＥＳ/ＮＯ a caller offers as a choice -- so that the
  caller follows the pool row if it is ever retuned. Two things still force a
  drop even then: the pool word (a capitalised game term: "Attack", "Magic",
  "Shelter") would render mid-sentence in the wrong case, or its case is wrong
  for the slot (a lowercase pool word heading a menu option). And **read the
  pool row before keeping a call**: one whose pool row has no English ships
  Japanese (detector 8). Never ADD a pool call the jp lacks (v0.05 tokenised
  `1F01` short and read its operand bytes as a call; the draft tree now refuses
  such references). Never drop a name-printing macro (`{01:xx}`-`{04:xx}` that
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
   (m/MS001D 0:0D[41], 2026-09-12). **A grep for さん/くん/君/様/殿 does not find
   the seam when the honorific is broken up by pause dots.** A dying or sobbing
   line writes it `さ‥ん` / `く‥ん`, and a writer who triaged by grepping those
   five strings reported the row as "no honorific present": m/MS0002 0:27[37]
   `さ‥ん‥‥よ‥かっ‥‥‥た` shipped as "...... th...ank... good...ness......",
   dropping Kamikawa's dying "-san" entirely. Read every `1F01` row's jp opening
   character by character, dots included (2026-09-12).
2. **Mid-line honorifics**: a name+honorific inside a line keeps it.
3. **Misattached `ref_en`**: a fluent line from the wrong row, scene or
   character -- shifted by an offset, duplicated across near-identical scene
   variants, swapped with a neighbour, a whole block from elsewhere. Read each
   row against jp; mirrored branches (Hayasaka/Emi) must agree; a twin row
   elsewhere often proves the reading; Newton is a dog and never gets a
   sentence; "TEST" strings are debug artefacts.
   **A shift is a RUN, not a row.** When v0.05 lost step with this version it
   stays out of step until something resynchronises it, so every row in the
   stretch holds an earlier row's line and each one reads fluently on its own.
   The tell is not a nonsense line, it is a line that answers the *previous*
   question: m/MS0064 0:01 runs two rows out from [20] to [64], and a writer who
   found the shift at [22] and [62] (where the displaced text named the wrong
   characters and could not be missed) applied the other seven verbatim and
   reported the file clean -- Rui's また発作だわ！ shipped as "I see. And that is
   why you came here.", which is the answer to [26]. Having found one misattached
   row, walk forward and back until the offset closes; the displaced cell you are
   standing on usually holds an earlier row's line, and an earlier row's cell
   holds yours -- reuse it, so the fix keeps Sneik's wording (2026-09-12).
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
   **`giten check` joins the fall-through alternative and only that one, which
   is how a whole file of broken assemblies passes a clean check.** The common
   shape is a `1E12` case list -- four `1E12 len 00 00 0N` cases, each ending in
   an `18 xx xx` that jumps *into* the fourth case's tail span. The check prints
   the fourth path joined ("To the right is the way deeper in......"), so the
   writer sees a sentence and stops; the other three read "If we head straight
   north from here, is the way deeper in......". m/MS005C had seventeen such
   tails and every one of them was broken on three paths of four (2026-09-12).
   Walk `18 xx xx` over `rec.span_tokens`, resolve each target to a span index,
   and print head+tail for *every* alternative before judging a menu record --
   the heads are usually `checked` verbatim-`ref_en` rows, so the defect sits
   where nothing flags it. Measure each assembled path too: the widest one is
   the budget, not the fall-through.
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

15. **Runtime-print edges**: a row's `tag` names the opcode BEFORE it, so a row
    tagged with a print op (`1F01`, `1F02`, `1E3E`: name / item / count prints)
    begins mid-value and BOTH its edges need a space wherever the English needs
    one ("Katsuragifound a trap" shipped without it); the row before a print
    ends in a space -- EXCEPT a speaker tag (`1FD2`), which ends in its colon
    with no trailing space (corpus 264 to 16; the engine starts a new line).
    **Which space is already there depends on the `1F01` selector**, the byte
    after the opcode (`docs/format-notes.md` §2.11, `giten/exe/names.py`):
    `07` prints the family name, `00` the family+given full name, `08` the
    given name **with a leading space of its own**. So a tail after a `08`
    print needs no leading space, **and the head before one must not end in a
    trailing space either** -- m/MS005C 0:12[60] "Bye then, " before a `08`
    print gave "Bye then,  Ayato" (2026-09-12; m/MS0021 0:1F[13] was the same
    bug). A tail after `07`/`00` does need one -- and a head
    that reads short is often a full name in two halves: m/MS0068 0:06[99] is
    `1F01 07 .. 04FE` + `桐子の事は`, whose `en` " Kiriko, what shall we do
    about her?" is correct as "Tachibana Kiriko", not a stray space
    (2026-09-12). The `expr` operand names the character (`04FF` the
    protagonist, `04FE` his sweetheart Tachibana Yuuka), which is how a file
    full of nameless seams is read at all. Alternative branch chains joined by runtime prints (a
    `1F86`/`1F19` switch choosing tails) must read on every path; when the rows
    are fragments rather than sentences, disassemble the record (m/MS0037,
    2026-09-12: 17 assembled paths checked).

16. **A print row read alone looks truncated, and "restoring" it duplicates the
    head.** A `1F01`/`1F02`/`1E3E` row is the *tail* of a sentence whose subject
    and verb usually sit in the row before it, so a short tail is normal, not a
    dropped clause. m/MS0061 0:08[47]/[48] is `用があるのは、`+name+`君の持つ
    パーツだ。`; the writer read [48] on its own, judged it "truncated to just
    '-kun.'" and wrote the whole clause into it, shipping "What I am after is the
    part held by <name>-kun, this is the part you're carrying." Read head+print+
    tail before adding anything to a print row -- and read *whose* sentence it
    is: the same record's 本来君は‥‥ tail had become "He is not, after all,
    anyone connected to..." when 君 is the person being addressed (2026-09-12).

17. **A span that begins one byte inside a two-byte character.** The tiler
    sometimes hands a span its Japanese with the first kana's *lead byte*
    missing, because the opcode before it swallowed that byte as an operand.
    The tell is a span opening on a half-width kana, or on a stray Latin letter
    where the sentence needs a word: m/MS0031 `ﾆころが‥‥` is ところが, `れがまず
    かった` is それがまずかった, `＜Vを食うと` is `83 81 83 56` = メシ ("grub", so
    the camp's food is what brainwashes you), and `｣：` is `9F|A3 81 46` = 泪：,
    a speaker tag and not punctuation. **The lost character is the English's to
    carry**, because nothing else will draw it -- the owner's own reviewed
    0:0A[2] does exactly that, shipping `レは、悪魔に襲われたんだ` as "I got
    attacked by a demon." A writer who reads such a row literally ships the
    garbage instead: 0:0B[1] went out as "the \\<V> stuff" and 0:01[12] /
    0:1A[18] as a bare ":" with Rui's name dropped (2026-09-12).
    **The opposite case, and how to tell them apart: disassemble.** When the
    missing text is a *whole token of its own* -- an `08 xx` dictionary word, a
    `1F D2` tag -- the engine still draws it and the English must NOT repeat it.
    m/MS0031 0:06[0]'s span is the bare `：` of `1F D2 08 00 81 46`: 早坂 is the
    `08 00` token *before* the span, so ":" is right there and "Hayasaka:" would
    print 早坂Hayasaka:. Dump `rec.span_tokens` beside `rec.data`
    (`giten.script.parse`) before deciding which of the two a short span is;
    guessing from the text alone gets it wrong in both directions.

18. **Seam-aware width, and the tokens that are NOT wide.** `giten check`
    measures every row **alone**, so it never sees a line the engine assembles
    out of head + runtime print + tail: m/MS0053 0:01[34]/[35] measured 44 and 59
    columns apiece and rendered as one 119-column line. Measure a `1F01`/`1F02`/
    `1E3E` run the way style-guide correction 4 says -- `head + 15 columns of
    name + tail` -- and put the `\n` where you want the break, because otherwise
    the engine picks it. Walk the record's tokens and concatenate every span that
    is separated from the next only by a print opcode; a `1FD0`/`1FD2`/`1FD3`/
    `1FBA` between two spans ends the run. **The converse trap:** a control token
    written out in a cell (`{1E10:01003C}`, 13 characters of text) costs **zero**
    columns -- `giten.width.text_width` charges only what draws -- and a writer
    who believes otherwise shortens perfectly good lines for nothing (m/MS0053
    0:05[3], 0:07[13], both 67 columns or less as they stood, 2026-09-12).
    **A print row needs no head span to cost its 15 columns.** When the opcode
    before a `1F01` is a `1FD2` tag or a `1FD0`/`1FBA` window open, no span joins
    it and the run-walk above returns nothing -- but the engine still draws the
    name first, so the line is `15 + the row's own first line` and `giten check`
    measures only the second half. Every one of m/MS0067's 33 joined runs came in
    under 74 after the refit while three *unjoined* print rows were still over
    (0:07[220] 78, 0:07[225] 76, 0:1D[9] 76). Measure `15 + first line` on every
    row tagged `1F01`/`1F02`/`1E3E`, joined or not (2026-09-12).

19. **A relative-clause head before a name print inverts in English.** Japanese
    puts the clause before the noun, so `エレベーターの前まで来た` + `1F01` +
    `‥‥‥` is "<NAME>, who had come as far as the elevator....." -- and an
    English head translated straight through renders "came to the front of the
    elevator Katsuragi.........". The head must be recast as a participial
    phrase that can stand before the name ("Having come as far as the elevator,
    "), not as a finite clause. Three in m/MS0053 alone (0:04[8], 0:04[13],
    0:05[0]); 0:04[13] had also been given a `\n<wait>` the jp does not have,
    which put a page break between the clause and the name it modifies
    (2026-09-12). The tell is a head span that ends in a past-tense verb with no
    following punctuation and a tail span that opens on `‥` or a particle.

20. **A file with near-identical siblings is reviewed against them, not alone.**
    Several families repeat one script with a word changed -- the terminals
    `m/MS00A0`-`MS00AE` (the same kiosk, one district name apiece), the shops
    `m/MS0100`-`MS0115`, the negotiation templates `MS6007`-`MS6016`. Dump the
    family's rows side by side (`awk -F'\t'` over `tables/m/MS00A*.tsv`) before
    judging anything in one of them: the siblings settle the house reading, the
    status convention and the token handling at a glance, and a lone file that
    differs is the one to look at. m/MS00AA came to review with its two
    `．．．\n` rows promoted to `checked` on an empty `ref_en` -- which `giten
    check` itself rejects -- while all thirteen siblings had them right as
    `draft`; the same dump confirmed that dropping that row's trailing `\n` and
    dropping the `{01:23}`/`{03:09}` pool calls is the family's settled practice
    and not a writer's slip (2026-09-12). The converse: do NOT unilaterally
    reword a line the whole family shares (`中止` -> "Cancel" here) -- a
    one-file "improvement" desyncs the other thirteen, and that is a corpus
    sweep for `build/tl-followups.md`, not a review edit.

21. **A record-call seam: `0C ff nn` / `0D ff nn` splices another record's text
    into the middle of a sentence.** `0D` is a **call** and `0C` a **goto** to
    `m/MS<ff>.BIN` record `nn` (`docs/format-notes.md` §"(2) `0B` and `0C`/`0D`
    are not text"), routed through the same handler as the `01..08` pool
    shorthands -- so the target's text resumes in the caller's open window at the
    caller's cursor, exactly the way an `08 xx` dictionary word does. The span
    ending immediately before a `0C`/`0D`, and the **first** span of the record
    it names, are therefore two halves of one rendered line, and `giten check`
    measures them apart. The tell is a record whose span `[0]` is tagged `DATA`
    (nothing precedes it, so the extractor has no tag to give it) and reads as a
    sentence fragment. m/MS0044 is the whole pattern in one file: each of its 25
    station records draws `[駅名]・[路線]` and then calls record `0x00`
    (`[大手町駅・丸ノ内線]ホームに降りる階段がある`) and record `0x01`
    (`[大手町駅・丸ノ内線]プラットホーム`). Sneik had read the second seam -- his
    `0:01[0]` is `" Platform."`, leading space and all -- and missed the first,
    so all 25 stations shipped "Ootemachi-MarunouchiThere are stairs leading to
    the platform here." **One shared row serves every caller, so measure it
    against the longest one**: recast to `" platform is down these stairs."` the
    worst case (Higashi-Ikebukuro-Yurakucho) is 58 columns, where the obvious
    literal head+tail came to exactly 74 (2026-09-12). Walk the container's
    `0C`/`0D` operands over `rec.span_tokens` before judging any record whose
    first span is `DATA`.

22. **Two runtime prints in one sentence, and the roles that get swapped.** One
    sentence can carry several `1F01`s, and the Japanese marks each print's role
    with the particle that follows it -- which is the first character of the
    *next* span, not of the print. `日下はビニールバックに入れられた、`+A+`の
    パーツを、`+B+`に返した。` is "Kusaka returned A's part to B": `の` makes A a
    possessor, `に` makes B a recipient. v0.05 tokenised these seams short, so
    what it left reads as a whole sentence only while the prints are invisible;
    both m/MS0007 0:29[62-64] and its twin 0:2A[64-66] shipped "Kusaka hands
    over<NAME> the part,<NAME> and handed it back to you." -- head with no
    trailing space, the second print handed the *subject* role, and a "you"
    standing where a printed name belongs. Read the particle opening each tail
    span before writing the English, and read the run assembled. **A twin record
    usually settles it**: the same file's `は言われた通り、`+`のパーツを、日下に
    手渡した。` was "<A> did as he was told, and <B> handed the part to Kusaka"
    in 0:2A and the correct "<A> did as he was told and handed <B>'s part to
    Kusaka" in 0:29 (2026-09-12).

23. **A `0C`/`0D` at the *head* of a record is usually not a seam -- and the warp
    op beside it says which `mapnames.tsv` row the line names.** Detector 21 is
    the record call that lands *between* two spans. `m/MS0035` is the other
    shape: every one of its 98 entrance records opens with `0D 35 62` -- a call
    to the file's own record `0x62` -- and only then draws `<place>入口\n`.
    Nothing is spliced in front of the title: `0x62`'s first block is four
    opcodes and its terminating `00`, so it draws nothing before it returns, and
    its own two `1FB2` options ("Enter"/"Walk away") sit in a `1FB1` list opened
    *after* that return. So walk the target's tokens to its first `00` before
    calling a head call a seam; a call that returns without drawing needs no
    leading space and no shared-row measurement. The same records carry the tool
    that makes a location file reviewable at all: the first `expr` operand of
    each record's `1E 04` (`script.literal_expr(rec.data, tok.off + 2)`) is the
    **destination map id**, so every row keys straight onto a
    `tables/mapnames.tsv` row and the two tables can be read against each other
    line by line instead of by guessing which 渋谷 is which. It is how
    `m/MS0035` 0:28/0:29 were caught: both warp to maps `0023`/`0024`, whose
    mapnames entry is 御花屋敷 "Hanayashiki", against v0.05's invented "Flower
    Garden" (2026-09-12).

24. **A literal backslash where v0.05 meant a newline.** Detector 4 is the
    newline that lost its backslash (`.n<wait>`); this is the other half -- a
    v0.05 cell that carries a **doubled** backslash, sometimes with a stray
    letter after it (`\\`, `\\b`, `\\m`), exactly where `\n` belongs. The table
    escapes a real backslash as two characters, so the cell is legal, the
    validator is silent, `giten check` says nothing, and the engine draws a
    backslash mid-sentence: m/MS0021 0:20[9] shipped "And it's not just
    her.\\All of your party members have been healed!". **Scan every `en` for
    two backslashes in a row**, not only for the escapes the format forbids --
    a well-formed escape can still be the wrong one. Corpus-wide there are 28
    such cells, four of them already shipping in `en` and marked `checked`
    (m/MS000E 0:0A[2], m/MS001A 0:06[16], m/MS005A 0:30[3], m/MS005B 0:13[35]);
    the rest sit in `ref_en` waiting to be applied verbatim by the next writer
    who trusts it (2026-09-12, m/MS0021 review).

25. **A sibling cited as precedent must be read in its `en` column, not its
    `ref_en`.** Detector 20 says to dump the family side by side; this says
    which cell settles it. The pass has spent days rewriting place names *out*
    of `ref_en`, so a sibling's `ref_en` is often the very reading that was
    already rejected there -- quoting it back is how a corrected name returns
    to the tree in a different file. m/MS0036 0:3F shipped 芝浦埠頭駅 as
    "Shibaura Station" on the report's claim that "m/MS0035 0:49 already
    established this exact location as plain 'Shibaura Subway Station'": that
    string is 0:49's `ref_en`, while its committed `en` (ef1e20a) is "Shibaura
    Pier Subway Station", carrying §2's binding 芝浦埠頭 = Shibaura Pier. The
    same trap catches any note that says "matched the precedent in <file>" --
    open the sibling and look at column 7, and prefer a binding §2 row over
    any file's practice (2026-09-12, m/MS0036 review).

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
which comes from disk), `python -m tests.run translation_floor`, then commit with a PATHSPEC COMMIT and no separate `git add`:
`git commit -m "..." -- tables/m/<NAME>.tsv tests/data/tl-floor.json`
(plus this rulebook if amended). Two reviewers share one git index, and a
staged file is swept into whoever commits next (it happened on 2026-09-12:
26fd6a0 carried another reviewer's review); a pathspec commit uses its own
temporary index and takes only the named files. Never `git add -A`/`.`,
never stash/checkout; other writers have
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
