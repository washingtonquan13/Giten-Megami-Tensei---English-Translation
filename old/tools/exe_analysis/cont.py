"""Multi-container parser matching dds_en.exe 0x43AA90 / 0x43AB10 exactly."""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')
ROOT = r"C:\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin"

def unxor(enc, seed):
    out = bytearray(len(enc)); prev = seed
    for i, b in enumerate(enc):
        out[i] = b ^ prev; prev = b
    return bytes(out)

def enxor(plain, seed):
    out = bytearray(len(plain)); prev = seed
    for i, b in enumerate(plain):
        prev = b ^ prev; out[i] = prev
    return bytes(out)

def seed_of(hdr): return ((hdr >> 8) ^ (hdr & 0xFF)) & 0xFF

def split_containers(raw):
    """Yield dicts describing each container in the file."""
    out = []; p = 0
    while p + 2 <= len(raw):
        hdr = int.from_bytes(raw[p:p+2], 'little')
        if hdr == 0: break
        enc = raw[p+2:p+2+hdr]
        if len(enc) < hdr:
            out.append(dict(off=p, hdr=hdr, body=unxor(enc, seed_of(hdr)),
                            short=True)); break
        out.append(dict(off=p, hdr=hdr, body=unxor(enc, seed_of(hdr)), short=False))
        p += 2 + hdr
    return out, p

def parse_records(body):
    """Emulate 0x43AA90's record loop. Returns (count, records, endpos, err)."""
    if len(body) < 2: return 0, [], 0, 'no count'
    count = int.from_bytes(body[0:2], 'little')
    p = 2; recs = []
    for k in range(count):
        if p + 3 > len(body): return count, recs, p, 'truncated at rec %d' % k
        rid = body[p]; ln = int.from_bytes(body[p+1:p+3], 'little')
        if ln == 0xFFFF:
            if p + 7 > len(body): return count, recs, p, 'truncated cond rec %d' % k
            cond, param = body[p+3], body[p+4]
            ln = int.from_bytes(body[p+5:p+7], 'little'); hl = 7
        else:
            cond = param = None; hl = 3
        if p + hl + ln > len(body): return count, recs, p, 'record %d overruns' % k
        recs.append(dict(id=rid, len=ln, off=p+hl, hl=hl, cond=cond, param=param,
                         data=body[p+hl:p+hl+ln]))
        p += hl + ln
    return count, recs, p, None

def recompute_hdr(recs):
    """The rule an inserter must use."""
    return 2 + sum((7 if r['cond'] is not None else 3) + len(r['data']) for r in recs)

def build_container(recs):
    body = bytearray(len(recs).to_bytes(2, 'little'))
    for r in recs:
        body.append(r['id'])
        if r['cond'] is not None:
            body += b'\xff\xff' + bytes([r['cond'], r['param']]) + len(r['data']).to_bytes(2, 'little')
        else:
            body += len(r['data']).to_bytes(2, 'little')
        body += r['data']
    hdr = len(body)
    return hdr.to_bytes(2, 'little') + enxor(bytes(body), seed_of(hdr))

if __name__ == '__main__':
    import collections
    files = []
    for d in ('m', 'et', 'p'):
        dp = os.path.join(ROOT, d)
        for f in sorted(os.listdir(dp)):
            if not f.upper().endswith('.BIN'): continue
            if d == 'et' and (f.startswith('A') or f.startswith('CA')): continue
            files.append((d + '/' + f, os.path.join(dp, f)))
    stats = collections.Counter(); bad = []
    multi = []
    for name, path in files:
        raw = open(path, 'rb').read()
        conts, endp = split_containers(raw)
        allok = True; ncont = 0; nrec = 0
        for c in conts:
            if c['short']: allok = False; break
            cnt, recs, end, err = parse_records(c['body'])
            if err or end != c['hdr']:
                allok = False; break
            ncont += 1; nrec += len(recs)
            if recompute_hdr(recs) != c['hdr']: allok = False; break
        leftover = len(raw) - endp
        if allok and ncont and leftover == 0:
            stats['clean multi-container'] += 1
            if ncont > 1: multi.append((name, ncont, nrec))
        elif allok and ncont:
            stats['containers + %d leftover bytes' % 0] += 1
            bad.append((name, ncont, leftover, 'leftover'))
        else:
            stats['not a container file'] += 1
            bad.append((name, ncont, leftover, 'parse fail'))
    print("files:", len(files))
    for k, v in stats.items(): print("  %-40s %d" % (k, v))
    print("\nmulti-container files: %d (showing 25)" % len(multi))
    for m in multi[:25]: print("   %-16s containers=%-4d records=%d" % m)
    print("\nnon-clean: %d (showing 40)" % len(bad))
    for b in bad[:40]: print("   %-16s ncont=%-4d leftover=%-8d %s" % b)
