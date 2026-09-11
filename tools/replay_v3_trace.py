"""Replay a pre-v4 trace against a v6 overlay table, offline.

A stopgap with a stated shelf life.  ``giten trace verify`` is the real oracle,
and it needs a **v4** trace -- one that logs FNV-1a over the record the
interpreter is standing in, because that is what overlay v6 keys on.  The
sessions recorded before 2026-09-10 are v2/v3 and carry no such hash, so verify
refuses them rather than judging addresses against a file label that is written
on load and routinely names a script that is not running.

That still leaves one question a v3 trace can answer, and it is the question
worth asking the day the overlay changes shape: **for every event, does the v6
table hold the record the engine's own index entry names?**  The index entry
(record id, runtime offset, length) is read out of the live buffer by
``trace.S``, so it is not a label and does not go stale.  Resolving it against
the corpus gives the handful of records on disk that could be sitting there:

    resolved      at least one of them is a key the table holds -- the overlay
                  would serve English at that address
    untranslated  the record is on disk and we have no English for it
    runtime       no record on disk has that shape, so the loader built it
    no context    the engine logged no index entry: a null context or handle,
                  which it produces legitimately between scripts

Usage::

    python tools/replay_v3_trace.py [trace.bin] [overlay.dat]
"""
from __future__ import annotations

import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from giten import container, files, overlay, paths, records  # noqa: E402
from giten.trace import core  # noqa: E402

#: the pool files are never promoted from a reference (a fragment spliced into
#: thousands of sentences cannot be right in all of them), so "no English" is
#: the intended state there rather than a gap
POOL = frozenset("m/MS7F%02X.BIN" % i for i in range(8))


def corpus(root=None):
    """``{(id, runtime offset, length): {hash: [file c#]}}`` over every m/ container."""
    root = root or paths.ORIGINAL_DDSWIN
    out = collections.defaultdict(dict)
    d = os.path.join(root, "m")
    for name in sorted(os.listdir(d)):
        if not name.endswith(".BIN"):
            continue
        rel = "m/%s" % name
        try:
            conts, _ = container.split(files.read_source(rel, root))
        except Exception:
            continue
        for ci, c in enumerate(conts):
            try:
                recs = records.parse_body(c.body).records
            except Exception:
                continue
            first = {}
            for r in recs:
                first.setdefault(r.id, r.data)
            off = 0x400
            for i in range(256):
                data = first.get(i)
                n = len(data) if data is not None else records.ABSENT_LEN
                if data is not None and n > 1:
                    out[(i, off, n)].setdefault(
                        overlay.fnv1a(data), []).append("%s c%d" % (rel, ci))
                off += n
    return out


#: the three wrong lines of docs/PLAN-content-addressing.md section 0, as the
#: engine's own index entries named them
SYMPTOMS = ((2, 0x041C, 12), (2, 0x0423, 9), (2, 0x0425, 9))


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    trace = argv[0] if argv else os.path.join(paths.BUILD_DIR, "trace.bin")
    ovl = argv[1] if len(argv) > 1 else os.path.join(paths.BUILD_DIR, "overlay.dat")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    with open(ovl, "rb") as fh:
        entries = overlay.parse(fh.read())
    have = {e.key: e for e in entries}
    corp = corpus()

    with open(trace, "rb") as fh:
        blob = fh.read()
    rs, body = core._pick(blob, trace)
    n = len(body) // rs.size
    print("%s: %d events, %d-byte records" % (os.path.basename(trace), n, rs.size))
    print("%s: %d record keys, %d spans"
          % (os.path.basename(ovl), len(entries),
             sum(len(e.spans) for e in entries)))

    seen = collections.Counter()
    for i in range(n):
        f = rs.unpack_from(body, i * rs.size)
        seen[(f[1], f[7], f[8])] += 1           # rec, idx_off, idx_len

    buckets, shapes = collections.Counter(), collections.Counter()
    unres = collections.Counter()
    for (rec, off, ln), count in seen.items():
        if not off and not ln:
            buckets["no context"] += count
            shapes["no context"] += 1
            continue
        cands = corp.get((rec, off, ln))
        if not cands:
            buckets["runtime"] += count
            shapes["runtime"] += 1
            unres[(rec, off, ln, "no record on disk has this shape -- built by "
                                 "the loader")] += count
            continue
        if any((rec, ln, h) in have for h in cands):
            buckets["resolved"] += count
            shapes["resolved"] += 1
            continue
        buckets["untranslated"] += count
        shapes["untranslated"] += 1
        who = cands[sorted(cands)[0]][0].split()[0]
        why = "in %s%s, no English" % (who, ", a pool file" if who in POOL else "")
        unres[(rec, off, ln, why)] += count

    print("")
    print("events by outcome")
    for k in ("resolved", "untranslated", "runtime", "no context"):
        print("  %-13s %8d events  (%5.1f%%)  %4d distinct (rec, off, len)"
              % (k, buckets[k], 100.0 * buckets[k] / max(1, n), shapes[k]))

    print("")
    print("the ten unresolved (rec, off, len) with the most events")
    for (rec, off, ln, why), count in unres.most_common(10):
        print("  rec %02X off 0x%04X len %5d  %7d events  -- %s"
              % (rec, off, ln, count, why))

    print("")
    print("the three symptom rows")
    for rec, off, ln in SYMPTOMS:
        cands = corp.get((rec, off, ln), {})
        print("")
        print("  record %02X, %d bytes at 0x%04X -- %d events this session, "
              "%d different records on disk"
              % (rec, ln, off, seen.get((rec, off, ln), 0), len(cands)))
        for h in sorted(cands, key=lambda k: cands[k][0]):
            who = cands[h]
            e = have.get((rec, ln, h))
            if e is None:
                print("    %-22s hash %08X  -- not translated; the engine reads "
                      "its own bytes" % (who[0], h))
                continue
            for s in e.spans:
                print("    %-22s hash %08X  +0x%02X -> %r"
                      % (who[0], h, s.rec_off,
                         s.data.decode("cp932", "replace").replace("\n", "\\n")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
