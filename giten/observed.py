"""Records the engine has answered for, and what it said.

Two hand-written verdicts, each naming the trace that produced it.  They live in
a module of their own -- with no imports -- because both :mod:`giten.script`
(which has to know, while it is tiling, whether a record it cannot walk is one
the engine's own control flow passes over) and :mod:`giten.tile` (which scores
them against the census and re-checks them against the fixtures) need them, and
``tile`` imports ``script``.

Neither dict is an excuse.  ``tests/test_tile.py`` re-derives both against the
observed fixtures on every run: a ``dead`` record that starts tiling has to leave
the list, and an ``unreached`` record has to satisfy its own definition -- every
program counter the engine was seen dispatching at inside it is reproduced by the
model, and the offset the walk gives up on is never one of them.
"""
from __future__ import annotations

#: **``dead``** -- a warp put the interpreter on this record's first byte and the
#: process died there.  Every one is in a container the shipped game has no path
#: to (``docs/limits.md``: the loader was never missing, the *caller* is), so
#: what the engine executes in them is whatever bytes happen to be there.  Their
#: program counters are logged and reported, and deliberately **not** scored
#: against the model: an interpreter running off the end of a garbage table is
#: not evidence about the tokenizer.  Value: the trace, and what it shows.
#:
#: A dead record contributes no branch targets and is never served.  That is not
#: a gap in the container's target set: nothing executes these bytes, so there is
#: no branch in them to miss.
DEAD_RECORDS = {
    ("m/MS6200.BIN", 0, 0x16):
        "warp-MS6200-r16: one token dispatched, at 0x0000, and the trace ends "
        "there -- the process died (player's note: 'r16: crash')",
    ("m/MS6200.BIN", 0, 0x1F):
        "warp-MS6200-r1F: six tokens, then the trace ends.  The 0E at 0x000B is "
        "a table with keys 1F 54 0E 02 06 9F (not ascending) and kinds "
        "E5 09 12 1F 00 18; the engine read it, branched out of its sixth entry "
        "to 0x0027, took the 18 there to 0x004E and the process died",
    ("m/MS6200.BIN", 0, 0x55):
        "warp-MS6200-r55: the 0C in m/MS0017 r01 jumped to its base (0x0A00) "
        "and NOT ONE token was ever dispatched in it (player's note: "
        "'r55: crash')",
    ("m/MS6500.BIN", 0, 0xC7):
        "warp-MS6500-rC7: one token dispatched, at 0x0000, and the trace ends "
        "there (player's note: 'rc7: crash')",
    ("m/MS610D.BIN", 0, 0xFF):
        "warp-MS610D-c0-rFF: no token was ever dispatched in its bytes.  0xFF is "
        "the highest record id there is, so nothing follows it in any image and "
        "its final 1F 0D expression reads a byte the container does not contain; "
        "the run went to the buffer's last byte and then through 610,910 virtual "
        "program counters before the process died",
}

#: **``unreached``** -- the walk fails at an offset the engine's own control flow
#: passes over.  The condition is checked, not asserted (see
#: ``tests/test_tile.py``): every program counter the engine was observed
#: dispatching at inside the record is reproduced by the model -- as a token of
#: the walk up to its failure point, or by re-walking from an address the
#: model's own ``rel16``/straddle names -- and the failure offset is never one of
#: them.  So the record's *code* is tiled and understood; what is not is a run of
#: bytes nothing executes.
#:
#: Such a record therefore does have known branch targets, and
#: :func:`giten.script.image_walks` is where they come from: the union of the
#: walk from offset 0 and the walk from every address the container's own
#: ``rel16`` operands and straddles name.  That is what lets the overlay serve
#: the rest of the container under the strict rule.
UNREACHED_RECORDS = {
    ("m/MS0031.BIN", 0, 0x00):
        "warp-MS0031-r00: 86 boundaries, every one reproduced.  The record holds "
        "three copies of a nine-byte blob -- `3X 00 00 00` then five bytes -- "
        "between a `10` conditional and a pair of `18` jumps; the walk reads the "
        "first two (0x0020, 0x003E) as junk opcodes and stops on the third, at "
        "the `0F` at 0x0060.  Nothing enters them: the `1F 79` at 0x0011/0x002F/"
        "0x004D jumps over each blob to the second `18` (0x002C, 0x004A, 0x0068) "
        "and all three of those land on 0x006B, where the engine was observed "
        "drawing text",
    ("m/MS610D.BIN", 0, 0x1B):
        "warp-MS610D-c0-r1B: seven boundaries, six times over, every one "
        "reproduced.  The engine runs 0x0000, takes the `12` at 0x0002 to 0x0052 "
        "and never touches 0x0005..0x0051, where the walk stops on a `0F` at "
        "0x001C",
    ("m/MS610D.BIN", 3, 0xCE):
        "warp-MS610D-c3-rCE: four boundaries, five times over, every one "
        "reproduced (0x0000, 0x0006, 0x0009, 0x000B); the `0D` at 0x000B leaves "
        "the record every time, so the `0E` at 0x00A4 the walk stops on is never "
        "reached.  rCE is the last record of container 3, so that table has "
        "nowhere to terminate: it runs to the image end at 0x06AB",
}

#: Files the script loader can open but nothing ever enters.  Not a guess and not
#: "no caller found": ``m/MS0080``'s five records were each warped to, and each
#: dispatched exactly two tokens -- the ``1F 00`` no-op and the ``02 1F`` pool
#: call at 0x0002, whose return lands on the ``00`` terminator at 0x0004 -- and
#: drew nothing, five times out of five.  The shop dialogue at 0x0009 is never
#: reached from offset 0, and three independent searches (``docs/warp-trees.md``)
#: found nothing in any ``m/`` or ``et/ID*`` file, no loader immediate and no
#: merge path that names file ``0x80`` at all.
#:
#: Their records tile, so this costs the model nothing; what it costs is twenty
#: table rows that would have been translated for a screen no session reaches.
UNUSED_FILES = {
    "m/MS0080.BIN":
        "nothing enters this file: each of its five records was warped to and "
        "terminated after two tokens without drawing, and no operand, immediate "
        "or merge path in the game names file 0x80 (docs/warp-trees.md)",
}
