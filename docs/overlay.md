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
`0x438E50` (five call sites, all redirected to the hook).

**The hook never asks which file a buffer is.**  It finds the record the
program counter is in, from the buffer's own 256-entry index, hashes that
record's bytes, and looks the triple up in one flat table:

    key = (record id, record length, FNV-1a of the record's bytes)

If the Japanese in front of us is the Japanese we translated, the English is
served.  If it is not, nothing is.  That is the whole rule, and section
"Identity binding was the wrong question" below is why it replaced everything
that came before it.

### Serving a span

`giten/overlay.py` gives each span a **virtual PC range** above the buffer's own
image end; serving English is then a pure function of the address:

```
rec_off <= k < rec_off + served   -> en[k - rec_off]        served IN PLACE at record_off + k
   last in-place byte             -> PC := image_end + virt_off (if a tail exists) else span end
virt_off <= v < virt_off + tail   -> en[served + v - virt_off]   the excess, in virtual space
   last tail byte                 -> PC := span end
anything else                     -> the original fetch
```

`served = min(len(en), len(jp), cap - rec_off)`, and `cap` is the lowest address
any branch in the container jumps to inside the span.  `virt_off` is the sum of
the tails of the *earlier spans of the same record*, so the layout is a property
of the record and of nothing else.  Virtual space is spent only on the excess of
English over Japanese; the worst record in the game uses 7,422 of the 24,576
bytes a record may have.

Every PC write in the engine is a plain value store (jump `0x433C40`, call frame
push/pop `0x43C1F0`/`0x43C260`, new context `0x438DF0`, menu rescanner
`0x435D23`), so a virtual PC survives all of them.

A virtual PC names no record on its own -- every record's tails start at the
same `image_end` -- so it is resolved through the per-handle memo.  That is
sound because **no opcode the codec may put inside a span transfers control
within one handle**: `codec.INLINE_OPS` is the newline, the page wait and the
eight pool calls, and a pool call switches to the pool file's own buffer
(measured in `traces/2026-09-10-run2.bin`: the caller's index entry is unchanged
across one) which gets its own memo slot.  `tests/test_overlay.py` pins that
precondition, because if it ever stops holding the virtual layout needs a
per-handle tail stack.

### The memo

The only thing remembered between fetches.  One slot per handle, direct-mapped
on `handle & 15`, each holding `{handle, base, rec, off, len, entry, pc}`.  A
slot is valid only when **all four** still agree:

* the handle;
* the buffer's base pointer;
* the buffer's own index entry for the memoised record, `(off, len)`;
* the program counter this slot handed back last.

The fourth is not optional and was not in the original plan.  A record id plus
an offset and a length is not content: measured over the corpus, **92 `(id,
offset, length)` slots hold more than one record** -- 257 records in all, 80 of
the slots holding something we translate -- and `rec 02` at `0x423` with length
9 is seven different records, which is one of the three wrong lines that
prompted v6.  Without the program-counter check a buffer reloaded in place could
present a different record at the same slot and keep serving the old record's
English.  A script load sets a new program counter, so a reloaded buffer's first
fetch is never a continuation and the record is hashed again.

Cost: one record hash per record transition and per jump, four `u16` compares
per byte.

## `overlay.dat` v6

```
header   4s "GTOV", u32 version = 6, u32 nrecs, u32 nspans
recs     nrecs x { u16 rec_id, u16 jp_len, u32 jp_hash,
                   u32 span_first, u16 nspans, u16 tail_total }
         sorted by (rec_id, jp_len, jp_hash) -- binary-searchable
spans    nspans x { u16 rec_off, u16 jp_len, u16 served, u16 len,
                    u16 virt_off, u16 pad, u32 data_off }
         grouped by record, sorted by rec_off, non-overlapping
data     the English bytes (codec-encoded, inline opcodes included)
```

`served` is stored rather than derived because it is not always
`min(len, jp_len)`: a span some branch jumps into stops at that branch's target
so the jump reads the original file.  When the same record content appears in
several containers with different branch layouts, the **smallest** `served`
wins -- serving less is always safe.

`virt_off` is carried by every span, including those whose English fits in
place, so it is non-decreasing across a record's spans and the hook can binary
search the virtual side too.

## The one residual: identical records must share English

Two files holding a byte-identical record are one key, so they get one
translation.  254 keys disagreed when v6 was written -- `Man:` against `Male:`,
three renderings of *"There's no one here..."*, two shopkeepers' greetings
written a month apart.  `tools/unify_duplicates.py` resolved them in the tables
(a reviewed row wins, else the most frequent text, else the longest), `giten
check` reports any new one as an `overlay-conflict` **error**, and `giten
overlay` refuses to write anything while one stands.  Under that rule the
residual is zero by construction.

## Identity binding was the wrong question

Every version before v6 answered *which file is this buffer* and then trusted
the answer.  v4 hashed the buffer's 1024-byte record index and matched it
against a hash built from one container of one file.  v5 kept that and added a
per-span hash of the Japanese, which made a **merged** buffer work -- but the
binding itself was still cached per `(handle, fid)`, and the verification bits
were computed once at bind time.

The engine reuses one handle and one pseudo file id (`0x7F`, "this map's script
slot n") for every shop, terminal, bar and clinic on a map, and rebuilds the
demon merge under `0xE0` for every demon.  So the binding went stale and the
hook served the previous script's English at the new script's record addresses.
Measured in `traces/2026-09-10`:

| what ran | the engine's own index entry, record 2 | English served |
|---|---|---|
| weapon shop (`m/MS0101`) | 12 bytes at 0x41C | "Hurry up and choose." -- correct |
| a later script, same id, same handle | 9 bytes at 0x423 | "Hurry up and choose." -- the shop's line |
| another | 9 bytes at 0x425 | "what we have on offer. Please take a look." -- entered mid-span |

Negotiation was the same defect from the other side: demon A's merge stayed
bound and demon B's files never bound, so Japanese drew.

Each of those was a real bug in a real mechanism, and each fix was correct about
the mechanism it fixed.  What none of them could fix is that **the question has
no stable answer** -- a buffer's identity is not a property of the buffer, it is
a property of a global the engine updates on its own schedule.  v6 stops asking.
The record in front of the program counter is a fact about memory right now, and
it is the only fact the overlay needs.

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
  interpreter runs whichever its context points at.  All 228 records carried an
  index entry -- which `trace.S` reads out of the *live* buffer -- of
  `(0x4BEF, 1)`, and `m/MS00DD`'s entire index stops at `0x1CC9`, so the buffer
  being executed was not `m/MS00DD` at all.  Nothing in that trace shows the
  engine leaving the script.  **The soft lock was explained later the same day**:
  it is the unsafe fall-through documented below.
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
  inside it, and `overlay.dat` stores that length instead of deriving it.
  **It costs no coverage** -- the capped bytes move into the virtual tail, so a
  sequential read still shows the whole English line; only the jumped-into path
  reverts to Japanese, which is what this bullet always claimed.
  Note what this was *not*: not a bad span boundary, not a tokenizer error, not
  a wrong byte in the tables.  The tables were right and the byte builder had
  refused these very edits for years (`@noedit`).  The overlay was written as a
  delivery mechanism and inherited the builder's *layout* rules without its
  *refusals*.
* Per **record**, the English excess over the Japanese must fit between the
  image end and 0x10000 (`overlay-space` in `check`).  Whole game: 0 refused
  rows; the worst record spends 7,422 of 24,576 bytes.
* Still direct edits, still bounded by the old rules: `p/` names (8 bytes),
  the 255-byte capture buffer (`1B`..`1C`), line width.  `et/ID*` tables are
  read by other code paths and are not covered by the hook.
* The hook is ~250 lines of C compiled `-m32 -ffreestanding`; a bug there
  crashes the game.  `tests/test_overlay.py` and `tests/test_merged_overlay.py`
  run the same C natively over a real `overlay.dat` and demand the bytes the
  Python model predicts -- including through a buffer swapped under a live
  handle, which is the case that needs a process, not a function call.

## The fall-through was not safe (2026-09-07)

`hook()` gave up -- and handed the address to `ORIG_FETCH` -- whenever it could
not identify the buffer.  For a real address that is harmless.  For a
**virtual** one it is not: a PC at or above `image_end` exists only because this
overlay put it there, and `ORIG_FETCH` just indexes the buffer.  Read past the
end and you get an access violation if the page is unmapped and garbage if it is
not.  Both happened, in the same file, one run apart:

* crash, from the dump: `eip 0x00438E75`, `FILEID 0x00DD` (the battle script)
  while the PC was `0x58EB` -- an address we invented for `m/MS001F`, whose
  image ends at `0x4BA7`.
* the earlier soft lock: same `FILEID 0x00DD`, same file actually running --
  proved independently by the engine's own index entry `(0x4BEF, 1)` -- landing
  on mapped `01` bytes and looping on pool calls.

`passthrough()` refuses to call `ORIG_FETCH` at all when the PC is at or above
the buffer's own image end, which is four bytes of its index
(`index[255].off + .len`) and needs no directory entry.  It returns `0xFF` and
advances the PC.  That is a chosen degradation, not a known-correct value: by
then the run is already wrong, and the only promise being made is that we do not
read memory we do not own.  **This survives v6 unchanged**, and matters more
now: with the memo gone (an evicted slot, an aliased handle) a virtual address
is exactly what cannot be answered.

## Test setup

`play/en/ddswin` = original files + `dds_dev.exe` + `overlay.dat`;
`play/jp/ddswin` = original files + the same `dds_dev.exe` and *no*
`overlay.dat` (the hook passes everything through).  Snapshot `trace.bin` after
each run; it is recreated on every launch.

`giten trace verify <trace>` needs a **v4** trace, which logs the record's own
FNV-1a and the buffer's image end.  Anything older is refused rather than judged
against the wrong file.

**One caveat, and it is about the machine, not the code.** The C conformance
harness will not run while ESET is active: it reports `NOT RUN: this machine
will not execute the harness (PermissionError)` and passes.  That is exactly how
the model and the C came to disagree unnoticed once already.  **If any test
reports NOT RUN, the C hook is unverified for that run, whatever the suite
says.**

---

## The merged-buffer gate, and why it cost 789 spans on slot 0 alone

**SUPERSEDED by v6 (2026-09-10).**  Kept because the measurement is still good
and because the fix it describes was correct about the mechanism it fixed -- it
is the last thing that was done to identity binding before identity binding was
removed.  What follows describes v5.

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

### What the fix was -- LANDED 2026-09-10, commit 6950987

1. `overlay.bind()`: the `len(resolve(...)) != len(e.spans)` gate is gone; an
   entry contributes the spans that verify. Candidate order is unchanged (file
   id), because ordering by explanatory power would have to be mirrored in C and
   buys nothing: a span that hashes to the Japanese in front of it is a correct
   translation of those bytes whoever supplied them.
2. `hook.c` `entry_fits()`: returns on the first span that verifies.
3. `hook.c` `merged_fetch()`: tests the span a PC lands in before serving it.
   **Not** with a bitmap -- that is how the single-entry path does it, but here
   it would be `2 x MAX_MERGE x MAX_SPANS/8` twice over, about 4 KB, and
   `hook.ld` puts `.bss` inside the blob so all of it is appended to the exe.
   `span_ok()` memoises on the last span asked about instead: eight bytes, and
   one hash per span rather than one per byte, because consecutive fetches walk
   through the same span.
4. The tail path needed no new structure after all: a tail is packed with its
   span's `rec`, `rec_off` and `jp_hash`, so the same test decides both.
5. `lookup()` reserves virtual space from the last tail that *verifies* rather
   than the last tail, so windows do not over-reserve now that partial entries
   bind. `bind()` sizes them the same way.

`.ovl` grew 4,608 -> 5,120 bytes. The 38 bytes patched in place did not move.

### How it is verified

`tests/test_merged_overlay.py` compiles the real `hook.c` into a harness and
walks a merged buffer through it, demanding the same bytes the Python model
gives. Two merges are walked: `ROW0`, which displaces nothing and passed before
the fix too, and **`ROW17`, where m/MS6100 replaces four of m/MS6000's records**
-- the case the old rule turned into "serve none of this file". All 73 records
of that buffer agree byte for byte, and the negotiation English is present in
the walk.

Reverting `entry_fits()` to the all-or-nothing form makes that test fail at
record `0x02`, so it is the bug it catches and not a restatement of the code.

**One caveat, and it is about the machine, not the fix.** The harness will not
run while ESET is active: it reports `NOT RUN: this machine will not execute the
harness (PermissionError)` and passes. That is exactly how the model and the C
came to disagree unnoticed in the first place. If this test ever reports NOT
RUN, the merged path is unverified in C for that run, whatever the suite says.

### Why this whole section is superseded

The gate above was a rule about *which entries may bind to a buffer*, and the
per-span hash under it was a rule about *which of a bound entry's spans may be
served*.  Both exist only because an entry is a file and a buffer had to be
matched to one.  v6 has no entries-per-file, no binding and no membership: a
record is found by its own bytes, wherever it is, in whatever buffer, merged or
not.  The demon merge stops being a case -- and so does the `0x7F` shop slot,
which the same machinery got wrong in the opposite direction by binding too
eagerly rather than not at all.

The numbers below are still the right way to *measure* a merged buffer, and
`tests/test_merged_overlay.py` still walks `ROW0` and `ROW17` through the real
`hook.c`.  What it no longer does is ask whether anything bound.
