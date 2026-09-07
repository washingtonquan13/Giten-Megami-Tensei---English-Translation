# Plan: stop shipping bugs of our own making

Written 2026-09-07, after a week in which three of my own proposals died on
contact with the binary and one claim I stated as structural turned out to be
untested.  The ordering below is chosen from what has actually broken this
project, not from what feels risky.

## The evidence this is built on

| cause | incidents |
|---|---|
| byte-rebuilt **script** data — relocated or unrelocated branches | **3 blockers** |
| **injected code that allocates** (`database.S`) | **2 crashes** |
| bad reference *content* promoted into tables | doubling, speaker tags |
| length-preserving constant rewrites (xp, locale, pace, popup) | **0** |
| pointer rewrites (`.nam`, `.men`) | **0** |

Two categories hurt us: **rewriting bytes the interpreter executes**, and
**code that allocates**. Constant rewrites have a perfect record.

"A pristine exe" is not achievable and is the wrong goal: strings that live in
`.rdata` need *something* to redirect them, and after this week's digging the
definition site is provably the only stable anchor — the engine copies strings
into a scratch buffer with 271 writers before drawing, and two of its six
draw-string routines take a window id rather than a pointer.

The achievable goal is: **every change is in a category with a clean incident
record, and a test exists that would catch a regression in it.** We have the
first half. Step 1 is the second half.

---

## Step 1 — `giten trace verify`: prove flow equality from one trace  **[A]**

**Why first.** I told the user the overlay could not affect flow. That was an
assumption I had never tested; when pushed, one of its two mechanisms turned
out to be checkable and I found we serve eight distinct flow-opcode *byte
values*. They are all operands of inline opcodes — but nothing was checking,
and `tests/test_v2.py` gained that check only after the question was asked.

Everything else in this plan is a change. Build the oracle before making more
changes.

**What it does.** For every token in an English trace, classify its PC:

* **outside any served span** — the byte at that PC in the *original* file must
  equal the logged `ch`. The overlay must not have touched it.
* **inside a served span or virtual tail** — the token must be text or a
  whitelisted inline op, never a flow opcode (`0C`, `0D`, `10`–`18`).
* every virtual PC must fall inside a tail range the overlay declared for that
  file, and the rejoin must land on that span's recorded `end`.

**Why one session is enough.** The overlay's contract is local: substitute
within a span, rejoin at `span.end`. If every token dispatched outside a span
matches the Japanese bytes, and every token inside one is text, then the
instruction stream the interpreter followed *is* the Japanese instruction
stream. No second play-through of the same route is needed, which is what made
the two-build `trace diff` expensive enough to keep being deferred.

**Risk:** none. Read-only analysis of files already on disk.

**Done when:** it runs against `traces/2026-09-06b-murmur.bin` and
`traces/2026-09-07-en-dev.bin` and either reports clean — the overlay is
exonerated over those routes — or names the first divergent token. Then it goes
in the test suite against a committed trace so a regression is caught by
`python -m tests.run`, not by play-testing.

**Honest limit:** it proves flow equality *on the routes traced*, not
universally. Coverage grows with play. That is still infinitely more than the
zero evidence we have today.

---

## Step 2 — extend the overlay to `et/ID*`  **[A−]**

The last 17 byte-rebuilt scripts: `ID0099`, `009B`, `009C`, `009D`, `009F`,
`00A2`, `00A3`, `00BB`, `00BC`, `00C1`, `00C2`, `00C3`, `00E9`, `00EC`, `012B`,
`0132`, `014E`. Sizes changed by **+25 to +156 bytes each**, so records move and
branches are relocated — the exact failure mode behind all three blockers, in
files that sit outside the mechanism built to prevent it.

They are excluded by one line in `overlay.plan()`:

```python
if r.edited and r.file.startswith("m/")
```

All 17 parse, have containers and records, and have **~63 KB of virtual room
each**. Nothing technical is stopping this.

**Sub-steps:**

1. **Fix `overlay._fid()` for `et/`.** It currently returns `0xD009` for
   `ID0099`, `ID009B` *and* `ID009C` — it parses the name as if it were
   `MS####`. Nothing may be keyed on the id until this is right.
2. **Establish the engine's runtime file id for `et/` scripts.** The unexplained
   ids `0x00FF` and `0x007F` in both traces may be exactly this. The dev tracer
   already logs `FILEID`, so one session that opens a demon conversation
   settles it. **This is the gate** — everything after it depends on the answer.
3. Extend `plan()` past the `m/` filter; two ids collide with `m/MS` (`0x0A2`,
   `0x0A3`) and the FNV-1a fingerprint over the live record index is what
   disambiguates them, which is what it exists for.
4. Verify with step 1.

**Risk:** it **fails closed**. A fingerprint mismatch means the hook serves
nothing and the file renders Japanese. It cannot corrupt. The real exposure is
a *coverage regression*: if we stop byte-rebuilding these and the overlay does
not serve them, the demon negotiation silently reverts to Japanese.

**Watch for:** the shop-text discovery. `m/MS01xx` is fully translated and
never executes through `exec_token`, so the overlay cannot reach it. If
`et/ID*` is driven the same way, step 2 buys nothing and we keep the byte
build. Sub-step 2 answers that before any work is wasted.

**Done when:** the 17 files are byte-identical to `original/`, the overlay
serves their spans, and a demon conversation reads English in play.

---

## Step 3 — B2: delete `database.py`  **[B]**

Trim the English item text by **5,592 bytes across 745 records — 7.5 bytes
each** so the body fits the stock `u16` offset table, rebuild `et/ET0001.BIN`
in place as `racenames` does for `ET0000`, and delete `giten/exe/database.py`:
48 bytes of replaced code, 196 bytes of our assembly, the `.idb` section, and
the coupling that makes an English exe die on a Japanese install.

This removes **the only module of ours that allocates memory**, and both
self-inflicted crashes came from it.

**Risk:** prose quality, not corruption.

* `build(parse(x)) == x` for all 745 records — the model is proven.
* `build()` replaces only the name/description tail; every type byte and binary
  header is carried through verbatim.
* Nothing addresses a record by offset: the locator `0x00422D10` reads
  `offset[index]` from the very table being rebuilt, so table and records move
  together by construction.
* The builder **refuses** to emit an over-ceiling body rather than truncating.
* The shipped build already has all 745 offsets shifted *and* a non-stock `u32`
  table. B2 keeps the shift and removes the width change — it makes the file
  **more** like the original, not less.

**Graded B, not higher:** smallest risk reduction of the three (61 bytes in
place, 512 appended — about 6%), highest content cost, and it is data-table
code with no branches, so it is not in the class that causes flow bugs.

**Done when:** the body is under 65,535, `ET0001.BIN` is rebuilt in place,
`database.py` and `.idb` are gone, and item names and descriptions read
correctly in a shop.

---

## Step 4 — leave the pointer rewrites alone  **[A, as a decision]**

~490 bytes across 117 sites in `names.py` and `menus.py`. They change *which
address a `push` names* — same instruction, same opcode, same length, same
order. No branch, no record length, no flag, no control flow. A soft lock
requires flow to diverge and there is nothing here for flow to depend on.

Zero incidents in the project's history, and the definition site is the only
stable anchor that exists. Doing nothing here is a decision, not an omission.

---

## Not doing: a menu overlay at the draw site

Recorded so it is not re-proposed. Three independent reasons, each checked:

* The **import slot cannot be patched on disk** — the loader overwrites
  `FirstThunk` with the resolved address at load time.
* The exe **never calls `TextOutA`**; it blits every character itself through
  `0x451230`.
* **String identity is destroyed before drawing.** Of the 39 call sites that
  pass a pointer, 29 pass one shared scratch buffer (`0x491340`, 271 writers
  across `.text`) holding already-formatted text, and 8 pass static addresses
  that are padding and fragments. The other 32 sites reach variants that take a
  **window id**, not a pointer.

`menus.py` is already an overlay in every sense that matters — English in an
appended section, originals untouched, redirection at a single stable point,
and **zero of our code running**. It hooks the definition rather than the draw
because the draw has nothing left to hook.

---

## Ordering, and why

1 before 2 because step 2 is itself a change and should land against a working
oracle. 2 before 3 because 2 removes the class that has caused three blockers
and 3 removes a module that has caused two crashes in code with no branches. 4
is already done by not acting.

If only one thing gets built: **step 1**. It is the only item that makes the
other three verifiable, and the only one that could have answered the Murmur
question instead of leaving it open.
