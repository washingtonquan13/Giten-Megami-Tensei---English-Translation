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

## The fall-through was not safe (2026-09-07)

`hook()` gave up -- and handed the address to `ORIG_FETCH` -- whenever it could
not identify the buffer, starting from the engine's current-file global
`0x4911B0`.  That global is written when a script is **loaded**, not on every
context switch, and several scripts are resident at once, so it routinely names
a file the interpreter is not running.

For a real address that fall-through is harmless.  For a **virtual** one it is
not: a PC at or above `image_end` exists only because this overlay put it
there, and `ORIG_FETCH` just indexes the buffer.  Read past the end and you get
an access violation if the page is unmapped and garbage if it is not.  Both
happened, in the same file, one run apart:

* crash, from the dump: `eip 0x00438E75`, `FILEID 0x00DD` (the battle script)
  while the PC was `0x58EB` -- an address we invented for `m/MS001F`, whose
  image ends at `0x4BA7`.  `0x58EB` was inside a tail we had declared, so the
  hook should have served it.
* the earlier soft lock: same `FILEID 0x00DD`, same file actually running --
  proved independently by the engine's own index entry `(0x4BEF, 1)`, which is
  `m/MS001F`'s -- landing on mapped `01` bytes and looping on pool calls.

Two changes, and the second holds even if the first ever fails:

1. `rebind` tries `(fid, fingerprint)` first, then the fingerprint **alone**,
   accepting it only when exactly one entry matches.  A fingerprint is the
   buffer's own content and cannot go stale.  Ten fingerprints in the corpus
   are shared and six of those groups have genuinely different images, so a
   lone fingerprint is not always an answer -- those keep the old behaviour.
2. `passthrough()` refuses to call `ORIG_FETCH` at all when the PC is at or
   above the buffer's own image end, which is four bytes of its index
   (`index[255].off + .len`) and needs no directory entry.  It returns `0xFF`
   and advances the PC.  That is a chosen degradation, not a known-correct
   value: by then the run is already wrong, and the only promise being made is
   that we do not read memory we do not own.

`tests/test_overlay.py` drives the real C hook for all three: a wrong file id
still serves English, an unidentifiable buffer still passes real addresses
through, and a virtual PC in an unidentifiable buffer comes back `0xFF`.

## Guarantees and limits

* Logic cannot change: no script byte is written.  On the same route the EN
  trace must equal the JP trace opcode for opcode (`trace diff`).
* A wrong span boundary (tokenizer error) shows Japanese or garbled text for
  that line.  Whether it can also move a branch is **open**: not disproven, and
  not proven either.  One way it provably can is recorded below, under the
  menu rescanner.

  *A retraction.*  On 2026-09-07 this guarantee was struck as FALSIFIED, on the
  strength of a recorded soft lock whose trace showed 228 records dispatching
  from PC `0x5BE3` in `m/MS00DD`, a file whose image ends at `0x1CC9`.  That
  reading was wrong and the strike is withdrawn.  The file a trace record is
  labelled with comes from the engine global `0x4911B0`, which is written when
  a script is **loaded**; several scripts are resident at once and the
  interpreter runs whichever its context points at, so while it runs an earlier
  one the global still names the file loaded most recently.  All 228 records
  carried an index entry -- which `trace.S` reads out of the *live* buffer --
  of `(0x4BEF, 1)`, and `m/MS00DD`'s entire index stops at `0x1CC9`, so the
  buffer being executed was not `m/MS00DD` at all.  They were program counters
  judged against a file that was not running.  Nothing in that trace shows the
  engine leaving the script.
  `giten trace verify` now refuses to judge a record whose file label the
  engine's own index entry contradicts (18,504 of 141,148 on that trace), and
  reports **0** program counters outside the file and our overlay.

  A second hole came out of the same chase.  A trace only means anything
  against the overlay that produced it, and nothing enforced that: the
  2026-09-06 trace re-checked against a later overlay reported 891
  out-of-bounds PCs in `m/MS0017`, every one an artifact of a single span whose
  English has since been dropped, shifting every virtual address above it.
  The tell was that the engine kept reading coherent English past the end of
  the last tail -- *"and a discarded DB blouson lying next to it"* -- which
  memory past the script buffer cannot produce.  `verify` now refuses a trace
  whose virtual PCs hold different bytes than the overlay it is handed puts
  there; virtual addresses exist only because the hook creates them, so this
  needs nothing stamped into either file.  It separates the traces on disk
  completely: three agree on all 31,430 virtual PCs, two disagree on 5,769.

  **What still stands from that investigation**: `verify` does now check that
  every dispatched PC is inside the real image or a virtual range we declared,
  and every check has a mutation test proving it fires.  Such a PC *can* only
  arise on a translated build, since virtual PCs exist because English is
  longer than Japanese.  **The soft lock was explained later the same day**:
  it is the unsafe fall-through documented above, and the section on it carries
  the evidence.  The `r == -1` ("page full, loop exits") on `m/MS00DD` record
  `0x4E` is where the context switches to another buffer; the file id does not
  follow, the hook stops recognising the buffer, and the original fetch is
  handed a virtual address off the end of it.  Ruled out while narrowing: the
  container-0 limitation (`m/MS00DD` has one container and one overlay entry);
  a page-capacity rule (the Japanese itself needs more than three rendered
  lines on 2,609 pages and more than six on 236); and, now, the claim that the
  engine was executing memory nobody owns.
* A span is diverted only when entered at its first byte.  The lines a branch
  lands *inside* keep their Japanese tail -- **enforced since 2026-09-07, and
  false before that.**  The hook derived its served length as
  `min(len(en), len(jp))`, so it answered every address inside a span,
  including the ones branches jump to.  Almost all of those aim at the line's
  own trailing `1E 10` page wait -- the script saying "skip the words, go
  straight to the page break" -- and instead of `1E` the jump got a letter of
  English, which the interpreter then ran as an opcode.  278 addresses across
  75 files shipped that way.
  The fix is one number: a span is served only up to the lowest branch target
  inside it (`SpanEntry.cap`), and `overlay.dat` v4 stores that length instead
  of deriving it.  Everything from the cap on falls through to `ORIG_FETCH`, so
  a jump reads exactly the bytes it always read.  **It costs no coverage** --
  the capped bytes move into the virtual tail, so a sequential read still shows
  the whole English line; only the jumped-into path reverts to Japanese, which
  is what this bullet always claimed.
  Note what this was *not*: not a bad span boundary, not a tokenizer error, not
  a wrong byte in the tables.  The tables were right and the byte builder had
  refused these very edits for years (`@noedit`).  The overlay was written as a
  delivery mechanism and inherited the builder's *layout* rules without its
  *refusals*.
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

---

## The merged-buffer gate, and why it costs 789 spans on slot 0 alone

Diagnosed 2026-09-10 against the player's recorded sessions. **The negotiation
text is not untranslated; it is translated and refused at bind time.**

`tools/screen_audit.py` put 30% of the surviving Japanese in the "row has clean
English and Japanese drew anyway" bucket. Decoding the trace says why. The
engine uses **only** the merged file ids `0x00E0`..`0x00EE` for demon
conversation, never a `m/MS6xxx` id, and the shipped `overlay.dat` holds 296
entries keyed on `0x6xxx` ids and **zero** on merged ids. All 296 are reachable
only through `bind()`'s merged path.

### What is actually wrong

Both `overlay.bind()` and `entry_fits()` in `giten/exe/hook.c` require **every**
span of an entry to verify before **any** of it is served:

    if (!span_holds(idx, base, end, &sp[i]))
        return 0;                   /* one miss rejects the whole file */

The rationale was that a file not in the merge fails on the first record the
merge does not share. But `0x0043ABC0` lets a later file **replace** an earlier
file's record by id, so a file that *is* in the merge fails too, and its other
hundred-odd verified spans go with it.

The per-span hash in `resolve()` / `span_holds()` is already the correctness
test: it keeps a span only when the Japanese at the live address hashes to what
that span was built from. It does not need the all-or-nothing gate on top, and
relaxing the gate cannot serve a span differently -- a span that verifies under
one rule verifies under the other. It can only add spans.

### Measured

Building the real merges that `et/ET0007` names, and binding the shipped
overlay against them (`scratchpad/merge_probe.py`, slot 0 of all 25 demon rows):

| | spans bound |
|---|---|
| all-or-nothing (today) | 2,646 |
| per-span | 3,435 |

Seven of the twenty-five rows go from about **3** spans to about **108**. That
is slot 0 of sixteen, so the whole-game figure is larger.

### What the fix needs, and why it was not done in one sitting

1. `overlay.bind()`: drop the `len(resolve(...)) != len(e.spans)` gate; order
   candidates by how many spans they verify, then by file id, so the file that
   best explains the buffer claims contested addresses first.
2. `hook.c` `entry_fits()`: return true when **any** span verifies.
3. `hook.c` `merged_fetch()`: a merged entry may now hold spans that do not
   verify, so the serve path has to skip them. The single-entry path already
   solves this with a precomputed bitmap (`c_ok`) precisely because hashing per
   fetch is O(span) per byte. The merged path needs the same, sized
   `2 x MAX_MERGE x MAX_SPANS/8` for spans and again for tails -- about 4 KB of
   BSS against a 4,608-byte `.ovl` section, so the section budget has to be
   checked, and `MAX_MERGE` can drop from 8 to the measured 5 if it is tight.
4. The **tail** path needs the same skip, and a tail is a separate struct from
   its span, so the two have to be associated before a tail can be refused.
5. Then: rebuild the exe, extend `tests/test_merged_overlay.py` with a merged
   image in which one record is displaced (today nothing covers that case --
   the full suite passes with the model and the C disagreeing), and play-test.

Steps 1 and 2 are small. Step 3 is a size-budgeted embedded change and step 4
needs a data-structure decision, which is why this is written down rather than
half-applied. **Do not land 1 without 2 to 4**: the Python model is what
`tests/test_overlay.py` checks the C against, and a model that binds more than
the hook does silently voids that guarantee.
