# Route: Baal Cult Branch (`m/MS0031`) — settles both open model questions

`m/MS0031` is `バール教団　支部`, the **Baal Cult Branch**, and record **0:01**
alone carries both of the model's remaining open questions.  One traced visit
to that scene answers both; nothing else needs to be played.

## Why this record

Record 0:01 is the reunion with 泪 (Rui).  She checks the player over
(`ちょっとだけ、脈とか見させてね‥‥`), then either `うん、健康そのものだね。` or
`ん、健康そのものだね。` depending on which reading is right — and later cries
`バカバカバカ！　いきなり消えたりして‥‥`.

| offset | question |
|---|---|
| `0x0108` | `10 01 00 0f` immediately after `1F 00` — is the engine's PC ever 0x0108? |
| `0x0227` | the second such site, where the shorter reading resolves to a real `1F 00` |
| `0x012A` | expression selector `1F` — kind 13, `u8 + expr` per the engine, `u8` per the corpus |
| `0x01F3` | the second kind-13 expression |

## What each answer means

**Opcode `10`.**  Our tiler makes the token six bytes and resumes the text at
`ん、健康そのものだね。`, which cannot begin a Japanese sentence.  The engine's
dispatch tables say six bytes is right; `10`'s own branch target is `0x010C`,
which is exactly where `うん` starts.  The trace logs the interpreter's PC, so
it says directly whether the PC is ever `0x0108`, and where it goes next.

**Expression kind 13.**  Selectors `0x19`–`0x23` reach `0x00436C49` →
`0x00438C40`, an unconditional `READ_U8` then an unconditional `read_expr`, so
the engine reads `u8 + expr`.  But 79 records tile only if it is `u8` alone.
No trace on disk has ever reached the *start* of a kind-13 token (50 sit in
traced records on paths never taken), so this is the first observation of one.

Both are recorded in `docs/limits.md`.  **Neither may be "fixed" from corpus
evidence alone** — that is how the `1F 0D` revert (`pre-expr-model`, b22272e)
happened the first time.

## How to run it — no save, no playthrough

`0C <file> <record>` is goto-record, and the first byte is the file (2,713 of the
2,807 sites with a file id below 0xA0 resolve to an `m/MS00xx` record that
exists).  So three bytes send the interpreter anywhere in that range.

`tools/make_warp.py` writes an `m/MS0017.BIN` whose record 0x01 begins
`0C 31 01` — go to `m/MS0031.BIN` record 0x01.  **`m/MS0017` r01 is the
injection point, not `m/MS002D` r00**, because every trace on disk runs
`MS002D` r00, 01, 02, 01, 04 and *then* `MS0017` r01: patching the later one lets
the whole opening initialise and only then warps.  `0C` never returns, so the
rest of that record is simply not reached.  `m/MS0031` itself is untouched — it
is the thing being measured.

**`play/warp` is already built and installed.**  It is a copy of `play/jp` whose
only difference is that one file (`diff -rq` says so), and it carries the same
`dds_dev_jp.exe` with the v2 tracer.  To rebuild it from scratch:

```
python tools/make_warp.py <somewhere>/MS0017.BIN 31 01
cp -r play/jp play/warp && cp <somewhere>/MS0017.BIN play/warp/ddswin/m/
rm -f play/warp/ddswin/trace.bin
```

Then:

1. Run `play/warp/ddswin/dds_dev_jp.exe` and start a **New Game**.  The opening
   initialises and the game drops straight into the Rui reunion — no save
   needed, and nothing has to be played to get there.
2. Advance the dialogue with Enter until the scene ends (a dozen presses; the
   two `10` sites are at 0x0108 and 0x0227 of the record, i.e. early).  A crash
   afterwards does not matter — the tracer writes one `WriteFile` per token, so
   the kernel already holds everything logged.
3. Copy `play/warp/ddswin/trace.bin` to `build/trace/jp-ms0031.bin`.
4. Decode **against the tree that ran**:

```
python -m giten trace decode build/trace/jp-ms0031.bin     --dir "C:/Giten Megami Tensei - English - v0.05/play/warp/ddswin"
```

The Japanese install is the oracle either way: on `play/en` every PC inside a
translated span is incomparable by construction, because the engine runs 1-byte
English while the tokenizer tiles 2-byte Japanese.

## Reading the result

* Every event must pass the decoder's self-check (`ok`).  Events that fail it
  are not evidence — see the stale-globals note in `docs/limits.md`.
* For `10`: look for an event in `m/MS0031` r01 with `pc0 == 0x0108`.  If it is
  there, the engine executes the token and the next `pc0` gives its true size.
  If the PC jumps from before `0x0106` straight to `0x010C`, those bytes are
  never executed and the text starts at `うん`.
* For kind 13: find an event whose `pc0` is the start of the token holding the
  expression at `0x012A`; the next `pc0` is the token's true end.  Our tiling
  and the `['u8']` alternative differ by one byte, so a single event decides it.
