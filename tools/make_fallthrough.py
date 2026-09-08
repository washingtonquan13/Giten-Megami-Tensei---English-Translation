"""Force the interpreter through a region it normally branches over.

`tools/make_warp.py` sends the interpreter to a record without a save or a
playthrough.  That is not always enough: `m/MS0031` r01 begins with a
multi-condition branch (`1F 04`) whose target is record offset 0x019F, so the
engine runs the token at offset 0 and jumps straight past 0x14..0x19E -- exactly
the region in dispute.  The 2026-09-06 warp trace shows it: the only program
counters logged inside that record are offset 0x1 and then 0x1A0 onward.

So this rewrites that branch's `rel16` to land on 0x14 instead.  Everything after
runs normally and the tracer logs the engine's own token boundaries across the
region, which is the ground truth no amount of reading the handler can supply --
`0x0042FEB0` was read twice today and answered a different question than the one
being asked.

    python tools/make_fallthrough.py <out.bin> [file_id] [rec_id] [new_offset]

Defaults to m/MS0031 r01 -> 0x14.  Writes one script file; drop it into a
JAPANESE install alongside the tree `make_warp.py` produced and run the dev exe.
The English tree is never touched: this file is a diagnostic, not a build input.
"""
from __future__ import annotations

import io
import os
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)

from giten import container, files, records, script, vmops

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(R, "build", "warp", "MS0031.BIN")
FILE_ID = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x31
REC_ID = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x01
NEW_OFF = int(sys.argv[4], 16) if len(sys.argv) > 4 else 0x14

REL = "m/MS%04X.BIN" % FILE_ID
raw = files.read_source(REL, os.path.join(R, "original", "ddswin"))
conts, end = container.split(raw)
assert end == len(raw) and conts, "not a clean container chain"

bodies = [c.body for c in conts]
body = records.parse_body(bodies[0])
assert body.error is None, body.error
assert records.serialise_body(body) == bodies[0], "record layer does not round-trip"

sc = script.parse(REL, raw)
base = records.bases([records.Record(r.id, r.data) for r in sc.containers[0]])[REC_ID]
rec = next(r for r in sc.containers[0] if r.id == REC_ID)
tok = rec.tokens[0]
rel = next((o for o in tok.ops if o.kind == "rel16"), None)
assert rel is not None, "the first token of r%02X has no rel16 to redirect" % REC_ID

old_target = vmops.rel16_target(base, tok, rel)
print("%s r%02X first token: idx=0x%03X, %d bytes, rel16 -> record offset 0x%04X"
      % (REL, REC_ID, tok.idx, tok.size, old_target - base))

# target = (base + op.off + op.size + imm) & 0xFFFF
pc_after = base + rel.off + rel.size
imm = (base + NEW_OFF - pc_after) & 0xFFFF
print("   redirecting to 0x%04X: rel16 0x%04X -> 0x%04X" % (NEW_OFF, rel.value, imm))

target = next(r for r in body.records if r.id == REC_ID)
d = bytearray(target.data)
d[rel.off:rel.off + 2] = imm.to_bytes(2, "little")
target.data = bytes(d)

bodies[0] = records.serialise_body(body)
new_raw = container.join(bodies)
assert len(new_raw) == len(raw), (len(new_raw), len(raw))

# nothing but those two bytes may have moved
c2, _ = container.split(new_raw)
b2 = records.parse_body(c2[0].body)
diff = [(r.id, sum(x != y for x, y in zip(r.data, s.data)))
        for r, s in zip(b2.records, records.parse_body(bodies[0]).records)
        if r.data != s.data]
assert not diff, diff
before = records.parse_body(container.split(raw)[0][0].body)
changed = [(r.id, sum(x != y for x, y in zip(r.data, s.data)))
           for r, s in zip(b2.records, before.records) if r.data != s.data]
assert changed == [(REC_ID, 2)], changed
print("   container rebuilt: %d bytes, only r%02X differs, by exactly 2 bytes"
      % (len(new_raw), REC_ID))

sc2 = script.parse(REL, new_raw)
r2 = next(x for c in sc2.containers for x in c if x.id == REC_ID)
t2 = r2.tokens[0]
print("   branch now targets record offset 0x%04X"
      % (vmops.rel16_target(base, t2, next(o for o in t2.ops if o.kind == "rel16")) - base))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
io.open(OUT, "wb").write(new_raw)
print("wrote %s" % OUT)
