"""What Japanese actually reached the screen in a play session, and why.

    python tools/screen_audit.py <textout.bin> [--min N] [--csv OUT.tsv]

The translation tables say what *should* draw.  `giten check` says what is
unreviewed.  Neither says what a player actually saw, and those differ: a row
can be translated, reviewed and still render in Japanese because the overlay
failed to serve it.  This reads a dev build's glyph log -- the record of every
character the game drew -- and reports the Japanese that survived, ranked by how
often the player saw it, with a verdict on the cause of each.

Verdicts, and what each one means for the fix:

    NO EXTRACTOR    the drawing code's source file is known and nothing
                    extracts it (see KNOWN_SOURCE).  Fix: write the extractor.
    NO TABLE ROW    no row in tables/ carries this text.  It lives in a file no
                    extractor reads.  Fix: find the file, then the extractor.
    NOT TRANSLATED  the row exists and `en` is empty.  Fix: translate it.
    EN IS JAPANESE  `en` is set but still holds kana or kanji.  Fix: finish it.
    SERVED?         the row has clean English and the game drew Japanese
                    anyway.  Nothing is wrong with the table -- this is an
                    overlay-side fault.  See docs/overlay.md.

Two details that are easy to get wrong and that this handles:

* **Pool calls must be expanded, not stripped.**  A drawn line is contiguous
  kana; the file stores ``手に入{08:60}`` and ``{08:60}`` is ``れた``.  Deleting
  the marker breaks the join and reports "no table row" for text that is sitting
  right there in a table.
* **Some draw-string variants are typewriters** -- one call per glyph.  Counting
  those calls separately shreds every sentence into single characters.  Runs of
  consecutive calls from the same variant are glued back together first.

The log is truncated every time the game launches, so run this against a copy.
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

from giten import pool  # noqa: E402
from giten.textlog import HEADER, MAGIC, REC  # noqa: E402

#: kana and kanji.  NOT U+FF01..U+FF60: that is the fullwidth ASCII block, where
#: the game's own digits live (the damage printer converts every ASCII digit
#: into one), and counting those calls "1" untranslated Japanese.
RUN = re.compile(r"[぀-ヿ一-鿿]+")
MARK = re.compile(r"\{[0-9A-Fa-f:]+\}|<wait>|\\n")

#: variants that draw one glyph per call
TYPEWRITER = {6}

#: Files that hold drawable text and that no extractor reads, so no table row
#: can ever exist for them.  Membership is checked per fragment, against the
#: file's own strings -- not assumed from the draw-string variant.
#:
#: ``et/ET000D.BIN`` chunk 1 is 221 NUL-terminated district names behind a u16
#: count and a u16 offset table.  It feeds the location strip.  Matching those
#: names against the script tables instead would credit whichever row happens to
#: share the characters -- 新宿 appears in 148 dialogue rows -- and report "not
#: translated, here is the row" about a row the strip never reads.
#:
#: Checking membership rather than trusting the variant matters: variant 1 is
#: not the strip, it is the general HUD drawer (party names, the MAG counter,
#: numbers, shelter names in English).  What is true, and verified across both
#: recorded sessions, is that every one of the 20 distinct *Japanese* strings it
#: drew -- 600 calls, no exceptions -- is in this file.
UNEXTRACTED = (("et/ET000D.BIN", 1, "the location strip"),)


def unextracted_strings():
    """``{text: (file, why)}`` for every file in :data:`UNEXTRACTED`."""
    from giten import container, paths
    out = {}
    for rel, ci, why in UNEXTRACTED:
        p = os.path.join(paths.ORIGINAL_DDSWIN, *rel.split("/"))
        body = container.split(open(p, "rb").read())[0][ci].body
        at = 0
        while at < len(body):
            end = body.find(b"\0", at)
            if end < 0:
                end = len(body)
            if end > at:
                try:
                    s = body[at:end].decode("cp932")
                except UnicodeDecodeError:
                    s = ""
                if s and has_jp(s):
                    out[s] = (rel, why)
            at = end + 1
    return out

CHUNK = 1 << 22


def has_jp(s: str) -> bool:
    return bool(RUN.search(s))


def stream(path):
    """Yield ``(variant, drawn bytes)`` per draw-string call, glueing runs."""
    with open(path, "rb") as fh:
        head = fh.read(HEADER)
        if not head.startswith(MAGIC):
            raise SystemExit("%s is not a GTXT log" % path)
        size = struct.unpack_from("<HH", head, 4)[1]
        if size != REC:
            raise SystemExit("record size %d, expected %d" % (size, REC))
        cur, carry = None, b""
        while True:
            blob = fh.read(CHUNK)
            if not blob:
                break
            blob = carry + blob
            n = len(blob) // REC
            for i in range(n):
                at = i * REC
                kind = struct.unpack_from("<H", blob, at)[0]
                if kind:
                    if cur is not None and not (kind in TYPEWRITER
                                                and cur[0] == kind):
                        yield cur[0], bytes(cur[1])
                        cur = None
                    if cur is None:
                        cur = (kind, bytearray())
                elif cur is not None:
                    ch = struct.unpack_from("<I", blob, at + 4)[0]
                    if ch > 0xFF:
                        cur[1].append((ch >> 8) & 0xFF)
                    cur[1].append(ch & 0xFF)
            carry = blob[n * REC:]
        if cur is not None:
            yield cur[0], bytes(cur[1])


def load_rows(pools):
    """Every table row that carries Japanese, with its pool calls expanded."""
    rows = []
    for p in sorted(glob.glob(os.path.join(R, "tables", "**", "*.tsv"),
                              recursive=True)):
        with open(p, encoding="utf-8") as fh:
            head = None
            for line in fh:
                line = line.rstrip("\n")
                if line.startswith("#") or not line.strip():
                    continue
                f = line.split("\t")
                if head is None:
                    head = f
                    continue
                d = dict(zip(head, f))
                if not has_jp(d.get("jp", "")):
                    continue
                try:
                    flat = pool.reading(d["jp"], pools)
                except Exception:
                    flat = d["jp"]
                d["_flat"] = MARK.sub("", flat)
                d["_table"] = os.path.relpath(p, R).replace(os.sep, "/")
                rows.append(d)
    return rows


def verdict_of(hits):
    if not hits:
        return "NO TABLE ROW", None
    best = min(hits, key=lambda d: len(d["_flat"]))
    en = best.get("en", "")
    if not en.strip():
        return "NOT TRANSLATED", best
    if has_jp(MARK.sub("", en)):
        return "EN IS JAPANESE", best
    return "SERVED?", best


def main(argv):
    if not argv:
        raise SystemExit(__doc__.strip().splitlines()[2].strip())
    path = argv[0]
    lo = int(argv[argv.index("--min") + 1]) if "--min" in argv else 1
    csv = argv[argv.index("--csv") + 1] if "--csv" in argv else None

    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    pools = pool.load()
    rows = load_rows(pools)
    unextracted = unextracted_strings()

    drawn_jp = collections.Counter()
    calls = 0
    for variant, drawn in stream(path):
        calls += 1
        if not drawn:
            continue
        s = drawn.decode("cp932", "replace").rstrip("\0")
        if has_jp(s):
            drawn_jp[(variant, s)] += 1

    frags = collections.Counter()
    for (variant, s), n in drawn_jp.items():
        for run in RUN.findall(s):
            if len(run) >= 2:
                frags[(run, variant)] += n

    out.write("%s\n" % os.path.basename(path))
    out.write("  %d draw-string calls, %d drew Japanese, %d distinct fragments\n\n"
              % (calls, sum(drawn_jp.values()), len(frags)))

    weighted = collections.Counter()
    lines = []
    for (run, variant), n in frags.most_common():
        if run in unextracted:
            v, best, nhit = "NO EXTRACTOR", None, 0
        else:
            hits = [d for d in rows if run in d["_flat"]]
            v, best = verdict_of(hits)
            nhit = len(hits)
        weighted[v] += n
        lines.append((n, variant, v, run, best, nhit))

    total = sum(weighted.values()) or 1
    out.write("  cause, weighted by how often the player saw it:\n")
    for v, n in weighted.most_common():
        out.write("     %-16s %5d  %4.1f%%\n" % (v, n, 100.0 * n / total))
    out.write("\n")

    for n, variant, v, run, best, nhit in lines:
        if n < lo:
            continue
        out.write("%6d  v%d  %-14s %s\n" % (n, variant, v, run))
        if run in unextracted:
            out.write("            source: %s -- %s\n" % unextracted[run])
        if best is not None:
            out.write("            %s %s[%s]  status=%s%s\n"
                      % (best["_table"], best.get("rec", "?"),
                         best.get("idx", "?"), best.get("status", ""),
                         "  (+%d other rows)" % (nhit - 1) if nhit > 1 else ""))
            out.write("            jp: %s\n" % best["jp"][:110])
            out.write("            en: %s\n" % best.get("en", "")[:110])
        out.write("\n")

    if csv:
        with open(csv, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("draws\tvariant\tverdict\tfragment\ttable\trec\tidx\tstatus\ten\n")
            for n, variant, v, run, best, _ in lines:
                b = best or {}
                fh.write("%d\t%d\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n"
                         % (n, variant, v, run, b.get("_table", ""),
                            b.get("rec", ""), b.get("idx", ""),
                            b.get("status", ""),
                            b.get("en", "").replace("\t", " ")))
        out.write("wrote %s\n" % csv)
    out.flush()


if __name__ == "__main__":
    main(sys.argv[1:])
