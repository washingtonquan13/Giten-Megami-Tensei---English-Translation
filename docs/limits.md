# What the tooling does not know

Every re-adopted module carries an entry here.  An entry is closed only by evidence from the exe or the tracer, never by a plausible theory.

## container / records
- Record-count words that overstate the body (`m/MS600A`, `m/MS610B`, `et/ID00A2`, `et/ID00A3`) and trailing bytes are copied verbatim; what the engine does with them is unknown.
- Containers with duplicate record ids and branches (`m/MS6000` c0/1/8, `m/MS6800` c0, `m/MS610B` c15) are not editable.

## vmops / opcodes.json
- 267 opcodes are typed as consuming no operands because the static tracer took the fall-through; 123 records still cannot be tiled.
- `1F01 nn` followed by `00` (3 240 sites in the original, all stripped by v0.05): meaning unknown.
- The byte after a name macro in the post-menu dead zone (`00 02 01 6a`): meaning unknown; v0.05 changed it, translators deleted it.
- `NOT_A_BRANCH = {010, 011, 182}` is statistical (target lands on an instruction at or below chance).  `017` is in the grey zone on the original (48.7% vs chance 43%) and is still relocated.

## codec
- One span in the original (`m/MS0061` 0:0B[32]) contains `FA 82` (冾, IBM extension); cp932 re-encodes it as the NEC duplicate `ED 65`.  Text tokens that do not re-encode to their own bytes are rendered as raw `{=HH}` tokens.

## script / relocation
- Branches whose target is strictly inside an edited span block the edit (115 lines ship untranslated).
- Text-capture mode (`1B`..`1C`, 256-byte buffer) is not yet enforced by `check`.

## exe
- Debug-menu arming is unverified (the table at `0x468318` is not four contiguous pointers).
- `HKCU\Software\ASCII\GITEN_DDS\DevConfig` must exist at startup; written by `Config.exe`.
