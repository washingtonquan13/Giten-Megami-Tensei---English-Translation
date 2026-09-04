"""Tokenize Giten script records using the opcode table recovered from dds_en.exe.

Validation harness: if the operand-length table is right, every record in every
container must tokenize to exactly its stored length. Run this after changing
opcodes.py to confirm nothing regressed.
"""
import os, sys, re, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
TBL_TXT = os.path.join(HERE, 'opcode_table.txt')

def load_table(path=TBL_TXT):
    """idx -> operand byte count; missing/None = unimplemented no-op (0 operands)."""
    t = {}
    for l in open(path, encoding='utf-8'):
        m = re.search(r'idx=0x([0-9a-f]{3}).*operand_bytes=(-?\d+)', l)
        if m: t[int(m.group(1), 16)] = int(m.group(2))
    return t

def is_lead(b): return 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xFC

def tokenize(data, tbl):
    """Yield (offset, kind, bytes). kind in {'op','text','end'}. Raises on overrun."""
    i = 0; n = len(data); out = []
    while i < n:
        b = data[i]
        if b == 0x00:
            out.append((i, 'end', data[i:i+1])); i += 1; continue
        if b >= 0x20:
            ln = 2 if (is_lead(b) and i + 1 < n) else 1
            out.append((i, 'text', data[i:i+ln])); i += ln; continue
        # control byte
        if b in (0x1D, 0x1E, 0x1F):
            if i + 1 >= n: raise ValueError('escape at end')
            idx = {0x1D: 0x300, 0x1E: 0x200, 0x1F: 0x100}[b] + data[i+1]
            hl = 2
        else:
            idx = b; hl = 1
        nops = tbl.get(idx, 0)
        if nops < 0: nops = 0
        if i + hl + nops > n: raise ValueError('operands overrun at 0x%x idx 0x%03x' % (i, idx))
        out.append((i, 'op', data[i:i+hl+nops]))
        i += hl + nops
    return out

def main():
    from cont import ROOT, split_containers, parse_records
    tbl = load_table()
    ok = bad = 0; recs_total = 0
    badlist = []; opuse = collections.Counter()
    for d in ('m', 'et', 'p'):
        for f in sorted(os.listdir(os.path.join(ROOT, d))):
            if not f.upper().endswith('.BIN'): continue
            if d == 'et' and (f.startswith('A') or f.startswith('CA')): continue
            raw = open(os.path.join(ROOT, d, f), 'rb').read()
            conts, _ = split_containers(raw)
            for ci, c in enumerate(conts):
                cnt, recs, end, err = parse_records(c['body'])
                if err: continue
                for r in recs:
                    if not r['data']: continue
                    recs_total += 1
                    try:
                        toks = tokenize(r['data'], tbl)
                    except Exception as e:
                        bad += 1
                        if len(badlist) < 25:
                            badlist.append(('%s/%s#%d id=0x%02x' % (d, f, ci, r['id']), str(e)))
                        continue
                    # a well-formed record ends with exactly one terminating 0x00
                    if toks and toks[-1][1] == 'end' and sum(1 for t in toks if t[1] == 'end') == 1:
                        ok += 1
                    else:
                        bad += 1
                        if len(badlist) < 25:
                            badlist.append(('%s/%s#%d id=0x%02x' % (d, f, ci, r['id']),
                                            'terminator count %d' % sum(1 for t in toks if t[1] == 'end')))
                    for off, k, bs in toks:
                        if k == 'op':
                            idx = ({0x1D: 0x300, 0x1E: 0x200, 0x1F: 0x100}[bs[0]] + bs[1]
                                   if bs[0] in (0x1D, 0x1E, 0x1F) else bs[0])
                            opuse[idx] += 1
    print("records tokenized cleanly: %d / %d   (failures: %d)" % (ok, recs_total, bad))
    for b in badlist: print("   FAIL", b)
    print("\ndistinct opcodes actually used in the data: %d" % len(opuse))
    return opuse, tbl

if __name__ == '__main__':
    opuse, tbl = main()
    print("\nmost-used opcodes:")
    for idx, c in opuse.most_common(40):
        lab = ("%02X" % idx if idx < 0x100 else
               "1F %02X" % (idx - 0x100) if idx < 0x200 else "1E %02X" % (idx - 0x200))
        print("   %-8s operands=%-3s uses=%d" % (lab, tbl.get(idx, 'unimpl'), c))
