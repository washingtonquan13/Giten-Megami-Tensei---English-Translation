# The opcode model: what it is, how it was verified, and how far to trust it

Written 2026-09-08, after the `m/MS0031` work accounted for the last untiled
record in a file the game can load. It exists so nobody re-opens a settled
question, and so nobody quotes a confidence number this evidence does not
support.

---

## 1. The short answer

**There is no known defect in the opcode model anywhere in the corpus.** Every
one of the 73 records that will not tile is explained, and none of them is a
tokenizer error.

That is not the same as "100% correct". Section 5 says exactly where the
remaining uncertainty is, and it should be quoted alongside the number.

---

## 2. What the model is

A script record is a flat byte string walked left to right. A byte `>= 0x20`
starts text (two bytes if it is a Shift-JIS lead). Otherwise it is an opcode:
`1D`, `1E`, `1F` are escape prefixes that add `0x300`/`0x200`/`0x100` to the next
byte; everything else indexes directly. The index selects an operand list, the
operands are consumed, and the walk continues.

Operands are fixed (`u8`, `u16`, `u32`, `rel16`) or variable:

| variable operand | used by | shape |
|---|---|---|
| `expr` | many conditionals | a recursive tree; first byte selects the node |
| `switch` | `0E`, `0F` | entry table, kind-tagged |
| `pairs_ff` | `1F 03`, `1F 04` | 2-byte terms, ends on a first byte of `0xFF` |
| `rtstr` | `1F A7` | expressions until one reads `-1` |

The runtime image is **one flat buffer**, not a set of isolated records:

    0x000..0x3FF   256 entries of { u16 data_offset, u16 length }
    0x400+         records copied in id order, absent ids = one 0x00 byte

    base(id) = 0x400 + sum(length(j) for j < id)      length = 1 when absent

`rel16` targets are measured in that space. **There is no end-of-record at
runtime** — a token at the end of a record reads on into the next one. That fact
is what finally explained three of the six `m/MS0031` failures, and it is the
single most load-bearing thing on this page.

---

## 3. How it was verified — four independent methods

### 3.1 Walking the engine's handlers (code ground truth)

`tools/opcode_operands.py` decompiles each handler's control flow with objdump
and counts the operand reads on each path. Operands reach the VM through exactly
three readers, so an opcode's operand list *is* the sequence of reads its handler
performs:

    0x00438FA0  u8       0x00438FC0  u16       0x00438FE0  u32

Three rules, each learned by getting it wrong first:

* **Follow control flow, never a linear scan.** Handlers are jump-table cases
  that share epilogues and jump into one another, so "stop at the first `ret`"
  runs one case into the next. Two byte-scanning attempts both produced
  confident, wrong tables.
* **Reachability is not consumption.** *Every* handler can reach the byte fetch,
  because the expression reader does. What matters is the reads on the path, so
  `0x00436B00` / `0x00437490` are treated as one opaque `expr`.
* **Know every reader, or delegation looks like a leaf.** Missing `0x00438FE0`
  made expression selector `0x02` look like a leaf when it is a `u32`.

If different paths disagree, the opcode is reported as context-dependent rather
than given a constant list.

### 3.2 The expression table, against the engine's own two tables

`0x00436B00` reads a selector byte, bounds it at `0x5D`, maps it through the kind
table at `0x00437380`, and dispatches on `0x00437288`. Walking all 62 kind
handlers reproduces `docs/opcodes.json`'s `expressions.nodes` for **all 94
selectors, zero disagreement**. Pinned by
`test_the_expression_table_is_the_engines_own_two_tables`.

Selectors above `0x5D` are the nullary "invalid" kind and consume exactly the
selector byte. That is why a conditional whose operand is missing silently eats
the following text's lead byte — see 4.1.

### 3.3 Corpus consistency

20,617 of 20,690 records tile (99.65%). 242,590 of 242,752 opcode instances
(**99.9333%**) dispatch to a slot with a real handler; the remainder is 162 uses
of 10 slots the engine treats as no-ops.

This is the weakest of the four methods, because a model can be self-consistently
wrong. It is used to *find* candidates, never to settle them.

### 3.4 The engine's own program counter, and its glyph blitter

The dev build logs one record per `exec_token` call, so the engine's token
boundaries can be compared with ours directly. On the Japanese warp traces, with
data byte-identical to the original:

| | |
|---|---|
| engine token starts observed | 946 |
| matching our walk | 943 |
| startup artifact (`pc 0x03FF`, inside the index, before execution begins) | 2 |
| the **predicted** mid-record spill entry at `r18+0x01` | 1 |
| **unexplained disagreements** | **0** |

Separately the build logs every glyph it blits (`0x451230`, plus six draw-string
variants). That is a *different code path from the interpreter*, so it
corroborates without sharing an assumption. It produced the cleanest experiment
in the project — see 4.2.

---

## 4. The findings that cost the most to get right

### 4.1 Opcode `10` is four bytes. Do not "fix" it.

Ten spans in `m/MS0031` begin on the trailing byte of a two-byte character and
read perfectly one byte earlier — `｢きなり` for `いきなり`, `ﾚしい事情` for
`詳しい事情`, `ｳ事` for `無事`. Ten for ten. **It is still wrong.**

`10 01 01 82` is opcode, rel16 `01 01`, then `82` as the condition's expression
selector; `0x82 > 0x5D`, so the reader takes the nullary kind and consumes it —
and that byte is the lead byte of `い`. Confirmed four ways:

* the engine's pc goes `0x3F -> 0x43` and never lands on `0x42`;
* the blitter drew `｢きなり、倒れるんだもん。`;
* all ten rel16 targets are `token + 0x104`, a constant, while the fourth byte
  varies (`82`, `8F`, `96`) — so that byte is not part of the target;
* the handler walk gives `(0 u8, 1 u16, 0 u32, 1 expr)` on every path.

**The garbled character is the 1997 script's own bug**, visible on screen in
Japanese. The author left the condition operand short.

### 4.2 The same marker drawn two ways in one session

`m/MS0031` r17 has no terminator, so execution spills into r18 **one byte late**.
Both records open with the same speaker marker `[1FD2] 泪 ： [1FD3]`:

| entry | drawn |
|---|---|
| r17 at offset 0 | `泪：‥‥なによ！` — clean |
| r18 at offset 1, by the spill | `ﾒ泪：うふっ、それで` — garbled |

Same bytes, two renderings, decided only by the entry point. Predictions were
registered in `tools/make_warp_seq.py`'s docstring **before** the run, A vs B, so
the result could not be read either way afterwards.

### 4.3 A record in the shipped game crashes it

`m/MS0031` r02's closing `18` reads its rel16 as `00 1F` — its own last byte plus
r03's first — and branches to `0x0C9D + 0x1F00 = 0x2B9D`, past the `0x2457` end of
the image. Reached by warp, the dialogue plays and the process dies.

### 4.4 Every untiled record, accounted for

| cause | records |
|---|---|
| dead data after a terminator (`00` = `or ax,0xFFFF; ret`) | `m/MS0031` r00, r0D |
| operand spills past the record | r02, r03, r17 |
| the corpus's one unterminated `pairs_ff` | r0B |
| files with no loader found | 67 |

`pairs_ff` earns its own line. The loop at `0x0042FEB0` terminates only on a
first byte of **exactly `0xFF`**, costing two bytes:

    call 0x4393e0        ; *a = first & 0x7F, *b = second; returns -1 if first & 0x80
    cmp  bx,0xffff       ; bit 7 set?
    jne  body            ; no -> evaluate the pair and loop
    cmp  ax,0x7f         ; set, and (first & 0x7F) == 0x7F -> first byte is exactly 0xFF
    je   terminate

**916 of 919 sites terminate inside their own record.** The three that do not are
r0B and two byte-identical copies of one record in `m/MS6F00`/`m/MS6F1F`, which
are not script at all.

---

## 5. What is NOT established

Quote this section alongside any confidence number.

1. **374 of 768 dispatch slots never occur in the corpus.** Nothing validates
   them. "100%" can only ever mean 100% of what this game contains.
2. **The `switch` reader deliberately diverges from the engine.**
   `vmops._read_switch` refuses entries with kind >= 2; the engine tests
   `kind != 0` and would follow them. The refusal is a desync detector, not a
   claim about the engine — such entries point at an instruction about 8% of the
   time. Relaxing it is a known trap.
3. **10 used slots are marked no-op** (162 uses; `1F 00` alone is 135). They
   consume prefix+byte and do nothing, which tiles fine, but reaching one usually
   means the walk is a byte out.
4. **Runtime verification is a small sample**: 946 token starts on two Japanese
   traces. The nine full play traces ran on English builds whose bytes differ
   from source, so they cannot be checked this way without rebuilding against the
   served image. That is the cheapest available improvement to this page.
5. **The 67 untiled records are in files with no loader *found*** — not proven
   unreachable. `0x0043AD20` is a generic `m/MS%04X` loader taking a 16-bit id
   whose caller chain was never traced to immediates. See `docs/limits.md`.
6. **`m/MS0031` may itself be unreachable**, which would make its six records moot
   rather than fixed. One `0C`/`0D` reference exists corpus-wide (r1B) and the
   file appears in none of 668,311 traced events — but those sessions are all
   early-game and this is plainly a late-game scene.

---

## 6. The standing lesson

**Text that reads better one byte over is not evidence.** Five rules in one month
looked decisive and were wrong on the corpus: "pure hiragana is grammar", "no
kana means data", "the clothing-radical block means data", "an operand ending on
a lead byte swallowed a character", and "opcode `10` is three bytes".

Settle opcode questions with the engine's program counter, its glyph log, or a
handler walk — never with a reading. And **register predictions before the run**;
that is what made the r17/r02 result unarguable.
