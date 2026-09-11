# Overlay v6: content addressing

Written 2026-09-10 after the player's third recorded session showed shop lines
at a terminal, mid-string English, and demons still speaking Japanese, all on
the build that carried the merged-buffer fix of 6950987.

## 0. The defect this removes, and the rule that replaces it

Every wrong line in `traces/2026-09-10` has one cause. `hook.c` answers the
question "which file is this buffer" once, from the engine's file-id global and
the buffer handle, caches the answer per `(handle, fid)`, and then trusts it.
The engine reuses one handle and one pseudo file id (`0x7F`, "this map's script
slot n") for every shop, terminal, bar and clinic on a map, and rebuilds the
demon merge under `0xE0` for every demon. So the binding goes stale and the
hook serves the previous script's English at the new script's record
addresses. Measured in the trace:

| what ran | engine's own index entry, record 2 | English served |
|---|---|---|
| weapon shop (`m/MS0101`) | 12 bytes at 0x41C | "Hurry up and choose." -- correct |
| a later script, same id, same handle | 9 bytes at 0x423 | "Hurry up and choose." -- the shop's line |
| another | 9 bytes at 0x425 | "what we have on offer. Please take a look." -- entered mid-span |

Negotiation is the same defect from the other side: demon A's merge stays
bound, demon B's files never bind, Japanese draws.

**The new rule.** The hook never identifies a file. An English byte is served
only if the Japanese *record* it translates is in the buffer, byte for byte,
right now. The key of every translated span is the content of its record:

    (record id, record length, FNV-1a of the record's bytes)

Nothing is remembered between fetches except a memo, and the memo is
re-validated against the live index on every fetch. There is no file id, no
index fingerprint, no per-file directory, no membership rule, no merge window,
no bitmap. Stale bindings, pseudo ids and rebuilt merges stop being cases.

**The one residual.** Two files holding a byte-identical record share a key,
so they must share English. Measured against the shipped overlay: 253 keys, in
46 files, currently carry different English for the same record -- "Man:"
against "Male:", three renderings of "There's no one here...". The build
refuses while any remain and `check` lists them; they are unified in the
tables (section 6). Under that rule the residual is zero by construction.

## 1. `overlay.dat` v6

Little-endian. One flat table, no per-file directory.

    header   4s "GTOV", u32 version = 6, u32 nrecs, u32 nspans
    recs     nrecs x { u16 rec_id, u16 jp_len, u32 jp_hash,
                       u32 span_first, u16 nspans, u16 tail_total }
             sorted by (rec_id, jp_len, jp_hash) -- binary-searchable
    spans    nspans x { u16 rec_off, u16 jp_len, u16 served, u16 len,
                        u16 virt_off, u16 pad, u32 data_off }
             grouped by rec, sorted by rec_off, non-overlapping
    data     English bytes (codec-encoded, INLINE_OPS only)

Per span: `jp_len` is the span's Japanese length; `len` the English length;
`served = min(len, jp_len, cap - rec_off)` where `cap` is the lowest branch
target inside the span, exactly as today (`SpanEntry.head`); `tail = len -
served`; `virt_off` = the sum of `tail` over the earlier spans of the same
record entry, so the tail's virtual address is `image_end + virt_off`.
`tail_total` on the record is the sum of all its tails. When the same record
content appears in several containers with different caps, the smallest
`served` wins (serving less is always safe).

Keep `overlay.parse` able to read v6 only. v4/v5 readers go; the fixtures that
depend on them go with them (section 5).

## 2. The hook (`giten/exe/hook.c`)

Per fetch `(handle, pc)`:

1. `base = script_buffer(handle)`; no base -> `ORIG_FETCH`. `idx = base`,
   `end = image_end_of(base)`.
2. **Memo.** Four slots `{u32 handle; const u8 *base; u16 rec, off, len;
   const struct rec *entry; }`. A slot is *valid* only if `handle` and `base`
   match and `idx[rec] == (off, len)` right now. Validation is done on every
   fetch; a slot that fails is recomputed, never trusted.
3. **Real pc (`pc < end`).** Find the record containing `pc` by binary search
   over the index (offsets are non-decreasing in id; absent ids are one-byte
   slots). If the memo slot for this handle is valid and names that record, use
   its `entry`; otherwise hash the record's `len` bytes, binary-search the recs
   table by `(rec_id, len, hash)`, and store the result in the slot (`entry`
   may be NULL: "not translated", also memoised). No entry -> `ORIG_FETCH`.
   Find the span with `rec_off <= pc - off < rec_off + served` by binary
   search. None -> `ORIG_FETCH`. Else `k = pc - off - rec_off`; serve
   `data[k]`; next pc is `off + rec_off + jp_len` when `k + 1 == len`,
   `end + virt_off` when `k + 1 == served`, else `pc + 1`.
4. **Virtual pc (`pc >= end`).** The memo slot for this handle must be valid
   (same buffer, same index entry) -- a virtual pc exists only because step 3
   just created it. Find the span with `virt_off <= pc - end < virt_off +
   tail`. Serve `data[served + (pc - end - virt_off)]`; next pc is the real
   end of the span on the last tail byte, else `pc + 1`. No valid slot or no
   span -> `passthrough` (0xFF, pc + 1), exactly as today.

Cost: a record hash once per record transition per handle, four u16 compares
per fetch. The hook has no `FILEID` reference at all; remove the define from
the harness header and the tracer's symbol table if nothing else needs it.

**Precondition to verify before writing a line:** `codec.INLINE_OPS` must
contain no opcode that transfers control within the *same* handle (no `0C`,
`0D`, `1F01`-style calls into another record of this file). Pool calls
(`01`-`08`) switch handles and return, so the memo for this handle survives
them. Pin this with a test on `INLINE_OPS`. If it does contain one, the
virtual layout above is not safe and the plan needs a per-handle tail stack;
stop and report rather than improvise.

Keep `pace()`, `script_step()`, `battle_step()` untouched. Keep every
`engine_state.py` guard (`tests/test_engine_state.py` enforces them). The
`.ovl` cave should shrink; update the `("ovl", 38, N, True)` pin in
`tests/test_v2.py` and the table in `docs/exe-patches.md` with the measured
size.

## 3. The model (`giten/overlay.py`)

`Model(table, image)` implements section 2 literally, one fetch at a time,
including the memo and its validation, so the harness can be driven through
buffer swaps and compared. `walk(pc, stop)` keeps its signature. Delete
`bind`, `resolve`, `rebind`-adjacent helpers, `merged_slot`, `fingerprint` as
an identity, `engine_index` if only the fingerprint used it, `Entry.fid/fp/
image_end`. `plan(rows)` now returns `(table, findings)` where the table is
keyed by record content; `build(table)` and `parse(blob)` implement section 1.

Refusals that stay, unchanged: untiled records, `PNAME_REC`, spans holding
`0xFF`, dangling escape prefixes, English encoding to nothing, a span not
starting where a token starts. The per-file `overlay-space` bound becomes a
per-record bound: `tail_total <= 0x10000 - MAX_IMAGE_END`, where
`MAX_IMAGE_END` is measured over every file and every `et/ET0007` merge and
pinned with a margin.

**Conflicts.** `plan()` groups rows by record key. Two rows with the same key
and the same span offset whose encoded English differs is a finding
(`overlay-conflict`) naming both rows; `check` reports it as an error and
`build` refuses the table. The message must name the file, record, span and
both English strings.

## 4. The harness (`tests/hook_harness.c`) and the C conformance tests

Add a scripted mode, `hook_harness script <file>`, one command per line:

    load <handle> <image.bin>       map the image as this handle's buffer
    reload <handle> <image.bin>     overwrite that buffer in place (same base pointer)
    walk <handle> <start> <stop>    print the bytes as hex, then pc=<final>
    fid <n>                         kept only while FILEID still exists

so one process can do what one play session does. Keep the old five-argument
form working for existing tests.

Tests, each comparing the compiled `hook.c` against `Model` byte for byte:

1. every record of `m/MS0017` walked (the existing plain test);
2. the two merges `ROW0` and `ROW17` (the existing merged tests, now with no
   file id at all);
3. **the stale-cache scenario**: load `m/MS0101` as handle 3, walk record 2,
   reload handle 3 with `m/MS00A0`, walk record 2 -- must equal
   `Model(MS00A0)` and must not contain `b"Hurry up"`; then reload with the
   `ROW17` merge under the same handle and walk every record;
4. interleaved handles: walk a span of `m/MS0017` that contains a pool call,
   with `m/MS7F0x` loaded as another handle, switching handles mid-walk the
   way the engine does, and confirm both memos survive.

**Mutation checks** (temporary edits, each must make a named test fail, then
restore): (a) skip the memo's index validation -> test 3 fails; (b) hash only
the span instead of the record -> a test with two files sharing a span but not
a record fails; (c) restore the old `served = min(len, jp_len)` -> the
branch-target test fails.

`_build_harness` prints `NOT RUN` when ESET blocks the binary. Report that
line verbatim if it appears; a green suite with that line is not verification.

## 5. The tracer and `verify`

Trace v4 appends to each record: `u32 rec_hash` (FNV-1a of the current
record's bytes, from the same index entry the tracer already reads) and `u16
image_end` (`idx[255].off + idx[255].len`). Record size 28. `trace.S` already
reads the index entry before the call; hash there, under the same guards.
Decoder: `RECORD_V4`, `BY_VERSION[4]`, `_fields` returns the two new values.

`verify` is rewritten to need no file identity: for every event with a
context, look up `(rec, idx_len, rec_hash)` in the overlay table exactly as
the hook does, and demand that the logged byte at `pc0` is either the English
the table serves there or the original record byte outside any served range;
virtual pcs resolve through `image_end + virt_off`. The "corroborated" gate,
`paired()`, and the stale-label carve-out go away. `decode`, `diff`, `bases`,
`files` keep using file labels; they are about the Japanese build and are not
touched.

The recorded fixtures (`tests/data/verify-overlay.gtov` and the traces beside
it) are v4/v5 overlays and cannot be replayed through v6. Replace the tests
that used them with synthetic traces generated from `Model.walk` (a clean
walk verifies clean; flip one served byte and `verify` names it; move a pc
into virtual space with no tail and `verify` names it). Delete the fixtures.

## 6. Unifying the 253 conflicts

`tools/unify_duplicates.py`: for every record key with more than one English,
pick one text and write it to every row in the group -- in `en` where the row
has `en`, in `ref_en` where it has only `ref_en`. Choice order: a row with
`status=reviewed`; else the most frequent text; else the longest. Add a `note`
`unified with <file> <rec>[<idx>]`. Print the full list (file, record, index,
before, after). Run it, commit the table changes separately from the code, and
put the printed list in the commit message body. Then `giten check` must show
zero `overlay-conflict` errors on `tables/` **and** on `build/tables_draft`
after `python tools/make_draft_tree.py`.

## 7. Documentation

- `docs/overlay.md`: rewrite the format and lookup sections for v6; keep the
  history sections but mark the merged-buffer gate section as superseded, with
  one paragraph saying why identity binding was the wrong question.
- `docs/limits.md`: replace the overlay entries about `MS6xxx` never being
  served and the `0xE0` ids with one entry: what v6 does not know (identical
  records need identical English; records the engine mutates at runtime draw
  Japanese; text outside the interpreter fetch is not the overlay's).
- `docs/exe-patches.md`: the `.ovl` size row.

## 8. Build, install, verify against the real trace

    python -m tests.run
    python tools/make_draft_tree.py
    python -m giten overlay --text build/tables_draft
    python -m giten exe release
    python -m giten exe dev
    copy build/exe/dds.exe, build/exe/dds_dev.exe, build/overlay.dat
         -> C:\Giten Megami Tensei - English - v0.05\play\en\ddswin\

Before installing, replay the player's session offline: for every event in
`play/en/ddswin/trace.bin` (copy it first; the game truncates it on launch),
the v6 table must resolve the record the engine's index entry names, and the
count of events whose record has *no* entry must be explained (untranslated,
or a record the engine mutated -- report the top ten by count). Then confirm
the three symptom rows in section 0 resolve to the terminal's own English.

## 9. Definition of done

- `python -m tests.run`: all pass, no skips, no `NOT RUN` line.
- Mutation checks (a)(b)(c) each fail the named test and are restored.
- `giten check` on `tables/` and on `build/tables_draft`: 0 `overlay-conflict`.
- `hook.c` contains no reference to `FILEID`, `fp`, `MAX_MERGE`, `entry_fits`,
  `rebind`, or a per-file directory.
- The play install carries the new `dds.exe`, `dds_dev.exe`, `overlay.dat`,
  and `giten trace verify` on a fresh session judges every event with a
  context.

## Standing constraints

Never push. Never modify `original/ddswin`. Every byte of English must be
cp932-encodable. `v0.05` lines are drafts only. Commit messages end with
`Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Use Write/Edit for
any file content that has backslashes; shell heredocs mangle them here.
