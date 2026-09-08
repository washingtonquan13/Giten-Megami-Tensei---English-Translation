# Recovered interpreter traces

`*.bin` is gitignored, so these files are **not in git** — they live here only so a
reinstall of `play/` does not destroy them. Back them up with the repo if you care
about them.

| file | what |
|---|---|
| `2026-09-06-en-dev.bin` | The first real play session on record. `dds_dev.exe` + the draft overlay, English. The machine lost power mid-session and the trace still came out clean: 150,019 complete 20-byte records, no torn tail. It is what `docs/playtest-2026-09-06.md` cites throughout, and it settled reports 2 and 7. |

Decode with `python -m giten trace decode traces/<file> --build <tree the trace ran on>`.
A `selfcheck` mismatch rate of roughly the served share is expected when the trace
ran with an overlay and the check is against the Japanese `m/` — see the reading
notes at the end of `docs/playtest-2026-09-06.md`.

| `2026-09-07-glyphs.bin` | The menu-overlay spike's answer: 47,192 glyphs / 2,777 runs from a shop-and-status session. Read with `giten trace textout`. |
| `2026-09-07-en-dev.bin` | The interpreter trace from that same session, which is what proved the shop text never runs through the interpreter. |

| `2026-09-08-warp31-fallthrough.bin` | The trace that closed the opcode `10` question. `tools/make_warp.py` into `m/MS0031` r01 plus `tools/make_fallthrough.py` redirecting that record's opening `1F 04` branch from 0x019F to 0x0014, so the engine executes the disputed region instead of jumping over it. 496 records; 44 token starts inside r01, **all 44 on one of our boundaries**. The engine's pc goes 0x3F -> 0x43 across the `10 01 01 82` at 0x3F, so the token is 4 bytes and the following text really does begin on a trailing byte. |
| `2026-09-08-warp31-glyphs.bin` | The glyph log from the same session — the independent confirmation, because the blitter is not the interpreter. It drew `ああ、やっと気がついた。｢きなり、倒れるんだもん。心配したわよ。`: the engine itself renders the broken `｢`. Read with `giten trace textout`. |

| `2026-09-08-warp17-spill.bin` | The run that settled `m/MS0031` r02/r03/r17. `tools/make_warp_seq.py` wrote `0D 31 17` then `0C 31 02` into `m/MS0017` r01, with `m/MS0031` **byte-identical to the original**. Predictions were registered before the run. Result: **A**. r17 has no terminator -- 74 tokens execute past its end, the first at r18+0x01 reading `ch=0x00D2`, the bare trailing byte. r02's closing `18` reads its rel16 as `00 1F` (its own last byte plus r03's first) and branches to **0x2B9D, past the 0x2457 end of the image** -- the crash the player saw. |
| `2026-09-08-warp17-glyphs.bin` | The glyph log from that session, and the cleanest evidence in the project: the *same* `[1FD2]泪：[1FD3]` marker drawn twice, `泪：` when r17 is entered at offset 0 and `ﾒ泪：` when r18 is entered at offset 1 by the spill. One session, one marker, two renderings, decided purely by entry point. |
