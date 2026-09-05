# The runtime text overlay

Decided 2026-09-04 after three consecutive play-test blockers (32K record cap,
the `0F` switch tables, span renumbering) turned out to be the same class of
bug: an incomplete opcode model letting a branch move when English lengthened a
record.  The overlay removes the class instead of adding a fourth rule.

## What ships

| piece | file | role |
|---|---|---|
| script files | `m/MS*.BIN` | **byte-identical to the original** |
| `dds.exe` | `giten exe release` | locale fixes + the `.ovl` section (hook.c) |
| `dds_dev.exe` | `giten exe dev` | release + the `.trc` tracer section |
| `overlay.dat` | `giten overlay --text tables` | every translated span, English bytes included |
| `p/*.BIN` | `giten build` | the 8-byte player-name field is still a direct edit |

## How it works

The interpreter reads every script byte through `FETCH(handle, &pc)` at
`0x438E50` (five call sites, all redirected to the hook).  `giten/overlay.py`
gives each translated span a *virtual PC range* above the file's image end;
`giten/exe/hook.c` then serves English as a pure function of the PC:

```
start <= PC < start + head   -> en[PC - start]     head = min(len(en), len(jp)): served IN PLACE
   last head byte            -> PC := virt (if a tail exists) else span.end
virt <= PC < virt + tail     -> en[head + PC - virt]  the excess over the Japanese, in virtual space
   last tail byte            -> PC := span.end
anything else                -> the original fetch
```

Virtual space is spent only on the *excess* of English over Japanese, so
the whole game fits with room to spare (worst file `m/MS0030` at 50%).

Every PC write in the engine is a plain value store (jump `0x433C40`, call
frame push/pop `0x43C1F0`/`0x43C260`, new context `0x438DF0`, menu rescanner
`0x435D23`), so a virtual PC survives all of them; there is no hidden state.
Files are matched by the current-file id (`0x4911B0`) plus an FNV-1a
fingerprint of the buffer's own 0x400-byte record index, which tells the
containers of a multi-container file apart.  A buffer whose entry 0 is not at
0x400 is not a script buffer and is never hashed.

## Guarantees and limits

* Logic cannot change: no script byte is written.  On the same route the EN
  trace must equal the JP trace opcode for opcode (`trace diff`).
* A wrong span boundary (tokenizer error) shows Japanese or garbled text for
  that line; it cannot move a branch or crash the interpreter.
* A span is diverted only when entered at its first byte.  The lines a branch
  lands *inside* (`@noedit`, 115 in the corpus) keep their Japanese tail.
* Per file, the English *excess* over the Japanese must fit between the image
  end and 0x10000 (`overlay-space` in `check`).  Whole game: 0 refused rows,
  worst file `m/MS0030` at 50%.
* Still direct edits, still bounded by the old rules: `p/` names (8 bytes),
  the 255-byte capture buffer (`1B`..`1C`), line width.  `et/ID*` tables are
  read by other code paths and are not covered by the hook.
* The hook is ~200 lines of C compiled `-m32 -ffreestanding`; a bug there
  crashes the game.  `tests/test_overlay.py` runs the same C natively over a
  real `overlay.dat` and demands the bytes the Python model predicts.

## Test setup

`play/en/ddswin` = original files + `dds_dev.exe` + `overlay.dat`;
`play/jp/ddswin` = original files + the same `dds_dev.exe` and *no*
`overlay.dat` (the hook passes everything through).  Snapshot `trace.bin` after
each run; it is recreated on every launch.
