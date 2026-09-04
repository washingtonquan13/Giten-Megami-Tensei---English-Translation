"""vm.py -- tile Giten script records using the recovered opcode + expression tables.

Model (all verified against dds_en.exe, see docs/format-notes.md):
  * a byte >= 0x20 is literal text (2 bytes if it is a Shift-JIS lead byte)
  * 0x00 ends the current record fragment
  * 0x1D/0x1E/0x1F are escape prefixes -> index 0x300/0x200/0x100 + next byte
  * everything else is opcode index == the byte itself
  * an opcode's operands are an ORDERED list of u8 / u16 / u32 / expr / rel16 /
    list_ff, taken from opdesc.json
  * an 'expr' is a recursive expression tree, grammar in evaltab.json

Coverage metric, per record:
    ok       every byte consumed, exactly one 0x00 and it is the last byte
    stray0   tiled to the end but a 0x00 appears before the last byte (legal:
             records hold several 0x00-terminated fragments reached by branches)
    overrun  operands ran past the end of the record  -> table is wrong
    unimpl   a byte dispatched to an unimplemented table slot -> misalignment
"""
import os, sys, re, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')
from cont import ROOT, split_containers, parse_records

HERE = os.path.dirname(os.path.abspath(__file__))
OPDESC = {int(k): v for k, v in json.load(open(os.path.join(HERE, 'opdesc.json'))).items()}
EVALTAB = {int(k, 16): v for k, v in json.load(open(os.path.join(HERE, 'evaltab.json'))).items()}
IMPL = {k for k, v in OPDESC.items() if v['impl']}

FIXED = {'u8': 1, 'u16': 2, 'u32': 4, 'rel16': 2, 'expr2': 0}

def is_lead(b): return 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xFC
ESC = {0x1D: 0x300, 0x1E: 0x200, 0x1F: 0x100}

class Overrun(Exception): pass

def read_expr(d, i, depth=0):
    """Consume one expression tree at d[i:]; return the new offset."""
    if i >= len(d) or depth > 24: raise Overrun('expr at 0x%x' % i)
    b = d[i]; i += 1
    for a in EVALTAB.get(b, []):
        if a == 'expr': i = read_expr(d, i, depth + 1)
        else:
            i += FIXED[a]
            if i > len(d): raise Overrun('expr operand at 0x%x' % i)
    return i

# --- opcodes whose operand length depends on the operand data itself -------------
# 0x210 (1E 10) "wait / page break", handler 0x43C0C0:
#     a = u8 ; b = u8 ; if b == 0 or b == 2: c = u8
def _sp_1e10(d, i):
    if i + 2 > len(d): raise Overrun('1E10 at 0x%x' % i)
    b = d[i+1]; n = 3 if b in (0, 2) else 2
    if i + n > len(d): raise Overrun('1E10 at 0x%x' % i)
    return i + n

SPECIAL = {0x210: _sp_1e10}

def read_ops(d, i, ops):
    for a in ops:
        if a == 'expr': i = read_expr(d, i)
        elif a == 'list_ff':
            j = i
            while j < len(d) and d[j] != 0xFF: j += 1
            if j >= len(d): raise Overrun('unterminated list_ff at 0x%x' % i)
            i = j + 1
        else:
            i += FIXED[a]
            if i > len(d): raise Overrun('operand at 0x%x' % i)
    return i

def tokenize(data, strict=True):
    """-> (tokens, status). token = (off, kind, idx, nbytes)."""
    out = []; i = 0; n = len(data)
    while i < n:
        b = data[i]
        if b >= 0x20:
            ln = 2 if (is_lead(b) and i + 1 < n) else 1
            out.append((i, 'text', None, ln)); i += ln; continue
        if b in ESC:
            if i + 1 >= n: return out, 'escape at end 0x%x' % i
            idx = ESC[b] + data[i+1]; hl = 2
        else:
            idx = b; hl = 1
        try:
            if idx in SPECIAL:
                j = SPECIAL[idx](data, i + hl)
            else:
                j = read_ops(data, i + hl, OPDESC.get(idx, {}).get('ops', []))
        except Overrun as e:
            return out, 'overrun at 0x%x idx 0x%03x (%s)' % (i, idx, e)
        out.append((i, 'op', idx, j - i))
        i = j
    return out, None

def files():
    for d in ('m', 'et', 'p'):
        dp = os.path.join(ROOT, d)
        for f in sorted(os.listdir(dp)):
            if f.upper().endswith('.BIN'):
                yield d + '/' + f, os.path.join(dp, f)

def scan():
    tot = collections.Counter(); perfile = {}
    badop = collections.Counter(); unimpl_use = collections.Counter()
    fails = []
    for name, path in files():
        raw = open(path, 'rb').read()
        conts, endp = split_containers(raw)
        if not conts or endp != len(raw) or any(c['short'] for c in conts): continue
        st = collections.Counter(); good = True; nbytes = 0
        for ci, c in enumerate(conts):
            cnt, recs, end, err = parse_records(c['body'])
            if err or end != c['hdr']: good = False; break
            for r in recs:
                d = r['data']
                if not d: continue
                nbytes += len(d)
                toks, status = tokenize(d)
                if status:
                    st['overrun'] += 1
                    m = re.search(r'idx 0x([0-9a-f]{3})', status)
                    if m: badop[int(m.group(1), 16)] += 1
                    if len(fails) < 60: fails.append((name, ci, r['id'], status))
                    continue
                bad = [t for t in toks if t[1] == 'op' and t[2] not in IMPL]
                zeros = [t for t in toks if t[1] == 'op' and t[2] == 0]
                if bad:
                    st['unimpl'] += 1
                    for t in bad: unimpl_use[t[2]] += 1
                elif not zeros or zeros[-1][0] != len(d) - 1:
                    st['stray0'] += 1
                else:
                    st['ok'] += 1
        if not good: continue
        perfile[name] = (st, nbytes)
        for k, v in st.items(): tot[k] += v
    return tot, perfile, badop, unimpl_use, fails

if __name__ == '__main__':
    tot, perfile, badop, unimpl_use, fails = scan()
    for w in ('m/MS0000.BIN', 'm/MS0003.BIN', 'm/MS6000.BIN', 'et/ID0099.BIN'):
        if w in perfile: print("%-16s %-52s bytes=%d" % (w, dict(perfile[w][0]), perfile[w][1]))
    n = sum(tot.values())
    print("\nTOTALS over %d record-structured files: %s" % (len(perfile), dict(tot)))
    print("records with no unexplained byte: %d / %d = %.2f%%"
          % (tot['ok'] + tot['stray0'], n, 100.0*(tot['ok']+tot['stray0'])/max(n,1)))
    print("\nfirst-failure opcodes:")
    for k, v in badop.most_common(20): print("   idx 0x%03x  %d" % (k, v))
    print("\nunimplemented opcodes reached:")
    for k, v in unimpl_use.most_common(20): print("   idx 0x%03x  %d" % (k, v))
    print("\nexamples:")
    for e in fails[:12]: print("  ", e)
