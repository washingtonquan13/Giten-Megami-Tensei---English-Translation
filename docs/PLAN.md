# Continuation plan

State as of 2026-09-04 (branch `development`, 16 commits ahead of `origin`, never pushed).

## Where things stand

| Stage | Status |
|---|---|
| Format reverse-engineering | Done. `docs/format-notes.md`, `docs/opcodes.json`. |
| Pipeline v1 (`tools/giten`) | Committed. Byte-exact identity build on all 844 files. **Cannot be used to build length-changed files** (seed rule, multi-container, rel16 relocation missing). |
| Pipeline v2 | In progress by an Opus agent when this was written. Deliverables: seed-rule container codec, opcode-aware tokenizer, rel16 relocation, real width budgets, `migrate` command, output in `text_v2/`. If it never landed, redo it from the brief in the pipeline v2 section below. |
| Glossary / style guide | `translation/glossary.tsv`, `translation/style-guide.md`. |
| Translation | 7,617 / 10,154 Japanese rows done (75%). Negotiation complete. Story tails MS0000–MS0031 were in flight. 758 rows tagged `@operand` need a second pass after migration. 98 rows `@skip` (debug menu, garbage). |
| In-game testing | Not started. Game has not yet been launched on this machine. |

Per-file status: `python -m tools.giten stats` (set `PYTHONIOENCODING=utf-8`). Fast cross-check that ignores malformed rows: count rows whose `jp` contains Japanese and whose `en` is non-empty and differs from `jp`.

## Usage-aware working rules

These exist because a session limit killed nine agents at once on 2026-09-03.

1. **One Opus agent at a time** for tooling or reverse engineering. **At most four Sonnet translators** in parallel, each on a disjoint file set. More parallelism only burns the session budget faster; it does not finish sooner once the limit trips.
2. Every agent saves each finished file to disk before starting the next. Commit each batch as it lands. Never leave finished work uncommitted.
3. Translators get the rules in `docs/pipeline.md` plus: 74 columns per narration line, 4 lines per page, 20 columns per choice option (1 column per ASCII char, 2 per full-width). Do not use the old "2× the Japanese" rule for options.
4. Do not run `check` from several agents concurrently on a half-written file; a malformed row in one agent's file blocks everyone's run. Run `check --skip-identity` between batches instead.
5. Validation is scripted (`check`, `tests.run`, `tools/scripts/quarantine_operands.py`). Never spend an agent on it.

## Next steps, in order

1. **Land pipeline v2.** Verify: `python -m tests.run` green; identity build byte-exact; a synthetic lengthening edit in `m/MS0003.BIN` re-tokenizes with every branch landing on the same instruction. Commit.
2. **Migrate.** `python -m tools.giten migrate --from text --to text_v2`. Read the report: rows carried, unmatched, and the former `@operand` rows now rendering as clean tokens. Replace `text/` with `text_v2/` and commit. Rows whose `en` carries a token mismatch (an operand character that a translator dropped, e.g. `{01}#`) are errors: blank them for redo.
3. **Second translation pass** (Sonnet, 2–3 agents): the ~760 formerly quarantined rows, the `{DICT:9x}` rows, and anything `unmatched` from the migration. Same briefs as before, with the v2 token syntax from the updated `docs/pipeline.md`.
4. **Consistency review** (one Opus agent, read-only on game): terminology against the glossary, speaker-name forms, demon voice per pool file, the inconsistencies listed at the end of the style guide (Panic/Panic, Baal/Bael, macca/Macca, DCS/DDC), coined terms reported by each translator. Output: a list of row edits, applied by script, then `check`.
5. **Exe leftovers** (one Opus agent): a table-driven string patcher for `dds_en.exe` using `tools/exe_analysis/` (strings have unique `imm32` pointers, no `.reloc`; append a new PE section for space). Targets: the demon attitude words, the Analyze panel, マッカ, 立川, the shop total line, and the empty-name bug at file offset `0x67BD8`. Output `build/dds_en.exe`, never the game folder.
6. **Build and install into a copy.** `python -m tools.giten build`, then `install --to <copy of ddswin>`. Keep the original `ddswin` untouched.
7. **Play-test** (the user): get `dds_en.exe` running first (dgVoodoo2 `DDraw.dll` + `D3DImm.dll` beside the exe, windowed; see the investigation report). Then exercise every negotiation personality type, the offer menus, and the retranslated story scenes. Negotiation is the riskiest system: the original author needed a fix release for a conversation crash. Report crashes with the demon name and the last on-screen line; fixes are per-file repacks.
8. **Release.** Tag `v0.06`, ship a zip of the changed files under `ddswin/` plus the patched exe and a README; push `development` and merge to `main`.

## If the two in-flight agents died

- Story tails MS0000–MS0031: re-run one Sonnet translator with the original brief (files whose hex id is 0000–0031; most rows already English; fill empty `en` where `jp` is Japanese). Check `git status` first: any file it finished is on disk and only needs committing.
- Pipeline v2: check whether `text_v2/` or new modules under `tools/giten/` exist. If partial, hand the brief to a fresh Opus agent and tell it to build on what is there.

## Pipeline v2 brief (condensed)

Container: sequence of `[u16 hdr][hdr encrypted bytes]`; seed `(hdr>>8)^(hdr&0xFF)`; `plain[0]=enc[0]^seed`, `plain[i]=enc[i]^enc[i-1]`; on rebuild `hdr=len(body)`. Records: first decrypted u16 = record count; runtime index 0x400 bytes; PC is u16. Text is bare; bytes <0x20 dispatch by `docs/opcodes.json` (typed operands, recursive expressions, `list_ff`, data-dependent `1E 10`); 123 opcodes carry PC-relative `rel16` that must be relocated when text length changes. Opcodes 01–08 nn call record nn of `m/MS7F00–07`; `0B [rel16][u8][u8]` cond jump; `0C ff nn` goto; `0D ff nn` call. Widths: 76-column box (74 usable), 4 lines/page, choice options 20 columns. Untiled records (0.6%) are copied verbatim and tagged `@untiled`.
