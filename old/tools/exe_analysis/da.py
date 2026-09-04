"""da.py -- disassemble a VA range of dds_en.exe with objdump.

Usage:
    python da.py <va_hex> [len]          # disassemble len bytes at VA
    python da.py --dump <out.txt>        # linear sweep of the whole .text
    python da.py --data <va_hex> [len]   # hexdump of a VA range

No capstone in this environment; objdump -D -b binary -mi386 -Mintel --adjust-vma
is used on an extracted slice, which is what the previous pass verified works.
"""
import os, sys, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import PE

CAND = [
    r"C:\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin",
    r"D:\BrowserDownloads\Giten Megami Tensei - English - v0.05\Giten Megami Tensei - English\ddswin",
]
D = next(p for p in CAND if os.path.isdir(p))
EXE = os.path.join(D, "dds_en.exe")
_p = PE(EXE)
_buf = _p.data

def va2off(va): return _p.va2off(va)
def off2va(off): return _p.off2va(off)

def read(va, n):
    o = va2off(va)
    if o is None: raise ValueError("VA %08x not mapped" % va)
    return _buf[o:o+n]

def disasm(va, n=0x80):
    b = read(va, n)
    fd, tmp = tempfile.mkstemp(suffix=".bin"); os.close(fd)
    open(tmp, "wb").write(b)
    try:
        r = subprocess.run(["objdump", "-D", "-b", "binary", "-mi386", "-Mintel",
                            "--adjust-vma=0x%x" % va, tmp],
                           capture_output=True, text=True)
    finally:
        os.remove(tmp)
    return "\n".join(l for l in r.stdout.splitlines() if ":\t" in l)

def hexdump(va, n=0x80):
    b = read(va, n); out = []
    for i in range(0, len(b), 16):
        c = b[i:i+16]
        out.append("%08x  %-47s  %s" % (va+i, " ".join("%02x" % x for x in c),
                   "".join(chr(x) if 32 <= x < 127 else "." for x in c)))
    return "\n".join(out)

if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--dump":
        sec = [s for s in _p.sections if s["name"] == ".text"][0]
        va = sec["vaddr"] + _p.imagebase
        open(a[1], "w").write(disasm(va, sec["rawsize"]))
        print("wrote", a[1])
    elif a and a[0] == "--data":
        print(hexdump(int(a[1], 16), int(a[2], 0) if len(a) > 2 else 0x80))
    else:
        print(disasm(int(a[0], 16), int(a[1], 0) if len(a) > 1 else 0x80))
