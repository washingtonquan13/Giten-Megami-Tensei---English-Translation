# Continuation plan

State as of 2026-09-04 (branch `development`, 18 commits ahead of `origin`, never pushed).

## Where things stand

| Stage | Status |
|---|---|
| Format reverse-engineering | Done. `docs/format-notes.md`, `docs/opcodes.json`. |
| Pipeline v1 (`tools/giten`) | Committed. Byte-exact identity build on all 844 files. **Cannot be used to build length-changed files** (seed rule, multi-container, rel16 relocation missing). |
| Pipeline v2 | **Landed and committed.** Default engine is now v2 over `text_v2/` (`text/` is the frozen v1 tables, kept for history). 84 tests green; identity build byte-exact; `verify` shows 0 decode and 0 tiling regressions on `build/ddswin_v2`. Migration carried 7,914 translations; 900 `@operand` rows re-opened with correct `jp`; 335 v1 translations could not be ported (listed in `build/migrate-report.txt`) and need redoing; 171 rows sit inside `@untiled` records and cannot be edited yet. Token syntax: `{01:03}` pool call with operand folded in, `{1E10:…}`, `{=HH}` raw byte, `reads:` in `note` gives the readable Japanese. |
| Glossary / style guide | `translation/glossary.tsv`, `translation/style-guide.md`. |
| Translation | 8,220 / 10,154 Japanese rows done (81%). All eight batches committed. 871 rows tagged `@operand` need a second pass after migration. 965 rows were never covered: `m/MS005A` (275), `MS005B` (208), `MS003E` (152), `MS006A` (131), `MS010A` (48), `MS005C` (26), `MS003A` (13), `MS006B` (13), `MS003F` (3), `MS0061` (3) — two translators misreported these files as already English — plus the name/word dictionaries `MS7F00` (61), `MS7F01` (14), `MS7F02` (17), which are inserted into text by opcodes 01–03 and need English too. 98 rows `@skip` (debug menu, garbage). |
| In-game testing | **Started by the user 2026-09-04.** First report: an early story gate not holding and crashes after the aptitude test. See *Play-test findings* below — one real pipeline defect found and fixed (98 corrupted bytes in 28 files); attribution of the reported symptoms is still open. |
| Build audit | `python -m tools.giten audit` compares a build to its source for control-flow equivalence. Clean on the current build. Run it after every `build`. |

Per-file status: `python -m tools.giten stats` (set `PYTHONIOENCODING=utf-8`). Fast cross-check that ignores malformed rows: count rows whose `jp` contains Japanese and whose `en` is non-empty and differs from `jp`.

## Usage-aware working rules

These exist because a session limit killed nine agents at once on 2026-09-03.

1. **One Opus agent at a time** for tooling or reverse engineering. **At most four Sonnet translators** in parallel, each on a disjoint file set. More parallelism only burns the session budget faster; it does not finish sooner once the limit trips.
2. Every agent saves each finished file to disk before starting the next. Commit each batch as it lands. Never leave finished work uncommitted.
3. Translators get the rules in `docs/pipeline.md` plus: 74 columns per narration line, 4 lines per page, 20 columns per choice option (1 column per ASCII char, 2 per full-width). Do not use the old "2× the Japanese" rule for options.
4. Do not run `check` from several agents concurrently on a half-written file; a malformed row in one agent's file blocks everyone's run. Run `check --skip-identity` between batches instead.
5. Validation is scripted (`check`, `tests.run`, `tools/scripts/quarantine_operands.py`). Never spend an agent on it.

## Next steps, in order

1. ~~Land pipeline v2.~~ Done 2026-09-04.
2. ~~Migrate.~~ Done; `text_v2/` is live and the CLI defaults to it.
3. ~~Second translation pass~~ Done 2026-09-04: all batches committed; 97.1% of spans done, every remaining empty row is tagged (skip/noedit/untiled). (Original scope: ~5,960 rows: the `{DICT:9x}` rows, and anything `unmatched` from the migration. Same briefs as before, with the v2 token syntax from the updated `docs/pipeline.md`.
4. ~~Consistency review~~ Done 2026-09-04 (commit 591964b): terminology unified, 775 dropped page waits restored, glossary 205 terms, checker 0 errors / 36 page-rows false positives (BBS screens drawn in a taller window than `width.py` models). (Original scope: terminology against the glossary, speaker-name forms, demon voice per pool file, the inconsistencies listed at the end of the style guide (Panic/Panic, Baal/Bael, macca/Macca, DCS/DDC), coined terms reported by each translator. Output: a list of row edits, applied by script, then `check`.
5. ~~Exe leftovers~~ Done 2026-09-04 (commit 71a71d5). (Original brief: one Opus agent; if it was cut off, a WIP snapshot of `tools/exepatch/`, `text_v2/exe/strings.tsv` and `tests/test_exepatch.py` is committed; a fresh agent should read those, then finish: run `python -m tools.exepatch check/build/verify`, write `docs/exe-patching.md`, confirm the translated rows in `strings.tsv` (attitude words, Analyze panel, Macca, Sougon fix, Confus.), and make `tests.run` green): a table-driven string patcher for `dds_en.exe` using `tools/exe_analysis/` (strings have unique `imm32` pointers, no `.reloc`; append a new PE section for space). Targets: the demon attitude words, the Analyze panel, マッカ, 立川, the shop total line, and the empty-name bug at file offset `0x67BD8`. Output `build/dds_en.exe`, never the game folder.
6. ~~Build and install into a copy.~~ Done 2026-09-04, reinstalled after the relocation fix below. `C:\Giten Megami Tensei - English - v0.05\test-install\ddswin` holds the v2 build. Its `dds_en.exe` is still the v0.05 one; the newly patched exe sits beside it as `dds_en_patched.exe` so the two variables can be changed one at a time. The original `Giten Megami Tensei - English\ddswin` is untouched. Rebuild after any table change with `python -m tools.giten build && python -m tools.giten verify && python -m tools.giten audit && python -m tools.giten install --from build/ddswin_v2 --to "<test-install>/ddswin" --yes`.
7. **Play-test** (the user). Two installs exist so a bug can be attributed:
   - `test-install\ddswin` = v0.05 exe + our translated data.
   - `vanilla-v005\ddswin` = untouched v0.05, for A/B. Saves are global (`GetWindowsDirectory()\save%04x.dds`, UAC-virtualised), so use a different slot per install or the two will share saves.
   Exercise every negotiation personality type, the offer menus, and the retranslated story scenes. Negotiation is the riskiest system: the original author needed a fix release for a conversation crash. Report crashes with the demon name and the last on-screen line; fixes are per-file repacks.
8. **Release.** Tag `v0.06`, ship a zip of the changed files under `ddswin/` plus the patched exe and a README; push `development` and merge to `main`.

## Known limitations to fix before or after v0.06

`build` skips 115 edits whose record has a branch landing inside the text span (source Japanese kept; safe). Fix in `tools/giten/script.py`: when a branch target falls inside a span, split the span at that target so each half is relocated separately, then re-run `build`/`verify`/`audit`. Until then those lines ship in Japanese.

`build` also leaves 972 `rel16` slots unrelocated because their displacement does not point at an instruction (see the 2026-09-04 fix below). Most are mistyped operands and want no relocation at all; a minority are real branches our tokenizer mis-tiles. Narrowing that set means improving `docs/opcodes.json`, not loosening the guard.

## Rebase on the Japanese original (2026-09-04, in progress)

**Decision:** stop diagnosing the hybrid; rebuild the patch on the untouched Japanese
original and validate one section at a time. Source: `D:\BrowserDownloads\Giten-Megami-Tensei-Tokyo-Mokushiroku_Win_EN_Patched-game\Giten Megami Tensei\ddswin`
(original data + XP compat patch only). The pipeline round-trips it byte-exact (1,103/1,103).

What was learned that the rebase encodes:

- The terminal regression (BBS skipped, test repeatable) is **ours** (A/B against vanilla v0.05). Never explained by static analysis; the incremental build is the diagnostic.
- Relocation must not touch opcodes `010`/`011`/`182` (`script.NOT_A_BRANCH`, measured). `audit` checks structure, branch destinations and image size; run it after every build.
- Sneikkimies' `dds_en.exe` repurposes half-width-katakana font slots `0xA1`-`0xDF` as a bold Latin alphabet. Our extractor rendered those as kana and translators deleted them. **The rebase ships the original font** (`build/dds_jp.exe` = original `dds.exe` + one byte: `0x509A9` `01`->`80`, SHIFTJIS charset so Japanese renders on en-US). Bold text is a later, deliberate feature.
- Text-capture mode: opcode `1B` on, `1C` off, `1E9C` clear, `1E9D`/`1E9E` render as a numeric/string field; 256-byte buffer, unbounded append. Original max 215 bytes/region. **TODO: checker rule, <=255 bytes of text between `1B` and `1C`.**
- v0.05 shipped seven 16-byte demon names in a 15+NUL field (renamed, `@renamed-15` in `text_v3/p/_P_NAMES.tsv`).
- v0.05 stripped ~3,240 `1F01 nn`+`00` idioms from the original. The rebase keeps them. Whether English renders cleanly with them in place is answered by the first play-test, not by more RE.

Tables: `text_v3/` (52,164 rows). `python -m tools.giten rebase` carried 14,479 of our translations and 25,194 of v0.05's (his now sit beside real Japanese and are reviewable; `@from-ours` / `@from-v005` / `@rebase-tagdiff` / `@rebase-unmatched` / `@rebase-new` in `note`). 7,779 rows untranslated, 3,785 spans the original has that v0.05 lacked. Report: `build/rebase-report.txt`. Checker on `text_v3` against the original: 34 `editable` errors (`MS610B` c15, duplicate ids in the original, stays Japanese), 34 `tokens` warnings (`ID00A2/A3`: our English references pool calls v0.05 added; review).

Installs (all use `dds_jp.exe`, original font):

| folder | contents | purpose |
|---|---|---|
| `test-install-JP\ddswin` | original data, untouched | **step 0**: identity — must play exactly like the original |
| `test-install-v3\ddswin` | original + English for `m/MS000*`, `m/MS001*`, `m/MS006A`, `m/MS7F0*` | **step 1**: the opening slice |
| `test-install\ddswin`, `test-install-B`, `vanilla-v005` | the v0.05-based builds | superseded; keep until step 1 passes |

Rebuild a slice: `python -m tools.giten build --root <JP> --text text_v3 --out build/ddswin_v3 --only "m/MS001*.BIN" ...` then `verify --root <JP> --dir build/ddswin_v3`, `audit --root <JP> --dir build/ddswin_v3`, `install --from build/ddswin_v3 --to <test-install-v3>/ddswin --yes`. Files not in `--only` build as identity, so the tree is always complete.

Next: (1) user plays step 0 then step 1 to the terminal; (2) if step 1 is clean, widen `--only` section by section; (3) add the capture-region checker rule; (4) review `@from-v005` rows against the Japanese; (5) translate the 7,779 + 3,785 remaining.

## If the two in-flight agents died

- Story tails MS0000–MS0031: landed and committed. The missed files listed in the state table above still need one Sonnet translator (same brief as the story batches; treat `MS7F00–02` as name/word pools: translate each entry as the bare word, no punctuation).
- Pipeline v2: check whether `text_v2/` or new modules under `tools/giten/` exist. If partial, hand the brief to a fresh Opus agent and tell it to build on what is there.

## Pipeline v2 brief (condensed)

Container: sequence of `[u16 hdr][hdr encrypted bytes]`; seed `(hdr>>8)^(hdr&0xFF)`; `plain[0]=enc[0]^seed`, `plain[i]=enc[i]^enc[i-1]`; on rebuild `hdr=len(body)`. Records: first decrypted u16 = record count; runtime index 0x400 bytes; PC is u16. Text is bare; bytes <0x20 dispatch by `docs/opcodes.json` (typed operands, recursive expressions, `list_ff`, data-dependent `1E 10`); 123 opcodes carry PC-relative `rel16` that must be relocated when text length changes. Opcodes 01–08 nn call record nn of `m/MS7F00–07`; `0B [rel16][u8][u8]` cond jump; `0C ff nn` goto; `0D ff nn` call. Widths: 76-column box (74 usable), 4 lines/page, choice options 20 columns. Untiled records (0.6%) are copied verbatim and tagged `@untiled`.
