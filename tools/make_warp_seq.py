"""Warp through a *sequence* of records so one play session measures several.

`tools/make_warp.py` writes a single `0C <file> <rec>` (goto).  This writes a
list, so one run can call a record, come back, and then jump into another:

    python tools/make_warp_seq.py <out.bin> 0D:31:17 0C:31:02

`0D` is call-record (returns when the callee terminates) and `0C` is
goto-record (does not).  Put the calls first and one goto last.

WHAT THIS RUN IS FOR -- predictions registered before it is taken
================================================================
Three records in `m/MS0031` c0 -- 02, 03 and 17 -- end with a conditional
branch whose operands run one byte past the record, and whose final byte is
`00`, the terminator.  Every one of the 22 records in that container that *does*
tile ends with a `00` byte, 21 of them as a one-byte terminator token.

    r02  ... 0a 1d 01 | 18 00           opcode 18 = [rel16]
    r03  ... 0a 1d 01 | 16 00           opcode 16 = [rel16, expr]
    r17  ... 0a 1f 00 | 10 01 01 00     opcode 10 = [rel16, expr], selector 00 = [u8]

Our model says each spills into the *next* record, because the runtime image is
one flat buffer (`base(id) = 0x400 + sum of lengths`) with no end-of-record.

**Prediction A (our model is right).**  The engine reads `10 01 01 00 1F` at
r17+0x79 as five bytes and continues at r18+1, whose bytes are `d2 9f a3 81 46`
-- so the blitter draws `ﾒ泪：`, the same broken speaker label already confirmed
in r01.  The trace shows a token start at r17+0x79 and the next at r18+1.

**Prediction B (the `00` is the terminator).**  The run ends at r17+0x7C and the
`0D` returns.  That would mean either opcode `10` takes no expression here or
expression selector `00` is not `[u8]` -- and both are supposed to be settled,
`10` four ways on 2026-09-08 and the selector table 94/94 against the engine's
own two tables.  B therefore falsifies something we believe, which is the point
of running it rather than reasoning further.

Records 00 and 0D are deliberately NOT in this run: their walks fail on a switch
entry, and the tiling records show `31 14 ff` is switch *data* consumed by an
`0F`, so those two are misaligned upstream and a tail measurement would not say
where.  They need their own run once the upstream point is located.

The English tree is never touched: this is a diagnostic, not a build input.
"""
from __future__ import annotations

import io
import os
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)

from giten import container, files, records

SRC, TARGET_REC = "m/MS0017.BIN", 0x01
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(R, "build", "warp", "MS0017.BIN")
STEPS = sys.argv[2:] or ["0D:31:17", "0C:31:02"]

seq = bytearray()
for s in STEPS:
    op, fid, rid = (int(x, 16) for x in s.split(":"))
    assert op in (0x0C, 0x0D), "step %r: only 0C (goto) and 0D (call)" % s
    seq += bytes([op, fid, rid])
assert STEPS[-1].startswith("0C"), "the last step must be a 0C goto, not a call"

raw = files.read_source(SRC, os.path.join(R, "original", "ddswin"))
conts, end = container.split(raw)
assert end == len(raw) and conts, "not a clean container chain"
bodies = [c.body for c in conts]
b = records.parse_body(bodies[0])
assert b.error is None, b.error
assert records.serialise_body(b) == bodies[0], "record layer does not round-trip"

rec = next(r for r in b.records if r.id == TARGET_REC)
old = rec.data
assert len(old) >= len(seq), "r%02X is %d bytes, need %d" % (TARGET_REC, len(old), len(seq))
print("%s r%02X: %d bytes, starts %s" % (SRC, TARGET_REC, len(old), old[:12].hex(" ")))
rec.data = bytes(seq) + old[len(seq):]
assert len(rec.data) == len(old), "length changed"
for s in STEPS:
    op, fid, rid = (int(x, 16) for x in s.split(":"))
    print("   %s m/MS%04X.BIN r%02X" % ("call" if op == 0x0D else "goto", fid, rid))

bodies[0] = records.serialise_body(b)
new_raw = container.join(bodies)
assert len(new_raw) == len(raw), (len(new_raw), len(raw))

c2, _ = container.split(new_raw)
b2 = records.parse_body(c2[0].body)
before = records.parse_body(container.split(raw)[0][0].body)
changed = [(r.id, sum(x != y for x, y in zip(r.data, s.data)))
           for r, s in zip(b2.records, before.records) if r.data != s.data]
assert [c[0] for c in changed] == [TARGET_REC], changed
print("   rebuilt %d bytes; only r%02X differs (%d bytes)" % (len(new_raw), TARGET_REC, changed[0][1]))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
io.open(OUT, "wb").write(new_raw)
print("wrote %s" % OUT)
