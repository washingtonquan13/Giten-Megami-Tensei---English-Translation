# How long the tools take, and why

Measured on the machine the translation is being built on (16 logical cores,
Python 3.12.10, Windows 11).  Every number here is wall time for the command as
written, from a cold process, with nothing else running.

The baseline artefacts live under `build/speed-baseline/` (not in git --
`build/` is ignored).  Each command's stdout is saved next to the files it
produced, and every later change is checked by re-running the same commands and
diffing every byte: the reports and `overlay.dat` and all 212 extracted tables
have to come back identical, or the change is wrong.  Two independent baseline
captures were diffed against each other first, to prove the artefacts are
deterministic and usable as an oracle: 225 files, 0 differ.

## The baseline (2026-09-11, before any of this work)

| command | wall |
|---|---|
| `python -m tests.run` (full suite, serial) | **341.9 s** (329 passed, 2 failed) |
| `python -m giten check --skip-identity --show 0` | 13.0 s |
| `python tools/screen_audit.py …roppongi-textout.bin --trace …roppongi-trace.bin` | 20.9 s |
| `python -m giten overlay --text build/tables_draft --out …/overlay.dat` | 6.3 s |
| `python -m giten extract --text …/extract` | 4.6 s |
| `python -m giten trace verify …roppongi-trace.bin --build <play install>` | 2.3 s |
| `python -m giten tile census` | 2.0 s |

The two failing tests --
`test_observe_agrees_with_the_engine_on_the_roppongi_session` and
`test_the_roppongi_session_verifies_clean_once_the_stale_records_are_named` --
fail **before** any of this work and for reasons that have nothing to do with
it: both are pinned to counts taken against a particular `build/overlay.dat` and
a particular play install, and both have since been rebuilt.  They are recorded
here so that "the same tests pass afterwards" means the same *set*, not a
smaller one.

## Where the time actually goes (measured, not assumed)

`script.parse`, `objdump` and `gcc` were wrapped in a counter and the whole
suite re-run under it:

| cause | calls | time | share of the 335 s suite |
|---|---|---|---|
| `giten.script.parse` | 9 318 | 76.3 s | 23 % |
| `objdump` subprocesses | 786 | 38.6 s | 12 % |
| `gcc` subprocesses | 22 | 19.4 s | 6 % |
| other subprocesses | 227 | 13.0 s | 4 % |
| everything else (pure Python in the tests themselves) | -- | 188 s | 55 % |

And per tool:

| tool | total | in `script.parse` | parses |
|---|---|---|---|
| `check --skip-identity` | 12.6 s | 7.3 s (58 %) | 777 |
| `tile census` | 1.8 s | 1.7 s (94 %) | 217 |
| `overlay` | 6.1 s | 2.0 s (32 %) | 191 |

One full pass over the corpus -- 844 files, 20 690 records, 44 774 spans,
~773 000 tokens -- costs **2.4 s**.  `check` does four of them in one process,
which is what 777 parses and 7.3 s mean: the same bytes, tiled from scratch,
four times.

Two things the original diagnosis expected are **not** true on this machine and
were left alone rather than "fixed":

* `trace verify` on the Roppongi trace takes **2.3 s**, not two and a half
  minutes.  It reads 272 405 records and already avoids `script.parse` entirely
  (`trace.core.corpus_records` goes straight to the container layer, with a
  comment saying why).  Vectorising it could save at most a second or so of a
  342-second suite, against a real risk of changing a report that is an
  oracle for two other tests, so it was not done.
* the objdump-based expression-table test does not cost ~100 s on its own; the
  786 objdump calls are spread across `test_v2`, `test_opcode_10` and
  `test_handler_determinism`, and the largest single test is 10.1 s.
