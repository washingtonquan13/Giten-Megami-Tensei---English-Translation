# What the tooling does not know

Every re-adopted module carries an entry here.  An entry is closed only by evidence from the exe or the tracer, never by a plausible theory.

## container / records
- **A record may not exceed 32,767 bytes** (closed 2026-09-04 by the tracer + disassembly of the loader `0x43ABC0`: the per-record growth delta is a signed 16-bit value; over 0x7FFF it goes negative, the shrink path runs and the game crashes on load).  The original's largest record is `m/MS006A` r00 at 28,291 bytes -- the BBS -- so English there has 4,476 bytes of headroom.  Enforced by `check` (`record-size`, predicted from the tables) and `audit` (measured on the build).
- Record-count words that overstate the body (`m/MS600A`, `m/MS610B`, `et/ID00A2`, `et/ID00A3`) and trailing bytes are copied verbatim; what the engine does with them is unknown.
- Containers with duplicate record ids and branches (`m/MS6000` c0/1/8, `m/MS6800` c0, `m/MS610B` c15) are not editable.

## vmops / opcodes.json
- 267 opcodes are typed as consuming no operands because the static tracer took the fall-through; 148 records cannot be tiled (123 before the switch grammar; the 25 newly refused ones tiled by luck and were editable).  `1F82` is a known offender: its operand model eats the next opcode's `1F` prefix (`m/MS0002` r26, `m/MS0015` r02, `m/MS0032` r22).
- ~~`1F01 nn` followed by `00`: meaning unknown.~~ **Closed 2026-09-04 by trace:** `1F01 nn` prints runtime string *nn* -- `00` is the player's name (the trace shows the PC jump to offset 0 of the name buffer and read 葛城史人), other indices print counters (`６`). The `00` after it is that string's terminator. v0.05 stripped all 3,240 and hard-coded names; we keep them.
- ~~The byte after a name macro in the post-menu dead zone (`00 02 01 6a`): meaning unknown.~~ **Closed 2026-09-04:** those bytes are a switch-table case (`[case 02][kind 01][rel16]`, format-notes 2.12) that the old five-byte model for `0F` had spilled into the text.  They are operands now and never reach a table.
- Switch tables (`0E`/`0F` and 14 relatives) are decoded from the handler; a `kind` byte other than 0/1 refuses the record.  Which records those are is known (25 that used to tile by luck), what their real layout is, is not.
- `NOT_A_BRANCH = {010, 011, 182}` is statistical (target lands on an instruction at or below chance).  `017` is in the grey zone on the original (48.7% vs chance 43%) and is still relocated.
- ~~Our expression model disagrees with the engine for 67 of 94 selectors.~~ **Closed 2026-09-06: it does not.  The extraction was wrong, twice over.**  `tools/extract_expr_nodes.py` carried its own control-flow walker which, on a `call`, compared the target against the readers it knew and otherwise stepped *over* it — so every kind handler that reads through a helper reported "consumes nothing".  Kind `0x0D` (selectors `19`–`23`) is the proof: `0x00436C49` calls `0x00438C40`, which is `call READ_U8; call READ_EXPR_DEREF`, i.e. `u8 + expr` — exactly what `opcodes.json` already said.  Separately, **there is a third stream reader, `0x00438FE0` (4 bytes, fetcher `0x438EC0`)**, alongside `0x00438FA0` (1, `0x438E50`) and `0x00438FC0` (2, `0x438E80`); not knowing it made selector `0x02` look like a leaf when it is a `u32`.  Following delegation and counting all three readers, the engine agrees with `opcodes.json` for **92 of 94 selectors**.  The extractor now reuses `tools/opcode_operands.py`'s walker instead of keeping a second one that could drift.
- **Selectors `0x4B` and `0x4F` are context-dependent in the engine** (kinds `0x2C`/`0x30`, via callees `0x00437440`/`0x004373E0` whose paths disagree).  No constant payload can be correct for them; `opcodes.json` keeps `['expr']` for both, which is a choice, not a derivation.
- `tools/opcode_operands.py`'s `_at()` is **order-dependent**: it will answer from a previously-cached 0x200-byte linear sweep even when the address is not an instruction boundary in that sweep, returning misaligned instructions.  It reported selector `0x59` as a leaf in a full run and as `u8 + expr` when walked first in a fresh process.  Verify any surprising result by walking that address first, in its own process.
- The expression table was **not** what blocks the untiled records.  Of the 116 that do not tile, the failures concentrate on constructs the engine itself resolves at runtime: the switch reader `0x004327C0` has a caller-argument early-out (`cmpw $0x0,0x14(%esp); je`) that reads no bytes at all, and opcodes `0x009`/`0x00B` reach a context-dependent callee (`0x00434780`).

## codec
- One span in the original (`m/MS0061` 0:0B[32]) contains `FA 82` (冾, IBM extension); cp932 re-encodes it as the NEC duplicate `ED 65`.  Text tokens that do not re-encode to their own bytes are rendered as raw `{=HH}` tokens.

## script / relocation
- Branches whose target is strictly inside an edited span block the edit (115 lines ship untranslated).
- Text-capture mode (`1B`..`1C`, 256-byte buffer) is enforced by `check` (`capture`) from the static token walk; a region entered by a branch from elsewhere is not modelled.

## exe
- Debug-menu arming is unverified (the table at `0x468318` is not four contiguous pointers).
- `HKCU\Software\ASCII\GITEN_DDS\DevConfig` must exist at startup; written by `Config.exe`.

## overlay (runtime translation)
- Spans are diverted only when entered at their first byte; a branch landing inside a translated span shows the Japanese tail (same 115 lines `@noedit` blocks).
- `et/ID*` tables are read by other code paths, not the interpreter fetch; the hook does not cover them.
- Not yet play-tested as of 2026-09-04 evening; `docs/overlay.md` has the test setup.
