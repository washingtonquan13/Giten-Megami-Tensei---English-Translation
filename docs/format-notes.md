# Giten Megami Tensei — binary format notes (from `dds_en.exe` RE)

Status: living document. Every claim is tagged **[VERIFIED]** (read out of the
disassembly *and* cross-checked against decoded data files), **[CODE]** (read out of
the disassembly, not yet cross-checked against data) or **[HYPOTHESIS]**.

Tooling in `tools/exe_analysis/`: `pe.py` (PE parse), `da.py` (objdump wrapper,
VA-addressed), `xref.py` (references to a VA), `callgraph.py` (whole-`.text` call
graph incl. dispatch-table targets), `opcodes.py` / `opsem.py` (opcode table
extraction + classification), `cont.py` (container/record parser mirroring the
engine), `script_tokens.py` + `vm.py` (tokenizer / tiling proof).

PE facts (re-confirmed): ImageBase 0x400000, no `.reloc`. `.text` VA 0x401000 =
file 0x400; `.rdata` VA 0x464000 = file 0x62800; `.data` VA 0x468000 = file 0x65C00.

---

## 0. The container / record layer (supersedes "u16 header + XOR body")

**[VERIFIED]** A `.BIN` is a *sequence of containers*, not a single blob:

```
container := u16 hdr (plaintext) , hdr bytes of ciphertext
file      := container+
```

Decryption **[VERIFIED at 0x401B20 / 0x401B40]**:

```
prev = (hdr >> 8) ^ (hdr & 0xFF)          ; 0x401B20, state byte at ds:0x4712D0
for each ciphertext byte c:  plain = c ^ prev ;  prev = c
```

Same chained XOR the pipeline already uses, but the **seed is derived from the
header word**. For a single container where `hdr == len(body)` the old rule
`plain[i] = enc[i] ^ enc[i-1]` agrees; the rule above is the engine's.

Decrypted container body **[VERIFIED at 0x43AA90 / 0x43AB10]**:

```
body   := u16 record_count , record * record_count
record := u8 id , u16 len , len bytes                        (len != 0xFFFF)
        | u8 id , 0xFFFF , u8 cond , u8 param , u16 len , len bytes
```

The `0xFFFF` form is a *conditional* record: the engine calls `0x4394E0(cond, param)`
and if it returns non-zero it **skips** the record (`0x401C90`, read-and-discard)
instead of installing it.

*Engine quirk:* `0x401C90` does **not** advance the XOR state (`ds:0x4712D0` is never
updated in that loop), so a container in which a conditional record is actually
skipped decrypts to garbage from that point on. Treat conditional records as
"variants that must be taken". **[CODE]**

**Two separate layers, and they have different reach.** `cont.py` measures both:

| layer | files that satisfy it |
|---|---|
| container chain (u16 length hops landing exactly on EOF) | **842 / 844** — everything except `et/A0000` and `et/A0001` |
| record layer inside the container | **213** — `m/MS*` 198 of 200, `et/ID*` 15 of 17 |

So the container + chained-XOR layer is universal, but the *record* layer is only
used by the script families `m/MS*` and `et/ID*`. `m/M*` (map geometry, 109),
`et/CA*` (257), `et/ET*` (86) and `p/P*` (432) put a different structure inside the
container. `et/ET7F00.BIN`, for instance, decrypts to `u16 0` followed by 6-byte
`{u16 index, u16 kind, u16 offset}` entries pointing into a string blob — an index
table, not a record list. Those families were **not** analysed further here.

51 files hold **16 containers each** (`m/MS6xxx`, `et/ID*`); most others hold one.

---

## 1. Q2 — what the game does with the leading u16 **[VERIFIED]**

`0x43AD20(list, file_id)` → `0x401DD0(file_id, kind=9, 0)` (fopen router, §4) →
`0x43AA90(list, FILE*)`:

```
fread(&hdr, 2, 1, f)          ; the leading u16, read in the clear
if (result < 1) return
0x401B20(hdr)                 ; ONLY use: seed the XOR state (hdr>>8)^(hdr&0xFF)
count = read_u16_decrypted(f) ; the real record count
remaining = hdr - 2           ; computed, stored to a local, NEVER READ AGAIN
for (i = 0; i < count; i++)
    remaining -= install_record(list, f)
```

**Answer.** The header word is **not validated** as a length, count, id or checksum.
Its only functional role is as the **cipher seed**. The engine keeps `hdr - 2` in a
local and decrements it per record, but nothing ever tests that local — dead code.
The number of records comes from the **first decrypted u16**; the number of
containers is implied by "keep reading until the file runs out".

**Rule for an inserter.**
* Conventionally `hdr == len(container_body)`; `cont.py:recompute_hdr()` reproduces
  it exactly: `hdr = 2 + Σ (3 or 7 header bytes + len(data))` over records.
* Recompute it after an edit — not because the engine checks the length, but because
  **changing `hdr` changes the cipher seed**. Header and encryption must agree.
* Recipe (`cont.py:build_container()`): `hdr = len(new_body)`, then encrypt
  `new_body` with `seed = (hdr>>8)^(hdr&0xFF)`. Byte-identical to the original for
  every unmodified container.
* The previously reported "hdr != body length for 38 `m/MS6xxx`, all 17 `et/ID*`,
  and `et/ET0000/000C/000D/000F/0021/0100`" was an artefact of treating a
  **multi-container** file as one container. Under the container model each of those
  files' u16 length hops land exactly on EOF, with `hdr == len(body)` for every
  container. There is no second meaning to recover: the word is a length *and* the
  seed, and nothing else.

---

## 2. Q1 — the script VM

### 2.1 Execution model **[VERIFIED]**

Global `ds:0x491160` → script context:

| off | type | meaning |
|---|---|---|
| +0x02 | ptr | window / text-render state |
| +0x0A | u32 | handle of the loaded script buffer (`0x404680` → base pointer) |
| +0x0E | **u16** | **program counter**, a byte offset into that buffer |

The PC is **16-bit** — a loaded script buffer is hard-capped at 64 KiB.

Main loop (`0x439090`, `0x4390F0`, `0x439120`): `do { ch = next_char(); r = exec_token(ch); } while (r >= 0);`

* `next_char` = `0x439000` → `0x438F50` → `0x438F00`: read one byte; if it is a
  **Shift-JIS lead byte** (CRT `_mbctype` table at `0x490C11`, bit 4) read a second
  and return `(b1<<8)|b2`. On `0x00` it calls `0x433FB0` (end of record: pop /
  advance) and retries.
* `exec_token` = `0x439020`: printable char (`0x45B6B0`) → **draw** (`0x445410`);
  otherwise → dispatch as opcode via `0x42FF50`.

**Consequence — there is no "message opcode with a length field".** Text is **bare**
in the stream: any byte `>= 0x20` (plus the trail byte of an SJIS pair) is literal
text, and a text run ends at the next control byte. Nothing stores a text length
anywhere. *You can lengthen or shorten a text run without touching any length field.*
The earlier `0B <u16 len>` "show message" hypothesis is **wrong** — `0x0B` is a
conditional branch (§2.4).

Operand readers, all advancing the PC: `0x438FA0` = u8, `0x438FC0` = u16 LE,
`0x438FE0` = u32 LE (wrappers over `0x438E50 / 0x438E80 / 0x438EC0`).

### 2.2 Dispatch **[VERIFIED]**

`0x42FF50(op)`; `if (op > 0x2FD) no-op`; `jmp [0x4318B0 + op*4]`.

| encoding | index | note |
|---|---|---|
| `xx` (xx < 0x20) | `0x000..0x01F` | bare |
| `1F xx` | `0x100 + xx` | escape handler 0x42FF97 |
| `1E xx` | `0x200 + xx` | escape handler 0x42FF86 |
| `1D xx` | `0x300 + xx` | escape handler 0x42FF75 — always > 0x2FD, **always a no-op** |

Table size 0x2FE. **499 of 766 entries are implemented**; 267 point at the no-op
`0x4318AA`. An unimplemented opcode consumes **no** operand bytes.

### 2.3 Branch targets are PC-relative **[VERIFIED]**

`0x433EC0` (`read_reltarget`) is the only way an opcode obtains a jump target:

```
imm    = read_u16()                  ; PC now points just past the operand
target = (PC + imm) & 0xFFFF
```

`0x433C40` (`set_pc`) writes it back. **Every branch operand is a 16-bit
displacement measured from the byte immediately after the operand**, not an absolute
offset. (Values wrap mod 2^16, so a backward branch appears as a large u16.)

* A branch and its target with the edit *outside* the span between them need **no**
  change.
* If the byte count strictly between the end of the operand and the target changes,
  the displacement **must** be adjusted by the same delta.

### 2.4 Branch / offset-bearing opcodes **[VERIFIED, 141 opcodes]**

Layout for every conditional form is **`[u16 rel_target][condition operands]`** — the
target is read *first* (`0x434850` / `0x4348B0` / … all call `0x434680 → 0x433EC0`
before evaluating the condition). Semantics: `if (condition == 0) pc = target`, i.e.
**branch-if-false**.

| opcode | operand bytes | handler | meaning |
|---|---|---|---|
| `18 tt tt` | 2 | 0x4300ED → 0x433EE0 | **unconditional relative jump** (6883 uses) |
| `09 tt tt cc cc` | 4 | 0x42FFE5 → `0x434850(0,0)` | branch-if-false, compare form 0 |
| `0B tt tt cc cc` | 4 | 0x430008 → `0x434850(0,1)` | branch-if-false, compare form 1 |
| `10..17 tt tt ..` | 4 | 0x4348B0 family | branch-if-false, 8 comparison variants |
| `1F 58 tt tt` | 2 | 0x430655 → 0x433F10 | **gosub**: run at target, restore PC |
| `1F 79 .. 1F AA` | 2..6 | 0x430… | branch-if-false, flag/variable comparisons |

The machine-readable list is `docs/opcodes.json`; branch opcodes carry
`"offset_operand": {"at": 0, "size": 2, "kind": "pc_relative"}`.

### 2.5 Record-id / pool references — and the answer to Q3 **[VERIFIED]**

Opcodes **`0x01 nn` … `0x08 nn`** share handler `0x42FFC7`:

```
nn = read_u8()
0x433E40(op + 0x7EFF, nn)      ; op=1 -> 0x7F00 … op=8 -> 0x7F07
```

`0x433E40` → `0x433D70(file_id, record_no)` → `0x433CA0` (resolve) → `0x433C70`
(switch the context's script buffer + PC to that record, remembering
`ds:0x4911B0 = file_id`, `ds:0x4911B2 = record_no`).

`0x433CA0` resolves `file_id` against a linked list of loaded script files
(`ds:0x481688`, keyed by the u16 file id at offset 0), loading on miss via
`0x43B650 → 0x43AD20 → 0x401DD0(id, kind = 9, 0)`. **kind 9 is hard-coded** and its
format string is `m\ms%.4x.bin` (VA 0x46828C).

**Answer to Q3.** `08 nn` is **always** record `nn` of **`m/MS7F07.BIN`** — never
`et/ET7F07`, never a per-script or per-family selection. There is no selector opcode;
`ET7F00`'s `＠辞書n` strings are content, not a dispatch table. The full family:

| opcode | file |
|---|---|
| `01 nn` | `m/MS7F00.BIN` record `nn` |
| `02 nn` | `m/MS7F01.BIN` |
| `03 nn` | `m/MS7F02.BIN` |
| `04 nn` | `m/MS7F03.BIN` |
| `05 nn` | `m/MS7F04.BIN` |
| `06 nn` | `m/MS7F05.BIN` |
| `07 nn` | `m/MS7F06.BIN` |
| `08 nn` | `m/MS7F07.BIN` ← the "dictionary" (20 225 uses) |

Corroboration **[VERIFIED]**: `0x43B6C0` preloads exactly file ids `0x7F00 … 0x7F07`
plus `0xDB, 0xDC, 0xDD, 0xDE, 0xDF` at startup — and `m/` contains precisely
`MS7F00.BIN … MS7F07.BIN` and `MS00DB … MS00DF.BIN`, with no `MS7F08`. The record
number is a **u8**, so a pool addresses at most 256 records — matching the 256-entry
index the loader builds (§2.6).

`et/ET7F00.BIN` is loaded through a different subsystem (kind 11, `et\et%.4x.bin`)
and is unreachable from `01..08`.

### 2.6 Runtime buffer layout **[VERIFIED]**

`0x43AA30` allocates a per-file buffer of `0x500` bytes:

```
0x000 .. 0x3FF : 256 entries of { u16 data_offset, u16 length }
                 entry[i] = { 0x400 + i, 1 }
0x400 .. 0x4FF : 256 zero bytes (every record defaults to a single 0x00 = "empty")
```

`0x43ABC0` grows/shrinks the blob in place as records are installed, so at runtime

```
offset(record id) = 0x400 + Σ_{j < id} length(j)          (length(j) = 1 if absent)
```

Records live in the buffer in **id order**, not file order, and the PC is an offset
into this whole buffer. Consequences:

1. Record data is **contiguous** — a relative branch can legally jump into a
   neighbouring record.
2. **Changing the length of record `k` shifts every record with id > k**, so any
   *cross-record* relative branch spanning the edit must be fixed up. Intra-record
   branches, and branches whose endpoints both lie entirely before or entirely after
   the edit, are unaffected.
3. **No record may be longer than 0x7FFF bytes.** `0x43ABC0` computes
   `delta = new_length - entry.length` in 16-bit registers (`sub di, ...`), then
   `test di,di / jge grow` -- a *signed* test.  A record of 0x8000+ bytes (delta
   0x7FFF+ over the 1-byte placeholder) reads as negative, the shrink/move path
   runs with a bogus count, and the game crashes while loading the file.  The
   original never comes close (largest: `m/MS006A` r00, 28,291 bytes); an
   English BBS of 35,824 bytes crashed the terminal on 2026-09-04 and this is
   how it was found.  The 0x10000 image cap (u16 PC) is a separate, looser bound.

### 2.7 Answers to the pipeline team's specific questions **[VERIFIED]**

**(1) Confirmed: `01..08` → `m/MS7F00..MS7F07`, and how the id is derived.**
Handler `0x42FFC7` (shared by opcodes `0x01`–`0x08`):

```
42ffc7  call 0x438FA0        ; nn = read_u8()  -- ONE operand byte
42ffcc  movzx ax, al
42ffd0  add   esi, 0x7EFF    ; esi held the opcode index -> 0x7F00 + (op-1)
42ffd6  push  eax            ; record number
42ffd7  push  esi            ; file id
42ffd8  call  0x433E40       ; = push-return-context, then switch to file/record
```

so `file_id = opcode + 0x7EFF` exactly: `01`→0x7F00 … `08`→0x7F07, and the file id
is turned into a name by the kind-9 template `m\ms%.4x.bin` (§2.5). Spot check:
`m/MS7F00.BIN` record 3 decodes to `ニュートン`, matching the observed
`{01}{03}：` = "name #3, then a colon". Note `MS7F00` record 1 is itself
`08 02 08 33 00` — pool records may call other pool records; expansion is recursive.

`0x433E40` pushes the current position first (`0x43C1F0(ctx, 0)`), so `01..08` are
**calls**: the pool record runs, hits its terminating `0x00`, and control returns to
the byte after the operand. That is why a pool record inserts inline.

**(2) `0B` and `0C`/`0D` are not text and not dictionary refs.**

* **`0B tt tt aa bb`** (4 operand bytes) — handler `0x430008` → `0x434850(0, 1)`:
  read a PC-relative target (`0x434680`→`0x433EC0`), evaluate a condition
  (`0x434780(0,1)`), and branch if false. A **conditional jump**, nothing else.
  `09` is the same with `0x434850(0,0)`.
* **`0C ff nn`** (2 operand bytes) — handler `0x430019` → `0x433E70(0)`.
  `0x433C10` reads two bytes: the first is a **file id**, the second a **record
  number**; `0x433D70(file_id, record)` then switches the interpreter to that
  record. `0C` is a **goto** (no return context pushed).
* **`0D ff nn`** (2 operand bytes) — handler `0x430028` → `0x433E70(1)`, identical
  but routed through `0x433E40`, i.e. it pushes a return context first: a **call**.
  So `0D 7F 07` and `08` reach the same place; `01..08` are just one-byte shorthands
  for the eight pool files.

  The file id here is a full u8 and resolves through the same kind-9 template, so
  `0C DE nn` = `m/MS00DE.BIN` record `nn`. Ids `0xE0..0xFF` take a different path in
  `0x433CA0`: they are remapped per current map through `0x40EAA0`/`0x40E910`
  (index files `m/MS6800..MS6802.BIN`), i.e. "the script for *this* map, slot n".

**(3) `{DICT:92}` / `{DICT:96}` in `m/MS0061` do not exist — they were mis-tiling.**
Tiled with the corrected table (`tools/exe_analysis/vm.py`), `m/MS0061.BIN` contains
**no** `08` reference above 0x90 except a single `08 FF`. `MS7F07.BIN` is a *single*
container with 145 records, ids `0x00..0x90` contiguous. The earlier `92`/`96`
readings came from a tokenizer that mis-sized an earlier opcode's operands and
resynchronised one or two bytes off.

Even so, an out-of-range pool index is **harmless, not a crash**: `0x43AA30`
pre-initialises all 256 index slots to `{offset: 0x400+i, length: 1}` pointing at a
zero byte, so referencing an absent record expands to the empty string.

**Actionable rule for the pipeline: operand bytes are never text.** Every opcode
consumes a fixed, or expression-determined, number of bytes *before* the text run
resumes (`docs/opcodes.json`). The reported symptoms — `{0B}ｼ`, `{02}じゃd`,
`{03}バスターE` — are all "one or more operand bytes leaked into the following text
run", i.e. the tokenizer under-counted that opcode's operands.

### 2.8 Operands are typed slots, and many are *expressions* **[VERIFIED]**

An opcode's operands are an **ordered list of slots**. Slot kinds:

| kind | bytes | note |
|---|---|---|
| `u8` / `u16` / `u32` | 1 / 2 / 4 | little-endian literal |
| `rel16` | 2 | PC-relative branch displacement (§2.3) |
| `expr` | **variable** | a recursive expression tree |
| `list_ff` | **variable** | bytes up to and including a `0xFF` terminator |

**Expressions** (`0x436B00`) are the reason a naive fixed-width table cannot tile the
data. `eval()` reads one selector byte (valid range `0x00..0x5D`), dispatches through
the byte map at `0x437380` into the jump table at `0x437288`, and each node then
consumes its own payload — a `u8`, a `u16`, a `u32`, or one/two **nested
expressions**. Full node table in `docs/opcodes.json` under `expressions.nodes`;
`tools/exe_analysis/evaltab.py` regenerates it. Frequent nodes:

| node | payload | meaning |
|---|---|---|
| `00` | `u8` | unsigned byte literal |
| `01`, `05` | `u16` | word literal |
| `02` | `u32` | dword literal |
| `03` | `u8` | signed byte literal |
| `08`, `31`..`37` | — | 0-byte pseudo-values (`0x08` is the "no value" node) |
| `0B`, `0D`..`18` | `u16` | variable / flag reference by 16-bit index |
| `19`..`2F`, `38`..`5D` | `u8` + `expr` | binary ops: `u8` selector + one sub-expression |
| `06`, `07`, `4B`..`4F` | `expr` | unary ops |

`list_ff` currently has one member, `1E 1E` (handler `0x435CF0`): it scans the stream
to a `0xFF` sentinel, counts the entries, **rewinds the PC** and re-reads them — a
menu/choice option-id list. Verified against `m/MS0004.BIN` record 0x35, where
`1E 1E 00 FF`, `1E 1E 02 FF`, `1E 1E 03 FF`, `1E 1E 01 FF` tile the record exactly.

**One opcode's length depends on its own operand data:** `1E 10` (the wait /
page-break, 21 878 uses), handler `0x43C0C0`:

```
a = u8 ; b = u8 ; if (b == 0 || b == 2) a third u8 follows
```

so `1E 10 01 01` is 4 bytes but `1E 10 01 00 05` is 5. `docs/opcodes.json` marks it
`"operands": [{"kind": "rule:wait_1E10", "size": "var"}]`.

### 2.9 Proof: tiling the corpus **[VERIFIED]**

`tools/exe_analysis/vm.py` tiles every record of every record-structured `.BIN`
using nothing but the recovered tables. Result over **213 files / 20 226 non-empty
records**:

| outcome | records | |
|---|---|---|
| `ok` — every byte consumed, single trailing `0x00` | 18 913 | 93.5% |
| `stray0` — fully consumed, extra `0x00` inside | 1 060 | 5.2% |
| `unimpl` — fully consumed, but a byte hit a no-op table slot | 130 | 0.6% |
| `overrun` — operands ran past the record: **table still wrong** | 123 | 0.6% |
| **fully tiled, no unexplained byte** | **19 973** | **98.75%** |

Per file: **190 of the 213 tile with zero overruns**; all 123 overruns live in just
23 files (`m/MS0024, 0031, 0033, 0036, 0039, 003A, 003C-0040, 0042, 0054, 0080,
00B1, 00B8, 00D2, 610D, 6200, 6800` and 3 more - `vm.py` prints the list).

`stray0` is *not* a failure: a record legitimately holds several `0x00`-terminated
fragments entered by relative branches (`0x433FB0` handles a `0x00` by popping /
advancing). `unimpl` is not a failure either: `1F 00` (135 hits) and the whole
`1D xx` space dispatch to the shipped engine's no-op, consuming exactly two bytes.

The four requested files tile **end to end with zero unexplained bytes**:

| file | records | ok | stray0 | unimpl | overrun | bytes tiled |
|---|---|---|---|---|---|---|
| `m/MS0003.BIN` | 11 | 11 | 0 | 0 | **0** | 12 031 / 12 031 |
| `et/ID0099.BIN` | 8 | 8 | 0 | 0 | **0** | 1 756 / 1 756 |
| `m/MS0000.BIN` | 6 | 3 | 3 | 0 | **0** | 26 240 / 26 240 |
| `m/MS6000.BIN` | 1 927 | 1 835 | 91 | 1 | **0** | 20 356 / 20 356 |

Two structural cross-checks fell out of this and confirm the *relative* branch model
against real data:

* `m/MS0004.BIN` record 0x35 (a 93-byte 4-way choice) tiles to exactly 93 bytes, and
  its three `18` jumps (`18 24 00` @0x35, `18 17 00` @0x42, `18 0A 00` @0x4F) all
  resolve to offset **0x5C**, the record's terminating `0x00`. An absolute
  interpretation gives three different, meaningless targets.
* In the same record each `1E 12` (choice option) has `rel16 = 9`, landing precisely
  on the **next** `1E 12` — the "option not taken, try the next one" chain.

### 2.10 What still fails (honest) **[HYPOTHESIS for the fix]**

The 123 remaining overruns concentrate in about 20 opcodes and have one identified
cause: several shared helper routines read an **extra** operand only for particular
values of the *constant argument* their opcode stub passes them, and the static
tracer takes the fall-through path. Confirmed instances:

* `0x4335C0(arg)` — reads one extra `expr` **iff `arg == 0`**. Reached by `1F 4F`,
  `1F 50`, `1F 51`, … Evidence: `m/MS0033.BIN` record 0x17 tiles to exactly 65 bytes
  only if `1F 4F` / `1F 50` are `[expr, expr]` (4 operand bytes), whereas the tracer
  reports `[u8, u8, expr, expr]`.
* `0x434740(a, b)` — reads a third operand **iff `b == 1`**. Reached by `1F 7F`..`1F 8A`;
  `1F 7F` is really `[rel16, expr]` (`1f 7f 08 00 03 17`), not `[rel16, expr, expr]`.
* `0x4374A0` switches on the *value* of the preceding expression, so `10`..`17` and
  `1F 05`..`1F 0C` are probably data-dependent like `1E 10`.

The fix is a constant-propagating tracer (resolve `cmp [esp+K], imm` against the
stub's pushed arguments and follow only the taken edge), or hand rules for the ~8
shared helpers involved. `tools/exe_analysis/stubs.py` already extracts
`(callee, args)` for every opcode, which is the input that fix needs.

Practical impact: the affected opcodes are control-flow / variable plumbing, not
text. A record that fails to tile should be **left untranslated** rather than edited;
`vm.py` reports them by file / container / record id.

---

## 3. Q4 — line-width budget **[VERIFIED]**

### 3.1 Metrics

`0x445410` is the character emitter. It computes the advance as

```
width = (ch < 0x100) ? 1 : 2      ; columns
... lea ecx,[edi*8]               ; column -> pixels: ONE COLUMN = 8 PIXELS
```

so **half-width = 8 px = 1 column, full-width Shift-JIS = 16 px = 2 columns**, on a
640x480 screen. All engine budgets are expressed in columns, not pixels.

### 3.2 The engine auto-wraps, and the budget lives in a table

`0x453C50(win, width, slack)` is called before every character:

```
if (win.cur_col + width  >  win.max_cols + slack)   newline(win)   ; 0x453BF0
return (win.cur_line < win.max_rows) ? 0 : -1                      ; -1 = page full
```

* **Yes, the engine auto-wraps.** A too-long line is broken automatically; it is not
  clipped and it does not overflow the window.
* When the wrap would push past the last row, `0x445410` returns `0xFFFE` and the
  interpreter stops to wait for the reader — so `max_rows` is a real
  **lines-per-page** limit, not just a scroll hint.
* `slack` implements kinsoku shori: `-2` for ordinary characters, `0` for the closing
  set at VA 0x46A614 (`’ ” 〕 〉 》 」 』 】 、 ， 。 ． ！ ？` — allowed to hang past the
  margin), `-4` for the opening set at VA 0x46A638 (`‘ “ 〔 〈 《 「 『 【` — broken
  early so a bracket is never left dangling). **The effective budget for ordinary
  text is therefore `max_cols - 2` columns.**

Window geometry table: **VA 0x46D030, 24-byte entries `{x, y, w, h, cols, rows}`
(6 x int32), 37 entries (type 0..36)** — matching the 37 window slots at
`0x48FDA8..0x490A60` (stride 0x58). Indexing verified at `0x45216C`
(`lea ebp,[ebp+ebp*2]; shl ebp,3` = type x 24) and `0x452333` / `0x45233E`
(`win[+4] = entry.cols`, `win[+6] = entry.rows`).

| type | x | y | w | h | **cols** | **rows** | usable (`cols-2`) | role |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 328 | 640 | 152 | **76** | **6** | 74 | tall bottom message box |
| 1, 12 | 0 | 358 | 640 | 80 | **76** | **4** | 74 | standard bottom message box |
| 2 | 104 | 248 | 432 | 80 | 52 | 4 | 50 | narrow message box |
| 3 | 0 | 30 | 640 | 288 | 76 | 16 | 74 | full-screen text |
| 4 | 10 | 30 | 304 | 288 | 34 | 16 | 32 | left menu column |
| 5 | 40 | 40 | 196 | 168 | 24 | 9 | 22 | (script type 5 is remapped to 14) |
| 6 | 416 | 88 | 208 | 208 | 24 | 12 | 22 | right-hand list |
| 7, 8, 11 | 334 | 30/140/250 | 288 | 80 | 32 | 4 | 30 | small right boxes |
| 9 | 208 | 56 | 416 | 200 | 52 | 11 | 50 | |
| 10 | 10 | 30 | 280 | 288 | 34 | 16 | 32 | |
| 14 | 104 | 232 | 432 | 96 | 52 | 5 | 50 | what `1E 07 5` actually opens |
| 15 | 120 | 264 | 400 | 64 | 48 | 3 | 46 | |
| 16 | 416 | 116 | 208 | 112 | 24 | 6 | 22 | most-opened script window |
| 17 | 64 | 272 | 504 | 176 | 10 | 10 | 8 | |
| 18 | 24 | 80 | 288 | 136 | 34 | 11 | 32 | |
| 19 | 160 | 312 | 456 | 116 | 54 | 7 | 52 | |
| 21 | 464 | 56 | 152 | 272 | 18 | 16 | 16 | |
| 25 | 16 | 48 | 288 | 184 | 34 | 10 | 32 | |
| 26 | 56 | 40 | 528 | 288 | 64 | 16 | 62 | |
| 28 | 416 | 48 | 176 | 208 | 20 | 12 | 18 | |
| 30 | 130 | 32 | 352 | 184 | 42 | 9 | 40 | |
| 32 | 72 | 264 | 496 | 112 | 60 | 6 | 58 | |
| 33 | 304 | 48 | 256 | 184 | 30 | 10 | 28 | |
| 34 | 480 | 32 | 144 | 240 | 16 | 14 | 14 | |
| 35 | 490 | 32 | 136 | 160 | 15 | 1 | 13 | |
| 36 | 112 | 384 | 416 | 80 | 50 | 4 | 48 | |

(Entries 13, 20, 22–24, 27, 29, 31 are zero / partial placeholders.)

Scripts open windows with **`1E 07 <expr>`** (handler `0x430F74` → `0x42FC00`; note
`type == 5` is silently remapped to `type = 14`). `1E 08` closes. Literal types
actually used in the shipped data: `0` (60x), `5→14` (215x), `16` (1626x), `25` (4x),
`28` (66x), `35` (3x), `36` (1x). Narration and dialogue, however, are drawn into the
window the *interpreter* was started with (`0x439090` / `0x4390F0` / `0x439120`,
selected by `1F D0` / `1F D1`), which is the bottom message box — type 1/12,
**76 columns x 4 lines**.

### 3.3 Corroboration from the shipped English text

`tools/exe_analysis/linewidth.py` measures every rendered line (text runs delimited
by `0A`, `1E 10` and `0x00`) across all 213 script files — 38 305 lines:

| budget | lines within it |
|---|---|
| <= 40 cols | 64.4% |
| <= 52 cols | 78.5% |
| <= 64 cols | 91.0% |
| **<= 76 cols** | **98.74%** |
| max observed | **177 cols** |

The 76-column cliff matches the type 0/1/3/12 budget exactly. The 1.3% of lines above
it rely on the engine's auto-wrap (they break where the engine chooses, not where the
author intended) — i.e. the existing translation already overruns in about 500 places.

### 3.4 Choice options **[VERIFIED]**

Menus are `1F B1 <expr>` (open, 1 751 uses) … `1F B2` (next option, 4 613 uses) …
`1F B7` (close, 1 751 uses). Handler `0x430B22` → `0x43A750`:

```
w      = eval()                    ; the 1F B1 operand = per-option width IN COLUMNS
cell   = w + 2                     ; +2 columns (16 px) of selection-cursor gutter
ncols  = avail_width / cell        ; how many option columns fit; clamped to >= 1
```

So the per-option budget is **declared per menu by the `1F B1` operand**, and the
engine lays options out in an `ncols`-wide grid of `w + 2`-column cells.

Measured over the shipped data: **1 690 of 1 752 menus declare `w = 20`** (160 px =
20 half-width / 10 full-width characters); the rest use 4, 6, 8, 10, 12 or 14.
99.3% of the 4 630 shipped options fit inside their declared width; **34 already
exceed it** (worst: 31 columns against a declared 20, `m/MS006D.BIN` record 0x26).

**Concrete budgets to hand a translator**

| context | hard budget |
|---|---|
| narration / speech line | **74 columns** (76 minus the 2-column kinsoku slack) = 592 px |
| lines per page before a wait | **4** in the standard box, **6** in the tall one |
| choice option | **20 columns** (= 20 ASCII chars) in 96% of menus; read the `1F B1` operand for the rest |
| character cell | 8 px half-width, 16 px full-width |

---

## 4. Filename router (kind → path) **[VERIFIED]**

`0x401DD0(id, kind, flags)` first tries a per-id override, then `switch (kind)` via
the jump table at `0x402208`, `sprintf`s a name and `fopen(name, "rb")`
(CRT fopen = `0x45AC20`):

| kind | template | VA |
|---|---|---|
| 0 | `fc\fc%.4x.bin` (retries with `id & 0xFFF0`) | 0x4681C8 |
| 1 | `fc\fch%.4x.bin` | 0x4681F0 |
| 2 | `et\ca%.4x.bin` | 0x468204 |
| 3 | `m\m%.4x.bin` | 0x468218 |
| 5 | `s\sm%.3x.bin` | 0x46823C |
| 6 | `s\sb%.3x.bin` | 0x468250 |
| 7 | `s\st%.3x.bin` | 0x468264 |
| 8 | `s\se%.3x.bin` | 0x468278 |
| **9** | **`m\ms%.4x.bin`** — every script / pool file | 0x46828C |
| 10 | `p\p%.4x.bin` | 0x4682A0 |
| 11 | `et\et%.4x.bin` | 0x4682B0 |
| 13 | `et\id%.4x.bin` | 0x4682E4 |
| 15 | `fc\fc%.4x%01d.bin` | 0x468198 |

`ds:0x4716E0` holds the id of the file currently being opened.

---

## 5. Open questions / not settled

* **The remaining 0.6% of records (§2.10)** — cause identified, fix not implemented.
* **Which window instance the interpreter draws into** is passed *into*
  `0x439090` / `0x4390F0` / `0x439120` by the caller and selected by `1F D0` / `1F D1`;
  the static evidence points at the bottom message box (type 1/12, 76x4) but this is
  **[HYPOTHESIS]** rather than traced end to end. The 76-column cliff in the shipped
  data (§3.3) is strong corroboration.
* **The conditional-record XOR desync** (§0) is read off the code but has not been
  observed happening in a real file; no shipped container appears to skip a record.
* **`0x0F`'s operand list** — `docs/opcodes.json` says `[u8, u8, u16, u8]` (5 bytes),
  which tiles everywhere it was checked, but one site (`m/MS0061.BIN` record 0x0B,
  offset 0x3C) leaves a following `01 5C` / `08 FF` pair whose record ids do not exist
  in `MS7F00` / `MS7F07`. Harmless (absent records expand to nothing) but it hints
  `0x0F` may be data-dependent too. **[HYPOTHESIS]**

### 2.12 Switch tables: `0E` `0F` `1F11`-`1F16` `1F19`-`1F1E` `1DB0` `1DB1` **[VERIFIED by disassembly + trace, 2026-09-04]**

Sixteen opcodes share one parser, `0x4327C0` (via `0x432740`).  After the
opcode's key operands (below) comes a `0xFF`-terminated table of 4-byte cases:

```
[u8 case][u8 kind][rel16 target]      kind != 0 : branch to target (PC-relative, measured
                                                  from the byte after the rel16, like every rel16)
[u8 case][u8 kind][u8 file][u8 rec]   kind == 0 : leave for script file `file`, record `rec`
FF
```

| opcode | key | handler |
|---|---|---|
| `0E`, `1F11` | random 1..100; the first case `>=` the roll wins | `0x4328C0` |
| `0F`, `1F12` | the last menu selection (byte at `0x4919E0`); exact match | `0x4328E0` |
| `1F13`, `1F14` | `u8` selector + `expr`, then a party member's byte `+0x7A` | `0x432900` |
| `1F15`, `1F16` | `u8` selector + `expr`, byte `+0x7B` | `0x432930` |
| `1F19`, `1F1A` | `expr` value | `0x432960` |
| `1F1B`, `1F1C` | context byte `+0x1C4` (no operand) | `0x432980` |
| `1F1D`, `1F1E` | context byte `+0x1C5` (no operand) | `0x4329A0` |
| `1DB0`, `1DB1` | `expr` value, mode 1 | `0x4329C0` |

The second opcode of each pair passes `win=1` (a window is closed first); the
operand layout is identical.  Kind is only tested for zero, but no real table in
the corpus uses a value other than 0 or 1 (the 14 non-`0E`/`0F` opcodes are 100%
kind 1 and land on an instruction boundary 100% of the time), so the tokenizer
refuses any other value rather than tile a record it has already lost.

Why this matters: the recovered table typed all sixteen as `u8 u8 u16 u8` --
five bytes, no branch.  The room menu in `m/MS0017` r02 is
`0F | 00 00 6A 00 | 01 01 05 00 | 02 01 0F 03 | FF`: option 0 goes to file `6A`
(the BBS), option 1 jumps 5 bytes to the "too focused on the exam" line, option 2
jumps 783 bytes to the room exit.  The English build never relocated the 783, so
"leave" landed mid-record and re-ran the menu -- found by `trace diff` on
2026-09-04, and the mis-typing also hid it from `audit`.  Every `rel16` in a
table is now an ordinary operand, so relocation and `audit` treat it like any
branch; the trace's `0F->` events name the case taken.

### 2.11 `1F 01` -- print runtime string **[VERIFIED by trace + disassembly, 2026-09-04]**

Operands (handler `0x436920`, selector table `0x436A4C`, 20 cases): `[u8 selector]`,
then `[expr]` for selectors `04 05 06 0C 0D 0E 0F 11 13`, else `[u8][expr]`.  So
`1F01 08 00 04 FE` is one instruction -- selector 08 (a character's name), u8 00,
expr `04 FE` -- and the text after it (`：`) is the whole span.  The first model
(`1F01 nn` + a `00` end marker) was wrong: the `00` and `04 FE` were operands.
Found when the overlay served "Yuuka:" and the engine, consuming the first three
bytes as operands, displayed "ka:".  The string itself is executed as script
from its own buffer through a call frame (the trace's `pc=0` events).


`1F 01 nn` switches the interpreter to a runtime string buffer (the trace shows the PC at 0x0000 and Shift-JIS characters drawn from it until `00`), then returns. `nn = 00` is the player's name (葛城史人 by default); other indices print numbers (a `６` was observed). It is a real opcode with a real effect and must survive translation. The `00` that follows it in the data is the string terminator, not a fragment end.

---

## 6. The item / equipment / gem database `et/ET0001.BIN` **[VERIFIED by disassembly, 2026-09-05]**

### 6.1 On-disk layout

One container (`u16 hdr` + XOR body, body = 59,636 bytes in the original). The body is:

```
+0x0000  u16 count            = 745
+0x0002  u16 offset[count]    byte offsets into the body, monotonic, offset[0] = 2 + count*2
         records              variable length, addressed only through the table
```

A record is a binary header whose shape depends on a **type byte**, followed by
NUL-terminated cp932 strings: the display name, then the description. 744 of the 745
records carry text: 8,167 bytes of names and 34,569 bytes of descriptions.

The status-screen stat labels (直感 / 精神力 / 魔力 / 知力 / 加護力 / 強さ / 体力 /
敏捷性 / 器用さ / 魅力) live in here too, not in the exe.

### 6.2 The read path

| VA | what it does |
|---|---|
| `0x004232C0` | init: router(id=1, kind=0x0B) -> `0x401C30` -> image pointer stored at **`ds:0x4800E8`** |
| `0x00401C30` | reads **exactly one** container: one `u16` header, `0x4044C0` allocates, `0x401BA0` reads + decrypts. It does **not** walk the chain. |
| `0x00422D00` | `[0x4800E8]` -> `0x404680` -> body base pointer |
| `0x00422D10` | record locator. Clamps the index against `word [base]`, then **`0x00422D2B: mov dx, word ptr [eax + ecx*2 + 2]`** — the only read of the offset table — then `0x00422D32: call 0x40B840` |
| `0x0040B840` | `return base + (offset & 0xFFFF)`. **17 callers**, so it must not be patched in place. |
| `0x00422D40` | decodes one record into a 0x46-byte scratch struct (the shop/status code passes `0x4911C0`); `switch (type-1)` through the jump table at `0x00423180`, 0x13 cases; each case calls a small field-copier first (`0x4231D0` and neighbours) |

### 6.3 Why the file is capped at 65,535 bytes, and how to lift it

Three independent limits, all of them small patches:

1. **Container size.** `0x401C30` reads a single `u16` length. *Fix:* repoint only the
   `call 0x401C30` at `0x004232D3` to a new loader that walks the whole chain and
   concatenates, reusing `0x401B20` / `0x4044C0` / `0x401BA0`. The file stays a legal
   container chain, so `container.py` needs no change.
2. **`u16` offsets in the file.** *Fix:* widen the table to `u32` and patch
   `0x00422D2B` `66 8B 54 48 02` (5 bytes) to `mov edx, dword ptr [eax + ecx*4 + 2]`
   = `8B 54 88 02` + one `nop` — exactly 5 bytes, no relocation needed.
3. **The `& 0xFFFF` in the resolver.** *Fix:* repoint the `call 0x40B840` at
   `0x00422D32` to a private six-byte resolver in the appended section
   (`mov eax,[esp+8]; add eax,[esp+4]; ret`), leaving the other 16 callers alone.

With all three, the database can grow to whatever the offsets allow, which is enough
for English names *and* descriptions (the Japanese is 42,736 bytes; English needs
roughly +21,000).

### 6.4 Other menu strings

| element | where |
|---|---|
| system menu (オートマッピング / オートナビゲーション / ゲーム中断) | `.rdata` table at `0x00468310`: `u32 count=3`, then 6-byte entries `[u16 flag][u32 ptr]`; a second set of 2 follows at `+0x20` |
| equip labels (技能 命中 攻撃 回避 防御 弾数) | `u32` pointer array at `0x0046A148`, referenced from `0x00442A06` / `0x00442A54` |
| `所持アイテム %1d/8` | `0x0046A540`, pushed at `0x004448E4` |
| `合計 %10ld` | `0x00468DAC`, `0x00468DCC`, `0x00468DE4` |
| location indicator (`初台ｼｪﾙﾀｰ`) | the `m/M####.BIN` map files (a different family from `m/MS####`), stored as **half-width katakana** |

Both string tables are pointer arrays, so re-pointing them at an appended section is
the same technique as `giten/exe/names.py` — no push-immediate rewriting needed.
