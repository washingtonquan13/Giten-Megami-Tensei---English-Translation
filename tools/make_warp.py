"""Build a throwaway JP tree whose opening jumps straight to m/MS0031 r01.

`0C <file> <record>` is goto-record (0x00433E70 -> 0x00433D70), and the first
byte is the file: 2,713 of the 2,807 sites with a file id below 0xA0 resolve to
an `m/MS00xx` record that exists.  So three bytes are enough to send the
interpreter anywhere in that range without a save and without playing.

The injection point is `m/MS0017` r01, not `m/MS002D` r00: every trace on disk
runs MS002D r00,01,02,01,04 and *then* MS0017 r01, so patching the later one
lets the whole opening initialise first and only then warps.

m/MS0031 itself is left byte-identical -- it is the thing being measured.
"""
import io, os, shutil, sys
R = "C:/Giten Megami Tensei - English - v0.05/Giten Megami Tensei - English Translation"
sys.path.insert(0, R); os.chdir(R)
from giten import container, files, records, script, vmops

SRC, TARGET_REC = "m/MS0017.BIN", 0x01
OUT = sys.argv[1]
#: goto m/MS00<file>.BIN record <rec>; defaults to m/MS0031 r01
FILE_ID = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x31
REC_ID = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x01
WARP = bytes([0x0C, FILE_ID, REC_ID])

raw = files.read_source(SRC, "original/ddswin")
conts, end = container.split(raw)
assert end == len(raw) and conts, "not a clean container chain"

bodies = [c.body for c in conts]
b = records.parse_body(bodies[0])
assert b.error is None, b.error
# round-trip check before touching anything
assert records.serialise_body(b) == bodies[0], "record layer does not round-trip"

rec = next(r for r in b.records if r.id == TARGET_REC)
old = rec.data
print("%s r%02X: %d bytes, starts %s" % (SRC, TARGET_REC, len(old), old[:12].hex(" ")))
rec.data = WARP + old[len(WARP):]
assert len(rec.data) == len(old), "length changed"
print("   patched to %s  (0C %02X %02X = goto m/MS%04X.BIN r%02X)"
      % (rec.data[:12].hex(" "), FILE_ID, REC_ID, FILE_ID, REC_ID))

bodies[0] = records.serialise_body(b)
new_raw = container.join(bodies)
assert len(new_raw) == len(raw), (len(new_raw), len(raw))

# prove nothing else moved
c2, _ = container.split(new_raw)
b2 = records.parse_body(c2[0].body)
diff = [r.id for r, s in zip(b2.records, b.records) if r.data != s.data]
assert diff == [], diff
same = sum(1 for r, s in zip(b2.records, records.parse_body(bodies[0]).records)
           if r.data == s.data)
print("   container rebuilt: %d bytes, %d records, only r%02X differs from the original"
      % (len(new_raw), len(b2.records), TARGET_REC))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
io.open(OUT, "wb").write(new_raw)
print("wrote %s" % OUT)

# and confirm the warp tiles as one 0C token
sc = script.parse(SRC, new_raw)
r = next(x for c in sc.containers for x in c if x.id == TARGET_REC)
t = vmops.tokenize(r.data)[0]
print("first token now: idx=0x%03X size=%d bytes=%s"
      % (t.idx, t.size, r.data[:t.size].hex(" ")))
