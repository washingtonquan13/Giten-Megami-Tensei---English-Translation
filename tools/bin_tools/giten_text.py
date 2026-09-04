"""Giten text extraction with dictionary expansion -- thin wrapper.

The implementation lives in ``tools/giten/`` (``dictionary`` + ``tokens``).

  0x08 <nn>  -> substitute entry <nn> of the word dictionary in m/MS7F07.BIN.

Other dictionaries live in MS7F00..MS7F02 (names/nouns) and MS7F06 (a pool of
whole battle-talk sentences).  MS7F03/04 are scripts, MS7F05 is a label.

Note the renderer here uses the old angle-bracket control notation (``<1FD3>``,
``<0A>``), which is display-only.  The pipeline itself uses
``tools.giten.tokens.render``, whose token language is reversible.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from tools.giten import dictionary as _dictionary       # noqa: E402
from tools.giten import tokens as _tokens               # noqa: E402
from giten import ROOT                                  # noqa: E402,F401

DEC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'decoded')


def records(b, start=2):
    """[id:u8][len:u16 LE][data:len] -- resync-tolerant walk (legacy behaviour).

    ``tools.giten.framing`` has the version the pipeline trusts; it additionally
    confirms a chain before believing it and checks that payloads hold text.
    """
    i = start
    out = []
    while i + 3 <= len(b):
        rid = b[i]
        ln = int.from_bytes(b[i + 1:i + 3], 'little')
        if ln > 0 and i + 3 + ln <= len(b) and b[i + 3 + ln - 1] == 0:
            out.append((i, rid, b[i + 3:i + 3 + ln - 1]))
            i += 3 + ln
        else:
            i += 1
    return out


def dictionary():
    return _dictionary.load()


def render(d, expand=True, depth=0, show_ctrl=True):
    D = dictionary()
    out = []
    i = 0
    n = len(d)
    while i < n:
        b = d[i]
        if b == 0x08 and i + 1 < n:
            op = d[i + 1]
            if expand and depth < 6 and op in D:
                out.append(render(D[op], expand, depth + 1, show_ctrl))
            else:
                out.append('{%02X}' % op)
            i += 2
            continue
        if b == 0x1f and i + 1 < n:
            if show_ctrl:
                out.append('<1F%02X>' % d[i + 1])
            i += 2
            continue
        if b == 0x0a:
            out.append('\n')
            i += 1
            continue
        if b < 0x20:
            if show_ctrl:
                out.append('<%02X>' % b)
            i += 1
            continue
        if _tokens.is_sjis_lead(b) and i + 1 < n and _tokens.is_sjis_trail(d[i + 1]):
            try:
                out.append(d[i:i + 2].decode('cp932'))
                i += 2
                continue
            except Exception:
                pass
        if _tokens.is_ascii_text(b):
            out.append(chr(b))
            i += 1
            continue
        if _tokens.is_halfwidth_kana(b):
            out.append(bytes([b]).decode('cp932'))
            i += 1
            continue
        if show_ctrl:
            out.append('<%02X>' % b)
        i += 1
    return ''.join(out)


if __name__ == '__main__':
    rel = sys.argv[1]
    p = rel if os.path.exists(rel) else os.path.join(DEC, rel)
    b = open(p, 'rb').read()
    lim = int(sys.argv[2]) if len(sys.argv) > 2 else 10 ** 9
    for k, (off, rid, d) in enumerate(records(b)):
        if k >= lim:
            break
        t = render(d, show_ctrl=('--ctrl' in sys.argv))
        if t.strip():
            print("%06x #%02X  %s" % (off, rid, t))
