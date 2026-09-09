"""Compare the 1997 PC-9801 release against the Windows original.

    python tools/pc98_diff.py <path to the PC-98 DDS98 directory>
    python tools/pc98_diff.py <dir> --skills      # the ET0004 field-level diff

The PC-98 release is the same game: of its 1,548 data files, **1,041 are
byte-identical** to the ones the Windows port ships, including every ``CA``
(257), ``ID`` (17), ``SB``/``SM``/``ST``/``SE`` and ``A`` file, 159 of 200
``MS`` scripts, 82 of 100 ``M`` and 395 of 432 ``P``.  Every ``FC`` file differs
-- those are the graphics, which the port redrew at a higher resolution.

That makes the PC-98 disc a **reference implementation** for this project, not
just a curiosity: where a Windows file is byte-identical to the 1997 original,
nothing about it was changed by the port, and where it differs, the diff is the
port's own edit and is worth reading.

Getting it: the disc image in the PepsimanGB dump is plain ISO 9660, so any
extractor will do; the files land in ``DDS98/``.  Nothing here writes, and
nothing in the build pipeline depends on this script -- it is an analysis tool.

The one genuinely surprising result is ``et/ET0004.BIN``, the skill database:
same size, same 309 records, but **73 of them carry different numbers**.  Run
with ``--skills`` for the field-level diff.  Notably all fifteen basic weapon
attacks (records 1-15) have two fields zeroed together, and every healing skill
had its ``+0x0A`` value raised.
"""
from __future__ import annotations

import collections
import io
import os
import re
import struct
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)

from giten import container, paths

WIN = os.path.join(paths.REPO_ROOT, "original", "ddswin")


def _win_index():
    """Upper-case basename -> path, over the whole Windows tree."""
    out = {}
    for root, _dirs, files in os.walk(WIN):
        for f in files:
            out.setdefault(f.upper(), os.path.join(root, f))
    return out


def survey(pc98: str) -> None:
    win = _win_index()
    tot = collections.Counter(); same = collections.Counter()
    diff = collections.Counter(); absent = collections.Counter()
    interesting = []
    for f in sorted(os.listdir(pc98)):
        key = f.upper()
        fam = (re.match(r"[A-Z]+", key) or [""])[0]
        tot[fam] += 1
        if key not in win:
            absent[fam] += 1
            continue
        a = open(os.path.join(pc98, f), "rb").read()
        b = open(win[key], "rb").read()
        if a == b:
            same[fam] += 1
        else:
            diff[fam] += 1
            if fam != "FC":                      # FC is art; the port redrew it
                interesting.append((f, len(a), len(b)))
    print("%-8s %6s %6s %6s %6s" % ("family", "total", "same", "diff", "absent"))
    for fam in sorted(tot):
        print("%-8s %6d %6d %6d %6d"
              % (fam, tot[fam], same[fam], diff[fam], absent[fam]))
    print("\nnon-graphics files that differ (%d):" % len(interesting))
    for f, la, lb in interesting:
        print("   %-14s pc98=%-7d win=%-7d  %+d" % (f, la, lb, lb - la))


def _skill_records(path: str):
    """The 309 skill records of an ET0004.BIN, via its u16 offset table."""
    body = container.split(open(path, "rb").read())[0][0].body
    n = struct.unpack_from("<H", body, 0)[0]
    offs = [struct.unpack_from("<H", body, 2 + 2 * i)[0] for i in range(n)]
    return [body[o:e] for o, e in zip(offs, offs[1:] + [len(body)])]


def skills(pc98: str) -> None:
    """Field-level diff of the skill database, the port's one real rebalance.

    The 20-byte binary header is what the engine reads; bytes past it are the
    name and description strings, and **not one record's text changed** -- so
    every difference here is a number someone deliberately retuned.
    """
    ra = _skill_records(os.path.join(pc98, "ET0004.BIN"))
    rb = _skill_records(os.path.join(WIN, "et", "ET0004.BIN"))
    if len(ra) != len(rb):
        raise SystemExit("record counts differ: %d vs %d" % (len(ra), len(rb)))
    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    cols = collections.Counter()
    changed = 0
    for i, (x, y) in enumerate(zip(ra, rb)):
        if x == y:
            continue
        changed += 1
        ds = [k for k in range(20) if x[k] != y[k]]
        for k in ds:
            cols[k] += 1
        name = x[20:].split(b"\0")[0].decode("cp932", "replace")
        text = "  TEXT CHANGED" if x[20:] != y[20:] else ""
        out.write("%3d %-16s %s%s\n"
                  % (i, name,
                     " ".join("+%02X %3d->%3d" % (k, x[k], y[k]) for k in ds),
                     text))
    out.write("\n%d of %d records changed; by header offset:\n" % (changed, len(ra)))
    for k in sorted(cols):
        out.write("   +0x%02X : %d records\n" % (k, cols[k]))
    out.flush()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__.strip().splitlines()[2].strip())
    d = sys.argv[1]
    if not os.path.isdir(d):
        raise SystemExit("not a directory: %s" % d)
    if "--skills" in sys.argv:
        skills(d)
    else:
        survey(d)
