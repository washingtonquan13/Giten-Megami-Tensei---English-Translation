"""Giten Megami Tensei (1999, ASCII/Atlus) .BIN decoder.

Container format (m/*.BIN, p/*.BIN, et/ET*.BIN, et/ID*.BIN):
    off 0..1 : uint16 LE  = length of the encoded body (== filesize-2) for m/ and p/
    off 2..  : encoded body

Encoding is a running (cumulative) XOR:
    enc[i] = plain[i] ^ enc[i-1]      (enc[-1] = 0)
  =>plain[i] = enc[i] ^ enc[i-1]
i.e. enc[i] = plain[0]^plain[1]^...^plain[i].  Trivially reversible, no compression.

et/A*.BIN (fonts) and et/CA*.BIN are stored PLAIN (not XOR-encoded).
fc/*.bin are raw Windows BMP files.
"""
import os, sys, re

import os as _os
def _find_root():
    """Locate ddswin/: $GITEN_ROOT, else search upward from this file for a folder containing ddswin/."""
    r = _os.environ.get("GITEN_ROOT")
    if r: return r
    d = _os.path.dirname(_os.path.abspath(__file__))
    for _ in range(6):
        cand = _os.path.join(d, "ddswin")
        if _os.path.isdir(cand): return cand
        for sub in _os.listdir(d):
            cand = _os.path.join(d, sub, "ddswin")
            if _os.path.isdir(cand): return cand
        d = _os.path.dirname(d)
    raise SystemExit("ddswin/ not found: set GITEN_ROOT to the game's ddswin folder")
ROOT = _find_root()

def unxor(data: bytes) -> bytes:
    out = bytearray(len(data)); prev = 0
    for i, b in enumerate(data):
        out[i] = b ^ prev; prev = b
    return bytes(out)

def enxor(data: bytes) -> bytes:
    out = bytearray(len(data)); prev = 0
    for i, b in enumerate(data):
        prev = b ^ prev; out[i] = prev
    return bytes(out)

def load(path, skip_header=True):
    raw = open(path,'rb').read()
    body = raw[2:] if skip_header else raw
    return raw[:2], unxor(body)

# ---- string extraction ----------------------------------------------------
def sjis_strings(buf, minlen=2):
    """Yield (offset, text) for NUL-terminated cp932 strings."""
    res=[]; i=0; n=len(buf)
    while i < n:
        if buf[i]==0: i+=1; continue
        j=i
        while j<n and buf[j]!=0: j+=1
        chunk=buf[i:j]
        if len(chunk)>=minlen:
            try:
                t=chunk.decode('cp932')
            except UnicodeDecodeError:
                i=j+1; continue
            if all((c=='\n' or c=='\t' or ord(c)>=0x20) for c in t):
                res.append((i,t))
        i=j+1
    return res

def dump_all(buf, minlen=2):
    """Looser: scan for runs of printable ascii+cp932 anywhere."""
    res=[];i=0;n=len(buf)
    while i<n:
        j=i;txt=[]
        while j<n:
            b=buf[j]
            if 0x20<=b<0x7f: txt.append(chr(b)); j+=1
            elif (0x81<=b<=0x9f or 0xe0<=b<=0xef) and j+1<n and (0x40<=buf[j+1]<=0xfc and buf[j+1]!=0x7f):
                try: txt.append(buf[j:j+2].decode('cp932'))
                except Exception: break
                j+=2
            elif 0xa1<=b<=0xdf: txt.append(bytes([b]).decode('cp932')); j+=1
            else: break
        if len(txt)>=minlen: res.append((i,''.join(txt)))
        i = j+1 if j>i else i+1
    return res

if __name__=='__main__':
    p=sys.argv[1]
    if not os.path.isabs(p): p=os.path.join(ROOT,p)
    skip = '--noskip' not in sys.argv
    hdr,buf = load(p, skip)
    print(f"file={p} size={os.path.getsize(p)} hdr={hdr.hex()} ({int.from_bytes(hdr,'little')}) body={len(buf)}")
    if '--hex' in sys.argv:
        for o in range(0,min(len(buf),int(sys.argv[sys.argv.index('--hex')+1]) if len(sys.argv)>sys.argv.index('--hex')+1 and sys.argv[sys.argv.index('--hex')+1].isdigit() else 512),16):
            row=buf[o:o+16]
            print(f"{o:06x}  {' '.join(f'{b:02x}' for b in row):<47}  {''.join(chr(b) if 32<=b<127 else '.' for b in row)}")
    for o,t in dump_all(buf,3):
        print(f"{o:06x}: {t!r}")
