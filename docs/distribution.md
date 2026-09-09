# Distribution plan

Written 2026-09-09, from the state of the tree that day. **Nothing here has been
built or tested.** It is a design and a set of measurements, kept so the release
does not have to be re-derived from scratch later.

Every claim below is marked **[measured]** or **[conjecture]**. The conjecture is
not decoration -- one of the load-bearing assumptions (what a clean retail
install looks like) has never been checked against an actual clean install, and
the patcher's whole entry path depends on it.

---

## 1. Is it a 1.0? No -- and the reason is one number

**[measured]** Coverage, 2026-09-09:

| tree | translatable rows | with English | characters |
|---|---|---|---|
| `tables/` (our own, tracked) | 45,083 | 18,497 (**41.0%**) | 613,646 |
| `build/tables_draft` (what installs) | 45,083 | 44,024 (**97.7%**) | 1,567,320 |

The gap is **25,527 rows and 953,674 characters** that exist only in the draft
tree, promoted from Sneikkimies' v0.05. That is roughly **61% of the shipped
text**, and `docs/todo.md` item 0 plus the v0.05 policy both say those lines are
drafts, never a direct build input.

**[measured]** `python -m giten check` on `tables/`: **1,479 errors**, 26,387
warnings, over 45,083 rows in 844 files.

    status 1309   editable 165   japanese 72   page-rows 52
    width-choice 26   overlay 4   width 3   record-size 1
    (missing 26,234, reported as warnings)

`japanese 72` is the one that shows on screen: rows that would render Japanese.

**Definition of 1.0, so it stops being a matter of opinion:** every shipped line
is either written by us or explicitly `reviewed`, `check` reports zero errors,
and the four known visible defects below are closed. Until then the honest label
is a public beta -- **0.9**.

**Known visible defects** (all in `todo.md`, none of them mysteries):

* district names draw in Japanese (`et/ET000D.BIN` has no extractor -- P1);
* the Dantalion-corridor directions regressed to Japanese, unexplained (P2);
* `m/MS00DD` rec `0x4C`, the damage line the player sees most, reads
  " HP of damage";
* ~26,200 rows have no English at all.

What *is* finished, and is why a beta is worth shipping: the container/opcode
model, the byte-exact identity build, the runtime overlay, the exe patch
accounting, and the combat pacing work -- 226 tests, all passing.

---

## 2. What the patch actually is

**[measured]** `play/en/ddswin` against `original/ddswin`: **2,333 files
identical, 453 changed, 2 added** (the other 16 "added" files are dev exes,
traces and dgVoodoo2, none of which belong in a release).

| what | count | note |
|---|---|---|
| `dds.exe` | 1 | 12,675,072 -> 12,685,312; +10,240 B of appended sections |
| `p/P*.BIN` | 432 | demon names, edited in place, every file the same size |
| `et/ID*.BIN` | 17 | item text |
| `et/ET0000`, `ET0004`, `ET0101` | 3 | race/lineage, skills, map labels -- rebuilt |
| **added** `overlay.dat` | 1 | 3,177,637 B -- the runtime English |
| **added** `et/et0102.bin` | 1 | 72,623 B -- the uncapped item database |

Nearly all the English is in `overlay.dat`, which holds our text plus FNV hashes
of the Japanese it replaces -- no game text of any kind.

---

## 3. Ship a patcher, not a repack

The release transforms the user's own install. Reasons that hold regardless of
anyone's view on copyright:

* **~3.5 MB against ~40 MB**, and an update is a new patcher rather than a full
  re-download.
* **It verifies its input.** A wrong or already-patched copy is refused with a
  message naming what was found, which removes a whole class of "it crashed"
  reports whose real cause is a different base install.
* **It demonstrates the project's own claim.** `docs/exe-patches.md` asserts the
  exe differs from the original by 1,016 accounted-for bytes. A patcher that
  reads the user's own pristine exe and writes exactly those bytes proves it. A
  repack asks to be taken on trust.
* **Backups.** `giten install` copies every file it will touch and re-reads the
  backup to verify it before overwriting anything. A repack offers no way back.

---

## 4. The trap: our base exe is not what a user will have

This is the part most likely to break on first contact, and it was nearly
missed.

**[measured]** `original/ddswin` contains **both** `dds.exe` and `dds_org.exe`:

| file | sha256 | what |
|---|---|---|
| `dds_org.exe` | `9b8105300b90931540a7e14372426747046c8423cec72dab8a2d6fe74a9b7a80` | pristine 1999 exe -- **our build base** |
| `dds.exe` | `76222fcf9c4f9c6228dce9c4a6957be2fcf2190bae7b135bbbe41774f3b653e5` | the XP tool's output |

**[measured]** `dds.exe` is `dds_org.exe` plus **233 runs, 2,097 bytes**: four
code runs totalling 149 bytes at `0x506BC` (20), `0x506D1` (122), `0x54B8B` (6)
and `0x5AB04` (1), and **229 font-table runs totalling 1,948 bytes** at
`0x69E42+`. Our `base` build applies the four code runs and drops the font
edits, so it differs from the XP tool's exe in exactly those 1,948 bytes and in
**nothing below the font table**. That confirms the recipe in
`exe-patches.md` end to end.

**[conjecture]** `dds_org.exe` exists in our reference *only because the XP tool
created it as a backup*, so a clean retail install has `dds.exe` = `9b810530...`
and **no `dds_org.exe` at all**. This follows from the tool's observed output
but **has never been checked against a clean install.** If it is wrong, the
entry path below is wrong.

A patcher that opens `dds_org.exe` by name therefore fails on exactly the users
it most needs to serve. **Identify the base by hash, not by filename.**

| state | `dds.exe` | `dds_org.exe` | action |
|---|---|---|---|
| A. clean retail | `9b810530` | absent | use `dds.exe` as the base |
| B. XP tool run | `76222fcf` | `9b810530` | use `dds_org.exe` |
| C. XP tool run, backup deleted | `76222fcf` | absent | **[conjecture]** skip the `xp` pass, already applied; warn that the half-width font stays the XP tool's variant, since we do not carry those 1,948 bytes |
| D. anything else | -- | -- | refuse, and print the hash found |

State D covers v0.05 already installed, a different release, or a modified copy.

---

## 5. The manifest is the wrong shape for a release

**[measured]** `original/MANIFEST.sha256` has 2,789 entries and describes an
**XP-patched** install, `dds_org.exe` and the XP tool included. A clean install
can never match it.

Replace it, for the patcher, with **per-file checks over only what is touched**:
the base exe strictly by hash, and each of the 453 data files against its
expected pre-patch hash. The builder already refuses on content mismatch; this
moves the complaint earlier and makes it legible -- `et/ET0004.BIN is not the
version this patch expects` rather than one all-or-nothing rejection.

**[conjecture]** The XP tool touches only `dds.exe`, so the 2,787 data files are
identical in both states. Unverified for the same reason as above. **Hashing one
clean install settles both this and §4 in a minute, and should be done before
any release.**

---

## 6. Recommended shape

A single-file `giten-patch.exe` (PyInstaller) wrapping what already exists:

1. ask for the game folder;
2. identify the base exe by hash (§4) and refuse state D with a clear message;
3. back up every file to be touched, re-reading the backup to verify;
4. `giten build` then `giten install` from the user's own files;
5. prompt for the combat-pacing choice (§7).

Steps 3 and 4 exist. Steps 1, 2 and 5 do not.

---

## 7. Obligations the release carries

* **Credit Sneikkimies prominently.** While v0.05 text is ~61% of the shipped
  characters this is an obligation, not a courtesy. It stays a courtesy after
  that.
* **Disclose the combat change.** The restored turn gauge is a gameplay change
  (`docs/pc98-comparison.md` §3, `combat-pacing.md` §4b). Say so plainly and
  offer the unmodified build -- `giten exe dev-x2` already produces it.
* **Do not bundle dgVoodoo2** unless its licence clearly allows redistribution;
  link it and document the setup (`giten-win11-compat` in memory).
* **Document the `DevConfig` registry requirement** -- `HKCU\Software\ASCII\
  GITEN_DDS\DevConfig` must exist; running `Config.exe` once creates it.
* **Ship a known-issues list** (§1) and a version string, so a bug report maps
  to a build.

---

## 8. Sequencing

Item 0 -- replacing the v0.05 text -- is the gate for 1.0 and nothing else on
this page depends on it. The patcher, the hash detection, the manifest rework
and the README can all be built and tested against the current beta, and none of
that work is invalidated by the translation catching up later.

The one task that should come first regardless, because two sections rest on it:
**get a clean retail install and hash it.**
