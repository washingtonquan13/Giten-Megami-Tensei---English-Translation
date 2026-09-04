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

2. **Branch resolvability** -- how many ``rel16`` displacements fail to land on
   an instruction boundary.  A file is allowed to have some in the source (the
   recovered opcode table mis-tiles a little; see ``docs/format-notes.md``
   section 2.10), but the build must never have *more* than the source did.
   This is the test that catches a mis-relocation, and it needs no token pairing
   between the two sides, so a record whose text re-tiled cannot raise a false
   alarm.

3. **Branches into edited text** -- a jump whose target is strictly inside a run
   of text that this build replaced points at a byte that no longer exists.
   :func:`script._drop_branched_into` is supposed to make this impossible by
   skipping the edit; this is the independent proof that it did.

4. **Runtime image size** -- the script PC is a ``u16``, so a container's image
   must stay under 0x10000, and growing text is the one thing that can push it
   there.

Exit status is non-zero if any finding is reported.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import codec, files, paths, records, script, vmops

#: The script PC is a u16 (``docs/format-notes.md`` section 2.3), so nothing in
#: a container's runtime image may sit at or past this offset.
PC_LIMIT = 0x10000


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


def _segments(rec):
    """Alternating ``("op"|"run", start, end)`` spans of one record's bytes."""
    if rec.tokens is None:
        return None
    segs = []
    run = None
    for t in rec.tokens:
        if t.kind == "op" and t.idx not in codec.INLINE_OPS:
            if run:
                segs.append(("run", run[0], run[1]))
                run = None
            segs.append(("op", t.off, t.end))
        else:
            run = [t.off, t.end] if run is None else [run[0], t.end]
    if run:
        segs.append(("run", run[0], run[1]))
    return segs


def _unresolvable(recs) -> "tuple[int, int]":
    """``(rel16 count, how many miss every instruction boundary)``."""
    if not recs:
        return 0, 0
    base = _bases(recs)
    bounds = _boundaries(recs, base)
    tot = bad = 0
    for r in recs:
        if r.tokens is None:
            continue
        for t in r.tokens:
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


def _audit_branch_into_edit(rel, ci, pa, pb, ra, rep):
    """Finding 3, for one record whose bytes this build changed."""
    sga, sgb = _segments(pa), _segments(pb)
    if sga is None or sgb is None:
        return
    base_a = _bases(ra)
    lo = base_a[pa.id]
    for r in ra:
        if r.tokens is None:
            continue
        for t in r.tokens:
            for o in t.ops:
                if o.kind != "rel16":
                    continue
                tgt = vmops.rel16_target(base_a[r.id], t, o)
                if not lo <= tgt < lo + len(pa.data):
                    continue
                off = tgt - lo
                si = next((i for i, (k, s, e) in enumerate(sga)
                           if k == "run" and s < off < e), None)
                if si is None or si >= len(sgb):
                    continue
                _, s, e = sga[si]
                _, s2, e2 = sgb[si]
                if pa.data[s:e] != pb.data[s2:e2]:
                    rep.say("branch-into-edit",
                            "%s c%d r%02X: a branch targets byte %d of a text "
                            "run this build replaced" % (rel, ci, pa.id, off - s))


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
            if pa.data != pb.data:
                _audit_branch_into_edit(rel, ci, pa, pb, ra, rep)


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
