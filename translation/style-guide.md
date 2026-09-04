# Giten Megami Tensei — English Translation Style Guide

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

**Currency capitalization:** "macca" is lowercase in the great majority of instances,
but two capitalized "Macca" slips exist — see the Inconsistencies section. Recommend
capitalizing "Macca" going forward (it is a proper noun / the official SMT spelling).

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

Flagging these for a cleanup pass; do not silently propagate them into new text.

1. **"Panic" used for two different status ailments.** `tools/exe_analysis/pairs.txt`
   shows both `恐慌` (offset `0x63050`, dread/rout) and `混乱` (offset `0x63078`,
   confusion/disorientation) translated identically as "Panic" in the fixed-width
   status table. These are mechanically distinct ailments — recommend renaming one,
   e.g. keep 恐慌 = "Panic" (or "Fear") and change 混乱 to "Confuse"/"Confus." (7
   chars) to disambiguate.
2. **"Baal" vs. "Bael"** used for the same demon lord. "Baal" dominates (13 files:
   `MS0003`, `MS0007`, `MS000D`, `MS0014`, `MS0015`, `MS0020`, `MS002B`, `MS002C`,
   `MS005C`, `MS005D`, `MS005F`, `MS0061`, `MS006C`, `MS006D.BIN`), but "Bael"
   appears in 5 files (`MS0002`, `MS0014`, `MS0030`, `MS005F`, `MS006D.BIN`) —
   and `MS0014`, `MS005F`, and `MS006D.BIN` each contain **both** spellings
   internally. The still-untranslated speaker tag `バール兵` ("Baal soldier")
   and `p_names.txt` (`P2199 Baal`) both support "Baal" as the intended spelling —
   recommend standardizing on it.
3. **"macca" vs. "Macca" capitalization.** Overwhelmingly lowercase "macca" (15+
   instances in `MS0007`, `MS0008`, `MS0019`, `MS003A`, `MS0065.BIN`), but two
   capitalized "Macca" instances slip in in the same file cluster. Recommend
   standardizing on capitalized "Macca" going forward (proper noun, matches the
   official SMT spelling named in the task brief).
4. **"DCS" (exe) vs. "DDC" (story text)** for what is presumably the same program
   name. The shipped exe translates `ＤＣＳ` as "DCS" (`tools/exe_analysis/pairs.txt`:
   `[TALK] DCSを所持していません` → `DCS not installed`), but every story-file
   appearance of the paired program alongside DDS/DAS instead reads "DDC" (`m/MS0007`,
   `MS001E`, `MS0028`, `MS0058.BIN`: *"I managed to download both DDC and DAS."*).
   Needs a decision on which is canonical before translating any new DCS/DDC
   reference.
5. **Typo "Baal Solider"** (transposed letters), `m/MS000D.BIN`, 2 instances,
   alongside the correct "Baal Soldier" used elsewhere (and once with no colon in
   `MS0061.BIN`).
6. **Typo "Bartended"** for "Bartender", `m/MS0040.BIN`, 1 instance; every other
   occurrence (`MS00B0`–`MS00B8.BIN`) correctly reads "Bartender".
7. **Speaker-tag punctuation drift** — most speaker tags end in a colon, but a
   handful use a period instead ("Emi." x4 in `MS000D.BIN`, "Sonoda." once in
   `MS000E.BIN`, "Woman." once in `MS0015.BIN`), and a few drop the trailing
   punctuation entirely ("Dantalion" with no colon in `MS002B.BIN` vs. "Dantalion:"
   elsewhere; "Scientist" with no colon in `MS0055.BIN` vs. "Scientist:" elsewhere).
8. **Same character split across full-name vs. given-name-only speaker tags.**
   Nishino's daughter is "Nishino Chita:" in `MS0054.BIN` but simply "Chita:" in
   `MS0029.BIN`. A minor character is "Take Katsumi:" as a speaker tag but just
   "Katsumi" in the accompanying narration in `MS0006.BIN`.
9. **Capitalization/hyphenation drift on demon-name speaker tags:** "Shuten Douji:"
   vs. "Shuten-Douji:"; "Yoshino-hime:" vs. "Yoshino-Hime:"; "Young man:" vs.
   "Young Man:" — all attested as separate strings for what should be the same name.
10. **Protagonist given-name order flips within a single file.** `m/MS0006.BIN`
    contains both "Ayato Katsuragi..." (given-name-first, 3 instances) and "Katsuragi
    Ayato..." (surname-first, 1 instance, *"So, it is you, Katsuragi Ayato..."*) for
    the same character in the same file — pick one order (surname-first is used
    everywhere else in the game and matches the exe's name-table ordering) and fix
    the outlier.
11. **`COMP` (exe battle-menu label) vs. `Arm Terminal` (story-text device name).**
    The shipped exe's combat command menu uses the bare acronym "COMP"
    (`tools/exe_analysis/english_inventory.md`, off `0x660b0`, in the
    ATTACK/SWORD/GUN/MAGIC/ITEM/COMP/EXTRA/RETURN/DEFENCE command row), while every
    narrative mention of the player's wrist device instead calls it "Arm Terminal"
    (`m/MS0000.BIN`, `MS0017.BIN`, `MS0019.BIN`). These probably refer to the same
    physical device from two different UI layers (a terse battle-menu label vs. full
    prose), but this was never reconciled by the previous translator — worth a
    decision on whether to rename the exe's "COMP" button to something that reads
    more naturally next to "Arm Terminal", or leave it as an accepted abbreviation.
12. **Minor prose typos** spotted in passing (not exhaustive — a full proofreading
    pass is out of scope here): `m/MS00B5.BIN`: *"...in truth, **his** just a little
    kid."* (should be "he's"); `m/MS00B8.BIN`: *"Oh, I have no **interested** in
    women."* (should be "interest"); `m/MS0103.BIN`: *"Here, take this. A **toke** of
    our appreciation."* (should be "token").
13. **`et/ET0000.BIN`'s race table contains one still-garbled entry.** Between the
    translated "God" and "Undefined" entries (offsets `0x9e0` and `0xa08`) sits a
    stray, apparently-corrupt fragment `"Z辱"` at offset `0x9e4` — worth checking
    whether this is a genuinely untranslated/broken race name or a decoding
    artifact.

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
