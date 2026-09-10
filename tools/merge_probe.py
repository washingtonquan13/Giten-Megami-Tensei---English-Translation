"""How many spans bind to a real merged negotiation image, all-or-nothing vs per-span.

Builds the merge the engine builds -- m/MS6000 plus the files et/ET0007 names for
one demon row, later files replacing earlier records by id -- then asks the
overlay to bind against it, once with the current rule and once with the rule
relaxed to per-span.
"""
import io
import os
import struct
import sys

R = r"C:/Giten Megami Tensei - English - v0.05/Giten Megami Tensei - English Translation"
sys.path.insert(0, R)

from giten import files, overlay, records, script  # noqa: E402


def recs_of(rel, ci=0):
    sc = script.parse(rel, files.read_source(rel))
    if not sc.containers or ci >= len(sc.containers):
        return {}
    out = {}
    for r in sc.containers[ci]:
        out.setdefault(r.id, r.data)
    return out


def et0007_rows():
    raw = files.read_source("et/ET0007.BIN")
    n = int.from_bytes(raw[:2], "little")
    return [tuple(raw[2 + i * 3:5 + i * 3]) for i in range(n // 3)]


def merged_files(row):
    t0, t1, t2 = row
    out = ["m/MS6000.BIN"]
    for fam, t in ((0x6000, t0), (0x6000, t1), (0x6100, t2)):
        if t != 0xFF:
            out.append("m/MS%04X.BIN" % (fam + t))
    return out


def build_image(rels, ci=0):
    merged = {}
    for rel in rels:
        merged.update(recs_of(rel, ci))
    idx = bytearray()
    off = 0x400
    body = bytearray()
    for i in range(256):
        d = merged.get(i, b"\0")
        idx += struct.pack("<HH", off, len(d))
        body += d
        off += len(d)
    return bytes(idx) + bytes(body)


def bind_per_span(entries, fid, image):
    """bind(), but an entry contributes the spans that verify, not all or none."""
    slot = overlay.merged_slot(fid)
    out, taken, cursor = [], set(), overlay._live_end(image)
    for e in sorted(entries, key=lambda x: (x.fid, x.ci)):
        if e.ci != slot or not e.spans:
            continue
        got = overlay.resolve(e, image, virt_base=cursor)
        if not got:
            continue
        used = max((sp.vend for sp in got if sp.tail), default=cursor) - cursor
        cursor += used
        for sp in got:
            if sp.start in taken:
                continue
            taken.add(sp.start)
            out.append(sp)
    out.sort(key=lambda x: x.start)
    return out


def main():
    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ov = open(os.path.join(
        r"C:/Giten Megami Tensei - English - v0.05/play/en/ddswin/overlay.dat"), "rb").read()
    entries = overlay.parse(ov)
    rows = et0007_rows()
    out.write("et/ET0007 rows: %d\n\n" % len(rows))
    out.write("row  files merged                     now  per-span   gain\n")
    tot_now = tot_new = 0
    for i, row in enumerate(rows):
        rels = merged_files(row)
        try:
            image = build_image(rels)
        except Exception as e:
            out.write("  %2d  <%s>\n" % (i, e))
            continue
        fid = 0xE0                       # slot 0
        now = overlay.bind(entries, fid, image)
        new = bind_per_span(entries, fid, image)
        tot_now += len(now)
        tot_new += len(new)
        out.write("  %2d  %-32s %4d  %6d  %+5d\n"
                  % (i, ",".join(r[5:9] for r in rels), len(now), len(new),
                     len(new) - len(now)))
    out.write("\n  totals over slot 0 of all %d demon rows: %d -> %d spans (%+d)\n"
              % (len(rows), tot_now, tot_new, tot_new - tot_now))
    out.flush()


if __name__ == "__main__":
    main()
