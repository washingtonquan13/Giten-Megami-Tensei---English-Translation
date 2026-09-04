"""dumprec.py <dir/FILE.BIN> [container] [recid] -- hexdump + token listing of a record."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from cont import ROOT, split_containers, parse_records
from vm import tokenize, IMPL

def lab(i):
    if i is None: return 'text'
    return ("%02X" % i if i < 0x100 else "1F %02X" % (i-0x100)
            if i < 0x200 else "1E %02X" % (i-0x200) if i < 0x300 else "1D %02X" % (i-0x300))

def show(name, ci, rid, raw_only=False):
    path = os.path.join(ROOT, *name.split('/'))
    conts, _ = split_containers(open(path, 'rb').read())
    c = conts[ci]
    cnt, recs, end, err = parse_records(c['body'])
    for r in recs:
        if r['id'] != rid: continue
        d = r['data']
        print("%s cont=%d id=0x%02x len=%d cond=%s param=%s" % (name, ci, rid, len(d), r['cond'], r['param']))
        for i in range(0, len(d), 16):
            ch = d[i:i+16]
            print("  %04x  %-47s  %s" % (i, ' '.join('%02x' % x for x in ch),
                  ''.join(chr(x) if 32 <= x < 127 else '.' for x in ch)))
        if raw_only: return
        impl = IMPL
        toks, status = tokenize(d)
        print("  -- tokens (%s) --" % (status or 'complete'))
        run = b''
        for off, kind, idx, n in toks:
            if kind == 'text':
                run += d[off:off+n]; continue
            if run:
                try: t = run.decode('cp932')
                except Exception: t = repr(run)
                print("        text %r" % t); run = b''
            mark = '' if (impl is None or idx in impl) else '  <UNIMPLEMENTED>'
            print("  %04x  %-8s %s%s" % (off, lab(idx), ' '.join('%02x' % x for x in d[off:off+n]), mark))
        if run:
            try: t = run.decode('cp932')
            except Exception: t = repr(run)
            print("        text %r" % t)
        return
    print("record id 0x%02x not found" % rid)

if __name__ == '__main__':
    show(sys.argv[1], int(sys.argv[2]), int(sys.argv[3], 0))
