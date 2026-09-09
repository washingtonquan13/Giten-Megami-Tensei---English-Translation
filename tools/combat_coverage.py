"""How much of the combat code do we actually understand?  A number, not a feeling.

    python tools/combat_coverage.py            # the summary
    python tools/combat_coverage.py --unnamed  # the busiest functions we cannot name

Counts every function in the four combat regions -- taken as the distinct
targets of `call rel32` in `.text` -- and checks each against the set of
addresses written down anywhere in `docs/*.md`.  Being *mentioned* in a doc is a
weak proxy for being understood, and it is deliberately the generous one: the
real figure is no higher than this and probably lower.

Written 2026-09-09, when the answer was **22 of 243, about 9%**, after a week of
combat work that had produced a correct account of turn scheduling, the input
gate, the target-list builder and the status tick.  The point of the number is
that all of that was four narrow threads through a large module, and it is easy
to mistake "I followed every thread I pulled" for "I have read the module".

`docs/combat-unknowns.md` is the backlog this measures progress against.  Re-run
it after any investigation session; if the count has not moved, the session
answered a question rather than mapping ground, which is fine but worth knowing.
"""
from __future__ import annotations

import collections
import glob
import io
import os
import re
import struct
import sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R)

from giten import paths  # noqa: E402

EXE = os.path.join(paths.ORIGINAL_DDSWIN, "dds_org.exe")
TEXT_RAW, TEXT_VA, TEXT_SIZE = 0x400, 0x401000, 0x62400

#: the four regions that make up combat, and what lives in each
REGIONS = (
    ("battle module", 0x0042A000, 0x0042E000),
    ("enemy AI / actor", 0x0040DC00, 0x00410000),
    ("unit state / status", 0x0043E000, 0x00440000),
    ("battle command UI", 0x0041D000, 0x0041E000),
    # Added 2026-09-09 with combat-damage.md: the attack / damage / accuracy
    # routines live here and were not being measured at all, so every earlier
    # figure in combat-unknowns.md silently excluded the arithmetic centre of
    # combat.  Counting it drops the total, which is the honest direction.
    ("attack / damage", 0x00406000, 0x0040C000),
)


def functions() -> "collections.Counter":
    """``{target VA: call-site count}`` for every ``call rel32`` inside .text."""
    data = open(EXE, "rb").read()
    out = collections.Counter()
    for off in range(TEXT_RAW, TEXT_RAW + TEXT_SIZE - 5):
        if data[off] != 0xE8:
            continue
        va = TEXT_VA + (off - TEXT_RAW)
        target = va + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if TEXT_VA <= target < TEXT_VA + TEXT_SIZE:
            out[target] += 1
    return out


def documented() -> "set[int]":
    """Every 6-hex-digit address appearing in any ``docs/*.md``."""
    out = set()
    for path in glob.glob(os.path.join(paths.REPO_ROOT, "docs", "*.md")):
        text = io.open(path, encoding="utf-8", errors="replace").read()
        for m in re.finditer(r"0x(?:00)?([0-9A-Fa-f]{6})\b", text):
            out.add(int(m.group(1), 16))
    return out


def main(argv):
    calls, named = functions(), documented()
    rows, tot, hit = [], 0, 0
    for label, lo, hi in REGIONS:
        fs = [t for t in calls if lo <= t < hi]
        nm = [t for t in fs if t in named]
        rows.append((label, len(fs), len(nm)))
        tot += len(fs)
        hit += len(nm)

    print("%-22s %7s %7s %8s" % ("region", "funcs", "named", "covered"))
    for label, f, n in rows:
        print("%-22s %7d %7d %7.0f%%" % (label, f, n, 100.0 * n / max(1, f)))
    print("%-22s %7d %7d %7.0f%%" % ("TOTAL", tot, hit, 100.0 * hit / max(1, tot)))

    if "--unnamed" in argv:
        print("\nbusiest functions we cannot name (call sites -> address):")
        un = [(c, t) for label, lo, hi in REGIONS
              for t, c in calls.items() if lo <= t < hi and t not in named]
        for c, t in sorted(un, reverse=True)[:20]:
            print("   0x%08X  %3d sites" % (t, c))


if __name__ == "__main__":
    main(sys.argv[1:])
