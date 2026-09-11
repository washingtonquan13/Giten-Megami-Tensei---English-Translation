# How long the tools take, and why

Measured on the machine the translation is being built on (16 logical cores,
Python 3.12.10, Windows 11).  Every number is wall time for the command as
written, from a cold process, with nothing else running.

## The oracle

The baseline artefacts live under `build/speed-baseline/` (not in git --
`build/` is ignored).  Each command's stdout is saved next to the files it
produced.  Every change below was checked by re-running the same commands into
`build/speed-postwork/` and diffing every byte: the reports, `overlay.dat` and
all 212 extracted tables have to come back identical, or the change is wrong.

Two independent baseline captures were diffed against each other first, to
prove the artefacts are deterministic and therefore usable as an oracle:
**225 files, 0 differ**.  After every change since: **225 files, 0 differ**.

The only normalisation the comparison applies is the absolute path of the
capture directory itself, which some reports print.  Nothing else.

## Before and after

| command | before | after | |
|---|---|---|---|
| `python -m tests.run` (full suite) | **341.9 s** serial | **50.4 s** default (12 workers) | 6.8x |
| `python -m tests.run -j1` | 341.9 s | **121.1 s** | 2.8x |
| `python tools/screen_audit.py …textout.bin --trace …trace.bin` | 20.9 s | **11.8 s** | 1.8x |
| `python -m giten check --skip-identity --show 0` | 13.0 s | **7.8 s** | 1.7x |
| `python -m giten overlay --text build/tables_draft --out …/overlay.dat` | 6.3 s | **4.2 s** | 1.5x |
| `python -m giten extract --text …/extract` | 4.6 s | **4.1 s** | 1.1x |
| `python -m giten trace verify …trace.bin --build <play install>` | 2.3 s | **2.3 s** | -- |
| `python -m giten tile census` | 2.0 s | **1.4 s** | 1.4x |

With every cache cold (a fresh clone, or straight after `rm -rf build/cache`)
the suite is **97.1 s** in parallel rather than 50.4 s, and it fills the caches
as it goes.

The suite is **338 tests, 0 failures, no `NOT RUN` line**, and the set of test
names is exactly the baseline's 331 plus the 7 added here.  Serial and parallel
report the identical set.  With every cache switched off --
`GITEN_NO_CACHE=1 python -m tests.run`, which is how to ask whether the cache is
at fault for something -- it is the same 338 tests, 0 failures, in 109.5 s.

### The slowest tests

| test | before | after |
|---|---|---|
| `test_the_expression_table_is_the_engines_own_two_tables` | 102.8 s | 3.3 s |
| `test_the_exe_is_only_as_patched_as_the_documentation_says` | 11.1 s | 10.3 s |
| `test_the_c_hook_stops_serving_when_the_buffer_is_swapped_under_the_handle` | 10.1 s | 3.0 s |
| `test_a_v4_trace_still_verifies_and_the_v5_fields_read_back_as_zero` | 8.8 s | 1.0 s |
| `test_no_span_ends_on_a_dangling_escape_prefix` | 6.6 s | 3.0 s |
| `test_a_record_finds_itself_in_the_merged_buffer` | 6.5 s | 2.8 s |

One test was 30% of the whole suite and nobody had noticed, because the list of
slow tests had only ever been eyeballed from a partial run.

## Where the time actually went (measured, not assumed)

`script.parse`, `objdump` and `gcc` were wrapped in a counter and the whole
suite re-run under it, before any change:

| cause | calls | time | share of the 335 s suite |
|---|---|---|---|
| `giten.script.parse` | 9 318 | 76.3 s | 23 % |
| `objdump` subprocesses | 786 | 38.6 s | 12 % |
| `gcc` subprocesses | 22 | 19.4 s | 6 % |
| other subprocesses | 227 | 13.0 s | 4 % |
| everything else, pure Python in the tests | -- | 188 s | 55 % |

And per tool:

| tool | total | in `script.parse` | parses |
|---|---|---|---|
| `check --skip-identity` | 12.6 s | 7.3 s (58 %) | 777 |
| `tile census` | 1.8 s | 1.7 s (94 %) | 217 |
| `overlay` | 6.1 s | 2.0 s (32 %) | 191 |

One full pass over the corpus -- 844 files, 20 690 records, 44 774 spans,
~773 000 tokens -- cost **2.4 s**.  `check` did four of them in one process,
which is what 777 parses and 7.3 s mean: the same bytes, tiled from scratch,
four times over.

## The parse cache

`giten/cache.py`, in front of `giten.script.parse`.

**The key** is a SHA-256 of

* the **raw file bytes** -- not its path or mtime, so a file copied in from
  another tree with the same contents is the same parse; and
* the **source text of every module that can change the answer**, read and
  hashed as bytes: `script.py`, `vmops.py`, `records.py`, `container.py`,
  `codec.py`, `spans.py`, `pool.py`, `partial.py`, `observed.py`, `loaders.py`,
  `files.py`, and `docs/opcodes.json`.

**The invalidation rule** follows from the key and needs no discipline: editing
one byte of any of those files changes the code digest, which changes every
entry's key, so every cached parse in the tree is unreachable from that moment.
There is no version constant to remember to bump.

The list cannot silently go stale either.
`test_every_module_the_parse_imports_is_on_the_key` walks `giten/script.py`'s
own import closure and fails if a module that shapes a parse is missing from it
(`cache.py` and `paths.py` are exempt and say why in the test).
`test_the_key_moves_when_any_module_that_shapes_the_answer_moves` appends a byte
to a **copy** of each keyed file in turn and asserts the digest moves -- a copy,
because a test that rewrites `giten/script.py` for a moment is a race against
every other worker once the suite runs in parallel.

**Storage** is `build/cache/parse/<first two hex digits>/<key>.pickle`, written
to a temp file in the same directory and `os.replace`d into place, which is
atomic on Windows and POSIX alike: two workers racing on one key both end up
with a complete file and neither can read a half-written one.  A failed write is
not an error -- the cache is an optimisation, and a read-only `build/` must not
stop a tool running.

**`GITEN_NO_CACHE=1`** bypasses the memo, the disk cache, and every other cache
in this document.  The equality test uses it: a child process parses all 844
files with the cache off and the parent compares every record, token, operand
and span **by value**.

### Two things that make it invisible rather than merely fast

**No caller ever receives an object another caller holds.**  A result that came
from the disk entry or from a real parse is already nobody else's and is
returned as it is.  Only a *memoised* result is shared, and that one is never
handed out: `_skeleton` rebuilds the `Script`, its `Rec` objects and their
`spans`/`tokens`/`flags` lists first.  This matters concretely --
`tests/test_partial.py` assigns `rec.tokens`, `tests/test_straddle.py` clears
it, `tests/test_overlay.py` recomputes `rec.spans`, and all three run in the
same process as everything else.  Tokens, operands, spans and the record bytes
*are* shared, because nothing in the tree assigns an attribute of one; copying
them would cost the entire saving and buy nothing.

**Nothing is memoised until it is asked for twice.**  Holding 844 parsed scripts
alive costs more in garbage collection than it saves when each file is wanted
once, which is exactly what `extract`, `overlay` and `tile census` do.  Measured:
an eager memo made `tile census` **0.4 s slower** -- 1.53 s of work inside the
process, and 0.69 s of interpreter teardown freeing a live set that a
single-pass run had never had to hold.  Remembering the key on first use and the
object only from the second makes one pass over the corpus pay nothing, and
still gives `check` -- four passes in one process -- every repeat for free.

## The other caches

All under `build/cache/`, all keyed on their own inputs' bytes rather than on
this package's source (`cache.raw_key`), so editing an unrelated module does not
throw them away.

* **`objdump`** (`build/cache/objdump`) -- each `_sweep` in
  `tools/opcode_operands.py`, keyed by the exe image's hash plus the address and
  window.  Deliberately **not** "dump `.text` once and slice it", which is what
  the timings invite: a linear sweep stays aligned only while it decodes real
  instructions, and the whole reason `_at` picks a base and sweeps from there is
  that a sweep started elsewhere drifts.  What is cached is each sweep exactly
  as issued.
* **`hook.c`** (`build/cache/hook`) -- `tracer.compile_hook_ex`'s
  gcc + ld + objcopy + nm, keyed on the contents of `hook.c` and `hook.ld`, the
  flags, the four numeric arguments and the toolchain.  1.31 s -> 0.10 s.
* **the C harness** (`build/cache/harness`) -- the linked `hook_harness.exe`,
  keyed on `hook.c`, `hook_harness.c`, `hook_harness.h`, the gcc command line
  and the toolchain.  Eight tests wanted the same binary.
* **test scheduling** (`build/cache/test-times.json`) -- module wall times, used
  to start the longest module first.  Scheduling only; it never changes which
  tests run or their order within a module.

"the toolchain" means the resolved path, size and mtime of each of
`gcc`/`ld`/`objcopy`/`nm` -- not the file contents (tens of megabytes, on every
call) and not `--version` (another subprocess).  Upgrading the compiler changes
all three.

## What was *not* a cache

Four of the changes are ordinary algorithm fixes that the profiler found once
the caching stopped hiding them.  Each returns the same value by construction:

* `tools/opcode_operands._at` asked "which known entry is the greatest one
  within 0x200 below this address" by **scanning the whole set**, once per
  instruction per path -- 3.5 million scans of a set that grows into the
  thousands, 64 of the 71 seconds that walk took.  It is a bisect now.  There is
  no second candidate to worry about: if the greatest entry at or below the
  address is too far away, every smaller one is further still.
* `trace.core._Image.locate` ran three linear passes over a record's whole token
  list per logged character, and recomputed the anchor count and owning span by
  scanning again.  A record's tokens tile its bytes, so no two end at the same
  offset and no two start at the same offset: a dict answers exactly what the
  first matching iteration answered.
* `overlay.plan` asked "does a token start where this span starts" with an
  `any()` over the record's token list, once per span -- 28.7 million
  comparisons a run.  It is a set built once per record.
* `container.unxor` had no loop-carried dependency and was written as though it
  did: `plain[i] = cipher[i] ^ cipher[i-1]`, with the seed standing in for
  `cipher[-1]`, is one XOR of the ciphertext against itself shifted a byte.
  numpy does it 20x faster (0.159 s -> 0.008 s over the corpus); the byte loop
  stays for hosts without numpy and for short bodies, and a test drives both
  paths over every container in the corpus.  `enxor` is **not** vectorised,
  because there each output byte depends on the previous *output*.

## The test runner

`python -m tests.run` runs test modules in parallel child processes; `-j1` is
the previous runner unchanged.  The default is still the **full** suite: no fast
tier, nothing skipped.

A child's output is relayed verbatim, so a test's own prints -- above all
`harness.build`'s `NOT RUN` line, the one thing that can make a green suite
meaningless -- appear where they always did, and a failure's traceback reads the
same however the suite was run.  This was verified against a probe module
holding a passing test, a failing one and one that prints `NOT RUN`: both modes
produce the same text and the same exit code.

The unit is the **module**, not the test.  A module is the only grouping whose
tests are known not to depend on the ones before them; several here share state
between their own tests on purpose, so splitting one across processes would be a
correctness change wearing a speed-up's clothes.  Each child is drained by its
own thread rather than a polling loop, so a module that prints a lot cannot fill
its pipe and stall while the parent is reading another.

## What was left alone, and why

**`giten trace verify` was not vectorised.**  The diagnosis expected it to take
two and a half minutes over 372 405 events; it takes **2.3 s** over 272 405, and
already avoids `script.parse` entirely -- `trace.core.corpus_records` goes
straight to the container layer, with a comment saying why.  Profiling it shows
no hotspot to vectorise: 3.2 s under the profiler, of which 1.0 s is the loop
body itself spread across the events and no single callee exceeds 0.25 s.  Bulk
struct decoding would save about a tenth of a second of a fifty-second suite,
against rewriting a report that two other tests use as an oracle.  The
`container.unxor` part of it *was* vectorised, because that one is provable in a
line.

**`test_the_exe_is_only_as_patched_as_the_documentation_says`** is now the
slowest test at 10.3 s.  It is not parse, objdump or gcc -- it applies and
re-reads the patch set -- and nothing about it was obviously cacheable without
weakening what it checks.

**Two Roppongi tests were failing before this work began**, for a reason that
had nothing to do with speed: they read their overlay from a tree that gets
rewritten (`build/overlay.dat` and the play install), and a trace only means
anything against the table that produced it.  They now read
`build/trace/overlay-as-run-2026-09-11.dat`, the copy archived the day the trace
was taken, and print a `NOT RUN` line naming it if it is absent rather than
judging the session against whatever else is lying around.

**`tools/handler_determinism.py --walk` reproduces `docs/handler-determinism.md`
in all but two rows**, and did so before this work too: the committed table
carries a longer hand-written rule for `0x1A7`/`0x1A8` than the generator emits.
The JSON the walk actually produces is identical.  Worth fixing, but it is not a
speed question.
