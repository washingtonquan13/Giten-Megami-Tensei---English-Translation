# Plan and status

The approved restart plan is the source of intent; this file is the running state.
Everything before the restart lives under `old/` (moved with `git mv`; history follows).

## Ground rules

- **Source is `original/ddswin`** — a read-only copy of the untouched Japanese release, checked
  against `original/MANIFEST.sha256` by `tests/test_restart.py`. Nothing ever points at D:.
- **Nothing ships that we cannot explain.** Every module has an entry in `docs/limits.md`; an
  entry closes only on evidence from the exe or the tracer.
- **`en` is written by someone reading `jp`.** Earlier translations arrive as `ref_en` (+ `ref_src`
  = `ours` / `v005`), never as `en`. `check` refuses an `en` without a `status` (`draft`/`reviewed`)
  and an `en` that copies `ref_en` without `reviewed`.
- **Sections, in story order, each played before the next is enabled.** A section is done when:
  untouched files are byte-identical (`build --only`), `audit` is clean, `check` is clean,
  `trace diff` against the JP run of the same route is clean, and a human has played it.

## Commands

```
python -m tests.run                                  # 46 legacy + restart tests, all against the original
python -m giten build --identity --out build/jp      # 1,103 files byte-exact
python -m giten verify --dir build/jp
python -m giten exe release | base | dev             # docs/exe-patches.md, asserting old bytes
python -m giten extract --family all                 # tables/ from the original
python -m giten carry                                # ref_en/ref_src from old/text_v3 (run once)
python -m giten check                                # tables + capture-region rule
python -m giten build --only "m/MS0017.BIN" --out build/en && python -m giten audit --dir build/en
python -m giten install --from build/en --to "<play>/en/ddswin" --yes
python -m giten trace selfcheck <play>/jp/ddswin/trace.bin
python -m giten trace diff <jp trace> <en trace> --build2 build/en
```

## Exe recipes (`docs/exe-patches.md`)

| build | contents |
|---|---|
| `base` | `dds_org.exe` + the XP r0.2β **code** patches (its font edits at `0x69E42+` are not carried) |
| `release` | base + `_setmbcp(932)` at `0x59DE0` + SHIFTJIS charset at `0x509A9` → Japanese renders on en-US, no Locale Emulator |
| `dev` | release + `.trc` section (224-byte PIC cave) with the three `exec_token` call sites redirected; writes `trace.bin` beside the exe |

Debug-menu arming is still an RE step (the table at `0x468318` is not four pointers). Not needed for the tracer.

## Play folders (`C:\Giten Megami Tensei - English - v0.05\play\`)

| folder | data | exes |
|---|---|---|
| `jp/ddswin` | identity | `dds.exe` (release), `dds_dev.exe` (tracer) |
| `en/ddswin` | identity + **diagnostic** English in `MS0017` only (`ref_en` promoted as `draft`, `build/tables_diag`) | same |

## Status (2026-09-04)

Done: restart layout; modules re-adopted with 46 tests against the original (re-baselined where v0.05
had set the numbers; one real fix: `FA 82` 冾 does not round-trip through cp932 and is now rendered
raw); `original/` manifest; exe patcher and all three builds; tracer built and verified (section,
redirects, PIC base); trace decoder/diff with self-check; tables with `ref_en` (14,479 ours /
25,194 v0.05); status and capture rules; `play/jp` and `play/en`.

Done 2026-09-04 evening: step 0 passed (Japanese renders on the release exe, no Locale Emulator); JP and EN traces
taken; decoder validated on real data (pc = token end, or the destination of a control opcode; self-check 72/3,592);
`1F01 nn` closed (prints runtime string nn: the player's name). The exam-loop route shows **identical flow** in both
builds — the reported loop is most likely an unreadable menu in a partial build (pool words still Japanese).

Open, in order:
1. Confirm with the user that the 'loop' was the menu (two Japanese options) and not a re-entry.
2. **Terminal crash**: `play/en` now holds MS0017 + MS006A + MS7F00-07 English (draft) under `dds_dev.exe`; the crash trace's last records name the step.
3. Then `02 01 6a` and capture-mode users; close each in `docs/limits.md`.
5. Section 1 (opening) translation: fill `en` from `jp` with `ref_en` as reference; `reviewed` before build.
6. Debug-menu arming; bold font as a deliberate feature; architecture graph from measured traces.
