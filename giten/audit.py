"""Control-flow audit: does a build still run the same script as the source?

``check`` validates the *tables* and ``verify`` proves every built file still
decodes and tiles.  Neither answers the question a player actually cares about
after a text-only patch: **did the game's logic change?**  A translation may
rewrite every line in the game and must still leave the interpreter walking the
identical path -- same opcodes, same operands, same jumps to the same places.

This module compares a build against the game folder it was built from and
reports the four ways that can fail.  All four are *derived* comparisons: they
re-parse both sides with the real pipeline, so they cannot drift from what the
builder does.

1. **Structural stream** -- the sequence of non-inline opcodes in every record,
   with their operand values.  Text, newlines, page waits and pool calls live
   inside spans and are the translator's to change; everything else must match
   byte for byte.  Any difference here means an edit escaped its span.

2. **Branch resolvability** -- how many branch displacements fail to land on an
   instruction boundary.  A file is allowed to have some in the source (the
   recovered opcode table mis-tiles a little; see ``docs/format-notes.md``
   section 2.10), but the build must never have *more* than the source did.  It
   needs no token pairing between the two sides, so a record whose text re-tiled
   cannot raise a false alarm -- which makes it the check to trust when finding
   3 and this one disagree.

3. **Branch destinations** -- the sharpest of the four.  Every real branch must
   still reach *the same instruction* it reached before.  The comparison keys on
   a structural anchor -- how many non-inline opcodes precede the target --
   rather than on a byte offset or a token index, because finding 1 has already
   proved the anchor sequence identical, whereas text re-tiles and byte offsets
   move.  Slots whose opcode is in :data:`script.NOT_A_BRANCH` are excluded:
   they are not branches, so where their value "points" is meaningless.

4. **Runtime image size** -- the script PC is a ``u16``, so a container's image
   must stay under 0x10000, and growing text is the one thing that can push it
   there.

5. **Record size** -- the loader (``0x43ABC0``) computes how much a record grows
   the buffer as a *signed 16-bit* delta (``sub di, ...`` then ``jge``): a record
   longer than 0x7FFF bytes turns the delta negative, the shrink path runs with a
   garbage count and the game crashes on load.  The original's largest record is
   28,291 bytes (``m/MS006A`` r00, the BBS); English pushed it to 35,824 and the
   terminal crashed -- found by the tracer on 2026-09-04.

Exit status is non-zero if any finding is reported.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import codec, files, paths, records, script, vmops

#: The script PC is a u16 (``docs/format-notes.md`` section 2.3), so nothing in
#: a container's runtime image may sit at or past this offset.
PC_LIMIT = 0x10000

#: The loader's per-record growth delta is a signed 16-bit value, so a record
#: of 0x8000 bytes or more is installed with a negative delta and the buffer
#: move that follows crashes (``docs/format-notes.md`` section 2.6).
RECORD_LIMIT = 0x7FFF


def _bases(recs) -> "dict[int, int]":
    """``{record id: runtime offset}`` -- :func:`records.bases` over parsed recs."""
    first = {}
    for pos, r in enumerate(recs):
        first.setdefault(r.id, pos)
    out = {}
    off = records.INDEX_SIZE
    for i in range(256):
        out[i] = off
        off += len(recs[first[i]].data) if i in first else records.ABSENT_LEN
    return out


def _image_end(recs) -> int:
    if not recs:
        return records.INDEX_SIZE
    b = _bases(recs)
    return max((b[r.id] + len(r.data)) for r in recs)


def _boundaries(recs, base) -> "set[int]":
    out = set()
    for r in recs:
        if r.tokens is None:
            continue
        out |= {base[r.id] + t.off for t in r.tokens}
        out.add(base[r.id] + len(r.data))
    return out


def _structural(rec):
    """(opcode, operand values) for every non-inline token, or ``None``.

    ``rel16`` values are replaced by a marker: a displacement legitimately
    changes when a record ahead of it grows, and finding 2 is what checks those.
    """
    if rec.tokens is None:
        return None
    return [(t.idx, tuple("R" if o.kind == "rel16" else o.value for o in t.ops))
            for t in rec.tokens
            if t.kind == "op" and t.idx not in codec.INLINE_OPS]


def _unresolvable(recs) -> "tuple[int, int]":
    """``(branch count, how many miss every instruction boundary)``.

    Counts only slots whose opcode really is a branch.  Including the
    :data:`script.NOT_A_BRANCH` opcodes would measure noise: their value is not
    a displacement, so whether it happens to point at an instruction is a coin
    toss that lands differently once records move, and it drowns the signal this
    finding exists to carry.
    """
    if not recs:
        return 0, 0
    base = _bases(recs)
    bounds = _boundaries(recs, base)
    tot = bad = 0
    for r in recs:
        if r.tokens is None:
            continue
        for t in r.tokens:
            if t.idx in script.NOT_A_BRANCH:
                continue
            for o in t.ops:
                if o.kind != "rel16":
                    continue
                tot += 1
                if vmops.rel16_target(base[r.id], t, o) not in bounds:
                    bad += 1
    return tot, bad


@dataclass
class Report:
    files: int = 0
    changed: int = 0
    rel16: int = 0
    findings: "list[str]" = field(default_factory=list)

    def say(self, kind: str, msg: str) -> None:
        self.findings.append("%-17s %s" % (kind, msg))


def _anchors(rec):
    """Byte offsets of the record's non-inline opcodes -- its structural spine.

    Finding 1 proves this sequence is identical on both sides, so an index into
    it is a stable name for a place in the script even though every byte offset
    around it may have moved.  Keying on a byte offset or a token index instead
    produces false alarms wherever text re-tiled, which is everywhere.
    """
    if rec.tokens is None:
        return None
    return [t.off for t in rec.tokens
            if t.kind == "op" and t.idx not in codec.INLINE_OPS]


def _destination(recs, base, anchors, target):
    """A relocation-independent name for the place a branch points at."""
    for r in recs:
        lo = base[r.id]
        if not lo <= target <= lo + len(r.data):
            continue
        off = target - lo
        a = anchors.get(r.id)
        if a is None:
            return (r.id, "untiled")
        if off == len(r.data):
            return (r.id, "end")
        for k, at in enumerate(a):
            if at == off:
                return (r.id, "op", k)
        return (r.id, "after-op", sum(1 for at in a if at < off))
    return ("outside",)


def _audit_destinations(rel, ci, ra, rb, rep):
    """Finding 3: does every real branch still reach the same instruction?"""
    ba, bb = _bases(ra), _bases(rb)
    aa = {r.id: _anchors(r) for r in ra}
    ab = {r.id: _anchors(r) for r in rb}
    for pa, pb in zip(ra, rb):
        if pa.tokens is None or pb.tokens is None:
            continue
        ta = [t for t in pa.tokens
              if t.kind == "op" and t.idx not in codec.INLINE_OPS]
        tb = [t for t in pb.tokens
              if t.kind == "op" and t.idx not in codec.INLINE_OPS]
        if len(ta) != len(tb):
            continue                      # finding 1 has already reported this
        for k, (x, y) in enumerate(zip(ta, tb)):
            if x.idx in script.NOT_A_BRANCH:
                continue                  # not a branch; where it points is noise
            for ox, oy in zip(x.ops, y.ops):
                if ox.kind != "rel16":
                    continue
                da = _destination(ra, ba, aa,
                                  vmops.rel16_target(ba[pa.id], x, ox))
                db = _destination(rb, bb, ab,
                                  vmops.rel16_target(bb[pb.id], y, oy))
                if da == db or da == ("outside",):
                    continue              # unchanged, or already dead in source
                rep.say("branch-moved",
                        "%s c%d r%02X opcode %d (%03X): reached %s, now reaches %s"
                        % (rel, ci, pa.id, k, x.idx, da, db))


def audit_file(rel: str, src: bytes, built: bytes, rep: Report) -> None:
    sa = script.parse(rel, src)
    sb = script.parse(rel, built)
    if not sa.ok:
        return                      # not a script file; the builder copies it
    if not sb.ok:
        rep.say("unparseable", "%s: the build no longer parses (%s)"
                % (rel, sb.error))
        return
    if len(sa.containers) != len(sb.containers):
        rep.say("framing", "%s: container count %d -> %d"
                % (rel, len(sa.containers), len(sb.containers)))
        return

    for ci, (ra, rb) in enumerate(zip(sa.containers, sb.containers)):
        if [r.id for r in ra] != [r.id for r in rb]:
            rep.say("framing", "%s c%d: the record id list changed" % (rel, ci))
            continue

        end = _image_end(rb)
        if end >= PC_LIMIT:
            rep.say("image-size",
                    "%s c%d: runtime image is 0x%X, past the u16 PC limit 0x%X "
                    "(source was 0x%X)" % (rel, ci, end, PC_LIMIT, _image_end(ra)))
        for pa, pb in zip(ra, rb):
            if len(pb.data) > RECORD_LIMIT:
                rep.say("record-size",
                        "%s c%d r%02X: %d bytes; the loader's signed 16-bit delta "
                        "caps a record at %d (source was %d)"
                        % (rel, ci, pb.id, len(pb.data), RECORD_LIMIT, len(pa.data)))

        _, ba = _unresolvable(ra)
        tb, bb = _unresolvable(rb)
        rep.rel16 += tb
        if bb > ba:
            rep.say("branches",
                    "%s c%d: %d branch displacements no longer reach an "
                    "instruction (the source had %d)" % (rel, ci, bb, ba))

        for pa, pb in zip(ra, rb):
            xa, xb = _structural(pa), _structural(pb)
            if (xa is None) != (xb is None):
                rep.say("tiling", "%s c%d r%02X: the record changed tileability"
                        % (rel, ci, pa.id))
                continue
            if xa is None:
                continue
            if xa != xb:
                k = next((i for i, (u, v) in enumerate(zip(xa, xb)) if u != v),
                         min(len(xa), len(xb)))
                rep.say("opcodes",
                        "%s c%d r%02X: structural opcode %d differs (%r -> %r), "
                        "%d -> %d opcodes"
                        % (rel, ci, pa.id, k,
                           xa[k] if k < len(xa) else None,
                           xb[k] if k < len(xb) else None, len(xa), len(xb)))
                continue
        _audit_destinations(rel, ci, ra, rb, rep)


def run(build_dir: "str | None" = None, root: "str | None" = None,
        quiet: bool = False, show: int = 40) -> Report:
    build_dir = build_dir or os.path.join(paths.BUILD_DIR, "ddswin_v2")
    rep = Report()
    for rel in files.all_encoded(root):
        src = files.read_source(rel, root)
        dst = os.path.join(build_dir, *rel.split("/"))
        if not os.path.exists(dst):
            rep.say("missing", "%s is not in the build" % rel)
            continue
        with open(dst, "rb") as fh:
            built = fh.read()
        rep.files += 1
        if built == src:
            continue
        rep.changed += 1
        audit_file(rel, src, built, rep)

    if not quiet:
        print("audited %d files against %s" % (rep.files, build_dir))
        print("  %d files differ from the source, %d branch displacements checked"
              % (rep.changed, rep.rel16))
        for line in rep.findings[:show]:
            print("  " + line)
        if len(rep.findings) > show:
            print("  ... and %d more findings" % (len(rep.findings) - show))
        if not rep.findings:
            print("  no control-flow differences: the build runs the same script")
    return rep
