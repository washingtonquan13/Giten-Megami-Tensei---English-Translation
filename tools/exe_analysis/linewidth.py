"""linewidth.py -- measure rendered line widths in the shipped script data.

The renderer (0x445410) advances the cursor by 1 column for a byte < 0x100 and
2 columns for a 2-byte Shift-JIS character, one column = 8 px. A line ends at
opcode 0x0A (newline) or at 1E 10 (wait/page break). This walks every record and
reports the distribution of line widths in columns, which must sit under the
per-window column budget in the geometry table at 0x46D030.
"""
import os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from cont import ROOT, split_containers, parse_records
from vm import tokenize, files

BREAK = {0x00A, 0x210, 0x000}          # newline, wait/page, end-of-record

def widths():
    hist = collections.Counter(); worst = []
    for name, path in files():
        raw = open(path, 'rb').read()
        conts, endp = split_containers(raw)
        if not conts or endp != len(raw) or any(c['short'] for c in conts): continue
        for ci, c in enumerate(conts):
            cnt, recs, end, err = parse_records(c['body'])
            if err or end != c['hdr']: break
            for r in recs:
                d = r['data']
                if not d: continue
                toks, st = tokenize(d)
                if st: continue
                col = 0; start = 0
                for off, kind, idx, n in toks:
                    if kind == 'text':
                        col += 2 if n == 2 else 1
                    elif idx in BREAK:
                        if col:
                            hist[col] += 1
                            worst.append((col, name, ci, r['id'], start))
                        col = 0; start = off
                if col: hist[col] += 1; worst.append((col, name, ci, r['id'], start))
    return hist, worst

if __name__ == '__main__':
    hist, worst = widths()
    tot = sum(hist.values())
    print("text lines measured: %d" % tot)
    run = 0
    for w in sorted(hist):
        run += hist[w]
        if w % 4 == 0 or w >= max(hist) - 3:
            print("  <=%3d cols : %6d  (%.3f%%)" % (w, run, 100.0*run/tot))
    print("\nmax = %d columns" % max(hist))
    worst.sort(reverse=True)
    for w in worst[:12]: print("   %3d cols  %s#%d id=0x%02x @0x%x" % w)
