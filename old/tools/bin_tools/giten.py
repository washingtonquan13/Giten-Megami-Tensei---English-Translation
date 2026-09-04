"""Giten .BIN decoder -- thin wrapper over the ``tools.giten`` package.

The real implementation now lives in ``tools/giten/`` (see ``docs/pipeline.md``).
This module is kept so the older exploration scripts in this folder, and any
notes that reference them, keep working unchanged.  Its public names --
``ROOT``, ``unxor``, ``enxor``, ``load``, ``sjis_strings``, ``dump_all`` -- mean
exactly what they always did.

Container format (m/*.BIN, p/*.BIN, et/ET*.BIN, et/ID*.BIN):
    off 0..1 : uint16 LE header (== len(body) for 783 of the 844 encoded files)
    off 2..  : body, chain-XOR encoded: plain[i] = enc[i] ^ enc[i-1]

et/A*.BIN (fonts) and et/CA*.BIN are stored PLAIN (not XOR-encoded).
fc/*.bin are raw Windows BMP files.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from tools.giten.container import enxor, unxor          # noqa: E402,F401
from tools.giten.paths import game_root                 # noqa: E402

ROOT = game_root()


def load(path, skip_header=True):
    raw = open(path, 'rb').read()
    body = raw[2:] if skip_header else raw
    return raw[:2], unxor(body)


def sjis_strings(buf, minlen=2):
    """Yield (offset, text) for NUL-terminated cp932 strings."""
    res = []
    i = 0
    n = len(buf)
    while i < n:
        if buf[i] == 0:
            i += 1
            continue
        j = i
        while j < n and buf[j] != 0:
            j += 1
        chunk = buf[i:j]
        if len(chunk) >= minlen:
            try:
                t = chunk.decode('cp932')
            except UnicodeDecodeError:
                i = j + 1
                continue
            if all((c == '\n' or c == '\t' or ord(c) >= 0x20) for c in t):
                res.append((i, t))
        i = j + 1
    return res


def dump_all(buf, minlen=2):
    """Looser: scan for runs of printable ascii+cp932 anywhere."""
    res = []
    i = 0
    n = len(buf)
    while i < n:
        j = i
        txt = []
        while j < n:
            b = buf[j]
            if 0x20 <= b < 0x7f:
                txt.append(chr(b))
                j += 1
            elif ((0x81 <= b <= 0x9f or 0xe0 <= b <= 0xef) and j + 1 < n
                  and 0x40 <= buf[j + 1] <= 0xfc and buf[j + 1] != 0x7f):
                try:
                    txt.append(buf[j:j + 2].decode('cp932'))
                except Exception:
                    break
                j += 2
            elif 0xa1 <= b <= 0xdf:
                txt.append(bytes([b]).decode('cp932'))
                j += 1
            else:
                break
        if len(txt) >= minlen:
            res.append((i, ''.join(txt)))
        i = j + 1 if j > i else i + 1
    return res


if __name__ == '__main__':
    p = sys.argv[1]
    if not os.path.isabs(p):
        p = os.path.join(ROOT, p)
    hdr, buf = load(p, '--noskip' not in sys.argv)
    print("file=%s size=%d hdr=%s (%d) body=%d"
          % (p, os.path.getsize(p), hdr.hex(),
             int.from_bytes(hdr, 'little'), len(buf)))
    if '--hex' in sys.argv:
        k = sys.argv.index('--hex')
        lim = (int(sys.argv[k + 1])
               if len(sys.argv) > k + 1 and sys.argv[k + 1].isdigit() else 512)
        for o in range(0, min(len(buf), lim), 16):
            row = buf[o:o + 16]
            hexpart = ' '.join('%02x' % b for b in row)
            asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in row)
            print("%06x  %-47s  %s" % (o, hexpart, asc))
    for o, t in dump_all(buf, 3):
        print("%06x: %r" % (o, t))
