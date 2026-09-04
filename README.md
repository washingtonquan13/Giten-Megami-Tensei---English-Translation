# Giten Megami Tensei (偽典・女神転生) — English Translation

Continuation of the abandoned v0.05 Windows fan patch. Goal: translate the remaining
~13% of text (demon negotiation, choice menus, story tails, exe leftovers) and ship a
patch that runs on Windows 11.

This repository holds **tools, translation text and build scripts only**. The game
itself (Atlus/ASCII assets) is never committed; see `.gitignore`.

## Layout

    tools/bin_tools/     decoder / encoder / text dumper for the game's .BIN files
    tools/exe_analysis/  PE parser and string inventories for dds_en.exe
    tools/dumps/         extracted text ready to translate (negotiation, choices, names)

## Game folder

The tools locate the game's `ddswin/` folder by searching upward from their own
location (the game folder is expected to be a sibling of this repo), or via the
`GITEN_ROOT` environment variable. Set `PYTHONIOENCODING=utf-8` before running them.

    python tools/bin_tools/giten_pack.py                 # verify byte-exact round trip on all 844 encoded files
    python tools/bin_tools/giten_lines.py m/MS6000.BIN   # dump tagged text lines (add --jp for Japanese only)
    python tools/bin_tools/giten_text.py m/MS6007.BIN    # record view with dictionary expansion

## Data format (verified)

* Container: `[u16 LE header][body]`, body is a chained XOR: `plain[i] = enc[i] ^ enc[i-1]`.
* Script records: `[id:u8][len:u16 LE][data]`; text uses `1F xx` control tags
  (`1F D2` speaker, `1F D3` speech, `1F B2` choice option) and `08 nn` = word `nn`
  from the dictionary file `m/MS7F07.BIN`.
* Negotiation text: `m/MS6000–6016`, `m/MS6100–610D`, `m/MS7F06`, `et/ID*`.
