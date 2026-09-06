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

## How to run it

The Japanese install is the oracle: on `play/en` every PC inside a translated
span is incomparable by construction (the engine runs 1-byte English while the
tokenizer tiles 2-byte Japanese).

1. Run `play/jp/ddswin/dds_dev_jp.exe` — already installed, already the v2
   tracer (it carries the `GTRC` magic; `dds_dev.exe` beside it is v1 and does
   **not** log `pc0`).  It writes `trace.bin` into that folder.
2. Reach the Baal Cult Branch and play the reunion with Rui through to the end
   of the conversation.  Keep the visit short — the smaller the trace, the
   easier the read.
3. Copy `play/jp/ddswin/trace.bin` to `build/trace/jp-ms0031.bin`.
4. Decode and read the answer:

```
python -m giten trace decode build/trace/jp-ms0031.bin \
    --dir "C:/Giten Megami Tensei - English - v0.05/play/jp/ddswin"
```

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
