# Giten Megami Tensei -- English Translation Style Guide

> **READ THIS FIRST -- corrections that supersede the body below.**
>
> This document was written for the previous pipeline. Its register, voice and
> convention sections remain the house style and should be followed. Four
> technical claims in it are now known to be wrong or obsolete:
>
> 1. **Bael vs Baal -- item 2 and glossary line 65 are SUPERSEDED.** They record a
>    decision to unify everything to "Baal" (279 rewrites). That is reversed by
>    project instruction: **バエル is the demon lord, "Bael". バール is the cult,
>    "Baal" -- "Baal Cult", "Baal Soldier", "Baalite".** They are two different
>    things and must never be merged. 237 shipping rows saying "Baal" where the
>    Japanese reads バエル were corrected on 2026-09-06.
> 2. **Line width is measured, not a rule of thumb.** The body calls the box width
>    "unverified/TBD" and suggests "~2x the Japanese character count". The real
>    budget is **74 columns per line and at most 4 lines per page** (a page being
>    the text between `<wait>`s), from the geometry table at `0x46D030`. Check with
>    `giten.width.findings(s)`, which must return nothing.
> 3. **Unit names are 15 characters, not 16.** The field is 16 *bytes* including
>    the NUL terminator (`giten.spans.PNAME_LEN`).
> 4. **`1F01` is a name seam, not an unrenderable trigger.** The body lists `1F01`
>    among tags with "no renderable text". It prints a party member's name at
>    runtime and the row's text continues from it -- so the row before ends with a
>    trailing space and the `1F01` row begins mid-sentence. Measure such a row as
>    `previous_row_en + 15 columns of name + this_row_en`.
>
> Also obsolete: the file/tool paths in section (d) refer to the old `tools/`
> layout. The current pipeline is `giten/` with `docs/format-notes.md`.


Companion document to `translation/glossary.tsv`. Covers the register/conventions the
previous translator already established (so the remaining ~13% — demon negotiation,
choice menus, story tails — matches seamlessly), character voice notes, a demon-voice
guide for negotiation, and the hard technical constraints of the file format.

Evidence throughout is cited by file path; short quotes (single lines) are given as
proof, not as a substitute for reading the source file.

---

## a) Register and conventions of the existing translation

**Honorifics:** mostly dropped, with two specific exceptions kept romanized:
- `-kun` and `-chan` ARE kept: Yuuka calls the protagonist "Katsuragi-kun" consistently
  (~15 instances across early files); a stray "Emi-chan" also occurs.
- `-san` and `-sama` are NEVER kept in translated text (0 hits across the sampled
  98 story files) — they are dropped entirely or converted to an English title
  instead, e.g. demon lords become "Lord Bael"/"Lord Dantalion"/"Lord Adonis", and a
  bartender addresses the protagonist as "Mister Katsuragi" (`m/MS00B4.BIN`).
- One still-untranslated line shows what happens to "-san" once it does get
  translated: 「園田さん！！」("Sonoda-san!!") appears in unfinished text in the
  MS0054 area — expect it to drop to plain "Sonoda!!" once translated, matching
  the established pattern.

**Name order:** Japanese order is kept (surname given first) for full names —
"Katsuragi Ayato", "Souma Sanshirou" — but everyday speaker tags use whichever single
name is that character's established "call name" (see the per-character table below),
not a fixed rule of "always surname" or "always given name".

**Speaker tags vs. narration vs. speech:** the format has three tag types and the
translation keeps them structurally distinct rather than using punctuation to imply
dialogue:
- Narration (`1FD0` window-open / `1FBA` narration line) — plain, unquoted third-person
  prose, e.g. `m/MS0000.BIN`: *"That person quickly notice you back, and rushes over
  to you."*
- A speaker-name line (`1FD2`), e.g. `Yamase:`, immediately followed by
- The spoken line itself (`1FD3`), also unquoted by default, e.g. *"Yo... It's been a
  while."*

Actual quotation marks (`"`) are reserved for a phrase quoted *within* a line, which
is rare (~29 out of ~10,370 dialogue lines sampled), e.g. `m/MS0000.BIN`: *"...I
thought 'Fuck this'."* (note: single quotes used for the nested quote-within-a-line,
double quotes never nest inside the outer unquoted dialogue).

**The `＞` prompt character:** rendered as a literal ASCII `>`, always prefixed
directly to system/choice-prompt lines with no space, e.g. `>What will you do?`,
`>Are you sure about this?`, `>AMS map data found. Download it?`. Individual choice
options themselves (the `1FB2` tag) do NOT get the `>` prefix — only the framing
question above the list of options does.

**Ellipses:** plain ASCII `...` throughout (2,786+ occurrences); the Unicode `…`
character is essentially never used in translated English (the one hit found was
inside still-untranslated Japanese text). Use `...`, not `…`, in all new text.

**Quotes and dashes:** straight double quotes only (no curly/smart quotes); no em-dash
usage anywhere — interruptions and trailing-off are both handled with `...`.

**Punctuation doubling:** `!?` is house style (212+ occurrences, e.g. *"Y-Yamase!?
You're alive?"*); `?!` is rare (3 occurrences) — prefer `!?`. Doubled `!!` for emphasis
is common (*"Emi! Emi!? EMIII!!"*).

**Full-width Japanese punctuation (`！`, `？`, `「」`):** never carried over into
translated English lines — always converted to standard half-width ASCII punctuation.
The only full-width punctuation surviving in the dumps is inside text that is still
untranslated Japanese.

**Stutters / interruptions:** rendered with a hyphen, e.g. "Y-Yamase!?", "Wh-What the
hell". Keep this convention for any new nervous/shocked dialogue.

**Currency capitalization:** always **"Macca"**, capitalized (proper noun / the
official SMT spelling). The corpus was overwhelmingly lowercase "macca"; all 35
lowercase instances were rewritten in the 2026-09 editorial pass (Inconsistencies
item 3). Write "Macca" in all new text.

---

## b) Character voice notes

Evidence-based notes for the cast, drawn from actual translated lines. All quotes are
single lines from the cited file.

- **Katsuragi Ayato** (protagonist) — addressed as "Katsuragi" by most people, "Ayato"
  only by the closest characters in urgent moments (Nishino: *"Ayato! The ID is
  58147! Enter it!"*), and "Katsuragi-kun" consistently by Yuuka. His own lines are
  terse and action-driven: *"I hear you!"*, *"Let's go!"*, *"Shut up! Guards, over
  here!"* Note: **"Souma Yukihito"**, named in the task brief, was not found anywhere
  in the sampled story files `MS0000.BIN`–`MS006D.BIN` — only in the unit-name table
  `p/` (see `tools/dumps/p_names.txt`, slot P2000). Treat this as either the
  protagonist's true/hidden name (revealed later in the story) or an unused
  placeholder until confirmed against content beyond MS006D — do not assume it is
  simply another name for Katsuragi Ayato without checking.
- **Tachibana Yuuka** — always "Yuuka:" as a speaker tag (surname never used as a
  tag). Warm, soft, contraction-heavy: *"Yep. We've gotta hurry, or we'll be late."*,
  *"Did you get everything, Katsuragi-kun?"*
- **Souma Sanshirou** — appears as "Sanshirou:" or "Souma Sanshirou:". Blunt/casual,
  occasional profanity: *"Hell yeah!"*, *"Shit..."*
- **Kirishima Emi** — always "Emi:" (758+ occurrences; "Kirishima" alone never used
  as a tag, only in the full self-introduction "Kirishima Emi"). Emotional,
  exclamatory, quick to anger or panic: *"Y-Yamase!? You're alive?"*, *"The hell did
  you just say!?"*, *"Wh-What the hell, Katsuragi!? What has gotten into you!?"*
- **Nishino (Yoshio)** — "Nishino:". Commanding under pressure (*"Kirishima!
  Hayasaka!"*, *"Check her pulse!"*), gentle in a domestic scene with his daughter
  Chita (`m/MS0029.BIN`).
- **Hayasaka (Tatsuya)** — "Hayasaka:". Hot-tempered: *"The hell!?"*, *"Who would
  ever want to be a demon's lackey!?"*
- **Kamikawa (Kouki)** — "Kamikawa:". Formal, dutiful, subordinate in tone to Sonoda:
  *"Yes sir."*, *"Sonoda. These guys are Devil Busters from Hatsudai!"*
- **Yamase (Isamu)** — "Yamase:". Brash survivor's-guilt voice, casual profanity:
  *"When the common folk started turning into demons, I thought 'Fuck this'."*, *"I
  got the hell out of there as fast as I could."*
- **Sonoda (Tetsuya)** — "Sonoda:" (also seen once as "Sonoda." — inconsistency, see
  below). Friendly-skeptical resistance-group leader: *"Come on, relax. We're on the
  same side here."*, *"Still, I've gotta ask... What are you guys doing out here?"*
- **Asuka Rui** — always "Rui:". Terse and urgent: *"Just a bit more!"*, *"The
  soldiers will be here any second! We've gotta hurry!"*
- **Newton** — a DOG, not a human character. All "lines" are onomatopoeia: *"Woof!"*,
  *"*Bark*!"*, *"*GRRRRRWL*!..."* Do not write English sentences for Newton.
- **Yamada Kazumi / Utsumi Shouko** — not located in the sampled story range
  (`MS0000.BIN`–`MS006D.BIN`); no voice evidence available yet. Flag for review once
  their appearances (likely later in the game) are identified.

---

## c) Demon voice guide for negotiation

`tools/dumps/negotiation_MS6xxx.txt` covers `m/MS6000.BIN`–`MS6016.BIN`,
`MS6100.BIN`–`MS610D.BIN`, plus a handful of one-off scripts (`MS6200`, `MS6300`,
`MS6400`, `MS6500`, `MS6800`–`MS6802`, `MS6F00`, `MS6F1F`).

**Structure:** `MS6000`–`MS6006.BIN` are shared system/menu text (the "how will you
speak to them?" framing, common battle-during-negotiation lines) rather than
distinct personalities — heavily interleaved with binary noise in the raw dump.
`MS6007.BIN` onward through `MS6016.BIN` are the actual reusable "personality
template" files: every one of them reuses the *same* response-record-ID skeleton
(the record tagged `#AA` is always the first-contact line, `#AB` is always the
"I'm in a good mood" line, etc.) just reworded in a different voice — confirmed
directly by comparing `MS6007.BIN` and `MS6008.BIN` record-for-record. `MS6100`–
`MS610D.BIN` are one-off named NPCs (cultists, a demon hunter, a fallen angel, a
math-babbling oddity) rather than repeatable "types", and are called out separately
at the end of this section.

All English lines below marked **(proposed)** are new writing for this style guide,
not existing translation — the negotiation script files are almost entirely
untranslated Japanese.

| File | Voice | Markers | Evidence (single lines, JP) | Proposed English voice + example lines |
|---|---|---|---|---|
| `MS6007.BIN` | Archaic old man (commoner register) | わし (I), お主/御主 (thou), じゃ/のう/わい sentence endings | "なかなかに　物分かりの良い奴じゃ" | Thee/thou archaic elder speech. (proposed) *"Aye, what business hast thou with an old fool?"* / *"Speak thy purpose, and be quick about it."* / *"Hmph. Thou hast some nerve."* |
| `MS6008.BIN` | Cold modern aristocrat (same template as 6007) | 私 (I), 貴様 (you), だ/だな endings | "私は　今　大変気分がいい" | Haughty, clipped formality. (proposed) *"I am in an excellent mood today. Consider yourself fortunate."* |
| `MS6009.BIN` | Boastful demon lord (hybrid of 6007/6008) | わし+我輩, 貴様, more physically threatening | "わしに出会ったのが　運の尽きと思う事だ！" | Threatening bravado. (proposed) *"You'll consider meeting me the worst luck of your life."* |
| `MS600A.BIN` | Rough/masculine tough guy | オレ (I), ぜ/ぜぇ/だぜ/かぃ endings | "オレの懐が　目当てってワケかい？" | Blunt street-tough diction, dropped g's. (proposed) *"Yeah? What's it to me?"* / *"Don't push your luck."* |
| `MS600B.BIN` | Childish/hyper "mascot" creature | オイラ (I), baby-talk endings, catchphrase ヒーホー | "ヒーホー！　出血だいさーびすでこいつをプレゼント！" | Exaggerated childish slang, nonsense exclamations. (proposed) *"Hee-hoo! Free stuff, free stuff!"* |
| `MS600C.BIN` | Rough/masculine, crueler | 俺 (I), ぜ/なぁ endings, laugh ケケケ | "ケケケ！　ムカつく野郎だ！" | Sneering, sadistic thug with a cackling laugh. (proposed) *"Kekeke! You call that trying?"* |
| `MS600D.BIN` | Archaic old man (commoner, distinct from 6007) | わし (I), お主, じゃ/のう/わい | "わしにラブコールでも　送りに来たのかの？" | Same archaic register family as 6007 — vary word choice to avoid duplicate lines. (proposed) *"Hmph. Thou hast some nerve."* |
| `MS600E.BIN` | Mechanical/foreign speaker | Dialogue rendered in full katakana (stylized "unnatural" speech), stiff ダ endings | "ワタシニ　惚レタノカナ？" | Clipped, toneless cadence, like a translated transmission. (proposed) *"Query: what is your purpose here."* |
| `MS600F.BIN` | Elegant/archaic noblewoman | わらわ (I, archaic feminine), そなた (thou), かえ/ぞえ/のじゃ endings | "そなたなぞ　もう知らぬわ！" | Haughty period-drama noblewoman. (proposed) *"Speak thy business, and be swift about it."* |
| `MS6010.BIN` | Bratty gyaru/valley-girl teen | アンタ (you, rude/casual), わよ/のぉ/じゃん endings | "アンタなんか　大っキライ！！" | Valley-girl casual, "like"/"totally". (proposed) *"Ugh, whatever, I so don't care."* |
| `MS6011.BIN` | Mature, seductive "onee-san" | 貴方 (you, intimate), わ/のよ/かしら feminine endings, calls player "ボウヤ" (boy) | "調子に乗るんじゃないわよ　ボウヤ！" | Sultry, condescending, calls the player "boy". (proposed) *"Don't get cocky with me, boy."* |
| `MS6012.BIN` | Polite/refined lady (keigo) | Full です/ます keigo + feminine わ endings | "調子に乗らないで頂きたいですわ！" | Prim, formal — distinct from 6011's casual seductiveness. (proposed) *"How terribly forward of you."* |
| `MS6013.BIN` | Zombie/ghoul, male | おで instead of おれ, slurred consonants throughout | "おでにも　くでよぅ" | Slurred, groaning undead speech. (proposed) *"Gimme... somethin' t'eat..."* |
| `MS6014.BIN` | Zombie/ghoul, female (pairs with 6013) | Same slurring pattern, feminine わ/のぉ endings | "友達　友達！" | Slurred undead speech, feminine. (proposed) *"We're... the same, y'know..."* |
| `MS6015.BIN` | Hungry ghost (Gaki-type), male | Unslurred; obsessive hunger/curse themes, オレ (I) | "オレは生きた肉を食いたい！" | Ravenous, obsessive, unsettling. (proposed) *"You don't know this hunger. You couldn't."* |
| `MS6016.BIN` | Hungry ghost (Gaki-type), female (pairs with 6015) | Unslurred, 私/わ feminine endings, same hunger themes | "私は生きた貴方を食べたいのぉ！" | Ravenous, obsessive, feminine. (proposed) *"I want to eat you. While you're still warm."* |

**Unique named NPCs (MS6100-series) — track separately, not as reusable "types":**
`MS6106.BIN` (Ishtar-cult devotee, polite keigo), `MS6107.BIN`/`MS6109.BIN`
(Bael-cult fanatics, formal vs. rough registers), `MS6108.BIN` (anti-demon human
vigilante ideologue), `MS610A.BIN` (a fallen angel, cold/formal/hostile to "God's
agents"), `MS610C.BIN` (a bizarre NPC reciting multiplication-table trivia, comic
relief). None of these voices repeat elsewhere in the corpus, so don't generalize
their style guide entries onto other files.

---

## d) Technical constraints

**Container/encoding** (see `README.md` and `tools/bin_tools/giten.py`): each `.BIN`
is `[u16 LE length header][XOR-chained body]`; script records are
`[id:u8][len:u16 LE][data]`.

**Control tags that MUST be preserved, in order, exactly as found** (from
`tools/bin_tools/giten_lines.py` and `tools/bin_tools/msparse.py`):
- `1F D0` — window/narration open
- `1F D1` — close window (also observed reused for the `>` prompt line itself in
  practice — treat any `1FD1`-tagged text as a framing/prompt line)
- `1F D2` — speaker name
- `1F D3` — speech line
- `1F B1` / `1F B2` / `1F B7` — open choice list / one choice option / close choice
  list
- Other `1F xx` tags appear with no renderable text attached (e.g. `1F03`, `1F04`,
  `1F7F`, `1F83` seen in `m/MS0000.BIN`, `MS0007.BIN`, `MS0011.BIN`) — these are
  almost certainly sound/flag/animation triggers bound to that exact script position;
  never delete or reorder them relative to the surrounding text even though they
  carry no visible words.
- `08 nn` — dictionary-word escape: substitutes entry `nn` from the shared dictionary
  `m/MS7F07.BIN`. When a tool shows this un-expanded it renders as `{XX}` (hex).
  Treat `{XX}` tokens as opaque and do not alter their position — they are reused
  word/phrase fragments (verified example from `tools/bin_tools/giten_text.py`
  header comment: `御主に仕/える/くらい/なら` — a dictionary word filling in a verb
  ending mid-sentence). If you must rewrite a line containing `{XX}`, either keep an
  equivalent word in the same grammatical slot or coordinate with whoever manages
  the dictionary file, since the same dictionary entry is reused across many lines.
- `0A` (raw byte, renders as `\n`) — explicit line break within the same text box.
  Preserve exactly where the line wraps in the original if the translated line is
  short enough to fit; otherwise it's fine to move the break, but keep the total line
  count the same unless you've confirmed the box can grow.
- `1E` (raw byte, per `tools/bin_tools/msparse.py` header comment) — page-break /
  wait-for-input control byte. This is the concrete byte behind the task brief's
  "`<wait>` page breaks" — dump tools render it as `<1E>`. Never remove it; it is
  what makes the game pause for player input before continuing.
- `00` (raw byte) — end of text run.

**Format specifiers:** exe strings use standard C printf specifiers — `%d`, `%s`,
`%c`, `%ld`, `%.1d`, `%5d`, `%-16.16s`, `%7ld`, etc. (see `tools/exe_analysis/pairs.txt`
for many live examples, e.g. `仲魔 %5d／%2d` → `Demon%5d／%2d`). These must be
preserved verbatim, in the same order and with the same width/precision modifiers,
since the game's rendering code does not re-parse or validate them — a mismatched
specifier will misread memory or crash.

**Status-effect name limit — hard 7 characters:** confirmed from
`tools/exe_analysis/pairs.txt` (cluster at file offset `0x62fe8`–`0x630f8`): this is
a fixed-width table, 8 bytes per slot (7 displayable ASCII characters + a null
terminator), verified by the constant 8-byte stride between every entry. Every
status name in the existing translation that doesn't fit is abbreviated with a
trailing period (`Paral.`, `Posse.`, `Berse.`, `Suffo.`, `Vamp.`, `Hallu.`) — follow
this exact convention (word-stem + period) for any new status name, never a
different abbreviation style. Do NOT assume this same hard limit applies to other
short UI strings — the negotiation "attitude" words (`哀願的`/`友好的`/`超敵対的`/
`敵対的`/`通常`, at file offset `0x66858` onward) are a *different*, non-fixed-width
cluster of ordinary consecutive null-terminated strings (variable gaps of 8–16+
bytes between entries) — they are not proven to share the 7-character cap. Keep them
short as a matter of taste/HUD aesthetics, but don't force an unnatural 7-char
abbreviation on them without evidence the field actually requires it.

**Unit name limit — 16 characters, not 15:** the task brief cites a 15-byte limit,
but direct evidence from `tools/dumps/p_names.txt` shows several names are already
truncated at exactly **16** ASCII characters, e.g. `Beelzebub's Swar` (16 chars,
clearly cut from "...Swarm"), `Shikijo Innen Re` (16 chars, cut from "...Rei"),
`Gabriel Ratchets` (16 chars), `Goat of Fertilit` (16 chars, cut from
"...Fertility"), while `Dog of New Moon` fits at exactly 15 with no truncation and
`Dog of Full Moon` fits at exactly 16 with no truncation. This is consistent only
with a 16-byte field, not 15 — use 16 characters as the hard cap for new/edited unit
names, and note the discrepancy with the original task brief.

**Character-width / line-box constraint:** per the task brief, English text is drawn
at roughly half the pixel width of Japanese (8px/char vs. 16px/char), so an English
replacement line may run up to roughly 2x the original Japanese character count
before overflowing the same on-screen box. **The exact pixel window width itself is
still unverified/TBD** — this document does not have a confirmed number, and no
tooling in `tools/` currently measures it. Treat "~2x Japanese character count" as a
rule of thumb, not a hard guarantee, until another pass confirms the real box width
in pixels.

**Round-trip safety:** `tools/bin_tools/giten_pack.py` verifies byte-exact
encode/decode round-trips on all game files — any new text must still pass this
check after packing (run `python tools/bin_tools/giten_pack.py` per the README).

---

## e) Inconsistencies found in the existing translation

Status key: **RESOLVED** = decided and applied corpus-wide in the 2026-09 editorial
pass (see `translation/glossary.tsv` for the citation-bearing entry); **OPEN** = still
needs a decision or a separate pass. Do not silently propagate an OPEN item into new
text.

1. **RESOLVED — "Panic" used for two different status ailments.**
   `tools/exe_analysis/pairs.txt` shows both `恐慌` (offset `0x63050`, dread/rout) and
   `混乱` (offset `0x63078`, confusion/disorientation) rendered "Panic" in the exe's
   fixed-width status table. **Decision: 恐慌 = "Panic", 混乱 = "Confusion".** The text
   tables already observed this split (`m/MS7F06.BIN` 0:C0 "fallen into a panic" vs
   0:49 "Thrown into confusion!"), so no table rows needed rewriting. The exe's own
   7-character slot still needs the abbreviated **"Confus."** for 混乱, following the
   house word-stem+period convention — that exe edit is **OPEN**, since this pass did
   not touch the executable.

2. **RESOLVED — "Baal" vs "Bael".** The Japanese source itself uses *both* バール and
   バエル for the same demon lord and his cult, and the shipped English was already
   inconsistent about it in *both* directions: it rendered バエル as "Baal" in 51 places
   and as "Bael" in 32. **Decision: "Baal" everywhere** — "Lord Baal", "Baal cult",
   "Baal Soldier", "Baalite". 279 occurrences of "Bael" plus 7 of "Baelite" were
   rewritten, including the MS6107/MS6109 cult-fanatic files, the place names
   "Baalite Base"/"Baalite Temple" (`m/MS0035.BIN`) and the `p/_P_NAMES` unit-name
   slot. No "Bael" spelling is retained anywhere in `text_v2/`.

3. **RESOLVED — "macca" vs "Macca".** **Decision: always capitalised "Macca"** (proper
   noun, official SMT spelling). 35 lowercase occurrences rewritten corpus-wide.

4. **RESOLVED — "DCS" (exe) vs "DDC" (story text).** **Decision: match the shipped
   exe.** The exe knows exactly three program names — DDS, DCS, AMS
   (`pairs.txt` off `0x664bc`, `0x66510`, `0x66530`) — so the story text's "DDC" was
   drift. 8 "DDC" and 3 "D.D.C." occurrences rewritten to "DCS"/"D.C.S." across
   `m/MS001E`, `MS0028`, `MS0058`, `MS006A`, `MS003D.BIN`. **"DAS" is not attested in
   the exe at all** and has been left as-is in prose; if it is ever added to the exe,
   match whatever spelling ships there.

5. **RESOLVED — typo "Baal Solider".** Both instances in `m/MS000D.BIN` fixed. The
   colon-less "Baal Soldier" speaker tag in `m/MS0061.BIN` now carries its colon.

6. **RESOLVED — typo "Bartended"** (`m/MS0040.BIN`) fixed to "Bartender".

7. **RESOLVED — speaker-tag punctuation drift.** Every `1FD2` speaker-name span now
   ends in a colon and carries no trailing space. Fixed: "Sonoda." ×5, "Emi." ×4,
   "Woman." ×1, `"Woman":` ×1, bare "Scientist" ×10, bare "Dantalion" ×4, bare
   "Baal Soldier" ×1, and one trailing space. **Important scoping note for future
   passes:** the same *strings* also occur as name-pool words (`m/MS7F00.BIN`) and as
   unit names (`p/_P_NAMES.tsv`), where a colon must **never** be appended — restrict
   any tag fix to rows whose `tag` column is `1FD2`.

8. **RESOLVED — full-name vs given-name-only tags.** "Nishino Chita:" ×2 in
   `MS0054.BIN` unified to "Chita:" (the form used 16× elsewhere). The "Take Katsumi:"
   tag vs "Katsumi" in `MS0006.BIN` narration is left alone — a speaker tag and a
   narration mention are allowed to differ.

9. **RESOLVED — capitalisation/hyphenation drift on demon-name tags.**
   "Shuten Douji:" ×3 → "Shuten-Douji:"; "Yoshino-Hime:" ×3 → "Yoshino-hime:";
   "Young man:" ×2 → "Young Man:"; "Mystery Man:" ×3 → "Mysterious Man:" (same
   character, same file `MS005D.BIN`). Majority form won in each case.

10. **OPEN — protagonist given-name order flips within `m/MS0006.BIN`.** Both "Ayato
    Katsuragi..." (×3) and "Katsuragi Ayato..." (×1) appear for the same character.
    Surname-first is used everywhere else and matches the exe's name table — not
    changed in this pass because it is prose rewriting rather than a mechanical
    substitution.

11. **OPEN — `COMP` (exe battle-menu label) vs `Arm Terminal` (story prose).** Still
    unreconciled; both are in use and neither is wrong in its own layer. The glossary
    keeps separate entries. Deciding this means editing the exe, which this pass did
    not touch.

12. **PARTLY RESOLVED — minor prose typos.** Not exhaustively swept. `m/MS0040.BIN`
    "Bartended" is fixed (item 6). Still **OPEN**: `m/MS00B5.BIN` *"...in truth, **his**
    just a little kid."* (should be "he's"); `m/MS00B8.BIN` *"Oh, I have no
    **interested** in women."* (should be "interest"); `m/MS0103.BIN` *"A **toke** of
    our appreciation."* (should be "token").

13. **OPEN — `et/ET0000.BIN`'s race table has one garbled entry.** The stray `"Z辱"`
    fragment at offset `0x9e4`, between "God" and "Undefined", is unchanged. `ET*`
    files have no record layer, so they are outside the v2 editable set.

### Decisions added by the 2026-09 editorial pass

14. **RESOLVED — ペンタグランマ: "Pentagramma".** Batches had produced "Pentagram",
    "Pentagramma" and "Pentagrammar". It is a proper noun naming the resistance
    faction, and **every one of the 118 occurrences in the corpus refers to the
    faction, none to the five-pointed star**, so there is no context where the shorter
    "Pentagram" needs preserving. 93 occurrences rewritten.

15. **RESOLVED — 合体: "Fusion" / "fuse".** The glossary previously guessed "install",
    reading across from the Arm-Terminal program metaphor. `m/MS003E.BIN` (the fusion
    facility, 28 instances) is unambiguously demon fusion. Use **"Fusion"** as the
    noun/facility term and **"fuse"** as the verb; 合体材料 = **"fusion material"**.
    8 rows rewritten across `MS600C`, `MS600E`, `MS600F`, `MS6106`–`MS6109`.
    "install" remains correct for actual DDS/DCS/AMS program installs — do not
    sweep it blindly.

16. **RESOLVED — 悪魔人: "Demonoid".** The term had three renderings: the speaker tag
    "Demonoid:" (`MS0008.BIN`, 13), the speaker tag "Tainted:" (`MS0063`, `MS0067`,
    `MS0069.BIN`, 15), and prose "demon-man"/"demon-woman" (`MS005C.BIN`).
    **Decision: "Demonoid"** — it is the word these characters use of *themselves* in
    dialogue (*"Demonoids are pretty much everywhere, but people tend to look down on
    us."*), so it reads as the in-world term rather than an outsider's slur. The 15
    "Tainted:" tags were rewritten. **OPEN:** the descriptive prose in `MS005C.BIN`
    still reads "demon-man"/"demon-woman"; left as narration wording for a future pass.

17. **RESOLVED — trailing pool calls standing in for Japanese grammar.** 58 finished
    English lines ended on a raw `{02:0A}` token, which renders the Japanese negative
    ending ません after the English. Several had left the *negation itself* in the
    token, so the English said the opposite of the source — e.g. `MS6001.BIN` 4:5D
    read "That sounds familiar" for 聞き覚えがありませんね ("that does *not* sound
    familiar"). All 58 rewritten to carry their own meaning with the token dropped.
    A further 173 `{02:09}` tokens (which render a full-width `・・・`) were replaced
    with the house-style ASCII `...`.

18. **RESOLVED — recurring battle-log flavour lines.** Same Japanese now gets the same
    English across `MS6002`–`MS6006` and `MS7F06`: 「{04:EF}は去ろうとする」→ "is about to
    leave", 「{04:FF}は幸せだ」→ "is happy.", 「{08:31}の鉄拳が」→ "Rui's Iron Fist",
    「後退できない！」→ "Can't retreat!". **Deliberately NOT unified:** the
    `MS6007`–`MS6016` personality files share a record skeleton and *are supposed to*
    reword the same Japanese in different voices, and two apparent MS6006/MS6004
    divergences turned out to be context-dependent joins with the following span.

19. **RESOLVED — glossary negotiation verbs, with a width caveat.** Menu verbs now
    follow the glossary (「何かくれ」→ "Give Me Something", 「怒る」→ "Get Angry",
    「去れ」→ "Leave", 「威嚇射撃」→ "Warning Shot", 「様子を見る」→ "Wait and See",
    「近づく」→ "Approach", 「肉をあげる／骨をあげる」→ "Give Meat"/"Give Bone").
    **But the glossary form only applies where the menu's declared width allows it.**
    `m/MS610D.BIN` declares 10 columns and `m/MS6200.BIN` declares 6 and 8, so those
    menus keep sanctioned short variants: "Exorcise" (成仏させる), "Observe" (様子を見る),
    "Kind" (友好的), "Harsh" (威圧的), "Get Mad" (怒る), "Warning" (威嚇射撃). Always
    check the `menu option, declared width N columns` note before substituting.

20. **RESOLVED — stray leading half-width kana glued to speaker tags.** Decode noise
    such as `ﾒYuuka:`, `ﾒRui:`, `ﾒDantalion`, `ﾒMurmur:`, `ﾒAdonis:` has been stripped
    from the affected spans (`m/MS001E`, `MS0031`, `MS002B.BIN`).

---

## Sources consulted

- `tools/dumps/negotiation_MS6xxx.txt`, `tools/dumps/ID_choice_menus.txt`,
  `tools/dumps/untranslated_choices.txt`, `tools/dumps/p_names.txt`
- `tools/exe_analysis/pairs.txt`, `english_inventory.md`, `sjis_inventory.md`
- `tools/bin_tools/giten.py`, `giten_pack.py`, `giten_lines.py`, `giten_text.py`,
  `msparse.py` (format/tag documentation)
- Direct dumps via `giten_lines.py`/`giten_text.py` of `m/MS0000.BIN`–`MS0024.BIN`
  (sampled), `et/ET0000.BIN`, `et/ET0001.BIN`, `et/ET0004.BIN`, `et/ET0010.BIN`,
  `et/ET0101.BIN`
- A full pass over all 98 files in `m/MS0000.BIN`–`MS006D.BIN`, all of
  `m/MS00A0.BIN`–`MS00AE.BIN` and `m/MS00B0.BIN`–`MS00B8.BIN`, and the 12 existing
  files in the `m/MS0100.BIN`–`MS0115.BIN` shop range
