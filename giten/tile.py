"""The tiling census, and the engine's own answer to it.

Two commands live here.

``giten tile census`` prints every record the model does not tile cleanly, with
its state and the error, and the totals.  It is the standing measurement of what
is left.

``giten tile observe <trace.bin> --build <tree>`` turns a trace taken on a warp
tree into the engine's own tiling of the records that trace executed, compares it
with the model's token starts, and writes one fixture per record so a later model
change cannot silently break a record the engine has already answered for.

Why the engine's answer is different in kind
--------------------------------------------
Every other check in this repo compares the model with itself: extraction and the
byte build use the same tokenizer, so a checker that re-parses both sides cannot
see an error *in* the model.  A trace can, because the dev exe logs one record
per token dispatch and the program counter it logs is the engine's, not ours.

Reading a boundary out of an event
----------------------------------
``pc0`` is **one past the token's first byte**, not the token's address: the
interpreter fetches that byte (two, for a wide character) before calling
``exec_token``, and the fetch is what advances the program counter -- an
opcode's operands are consumed later, inside the handler.  So

    boundary = pc0 - (2 if ch > 0xFF else 1) - idx_off

in the record's own coordinates, where ``idx_off`` is the engine's own index
entry for the record the *program counter* is in.  Three gates, all of them
load-bearing:

* **``REC_FROM_PC`` required, ``VIRTUAL`` excluded** (v5).  A virtual program
  counter (at or above the image end) names no record at all -- every record's
  overlay tails begin there -- and an event whose scan found nothing carries
  ``ds:RECID``, an engine global written on *load*, which routinely names a
  record the interpreter is not in.  Neither says anything about boundaries.
* **The program counter must be inside the record the event names.**  On a v5
  event with ``REC_FROM_PC`` that holds by construction.  On a **v4** trace the
  record always comes from the stale global, so this is the gate that makes such
  an event usable at all: if ``pc0 - width`` lands inside the logged index entry
  *and* the next check passes, the record the global named is demonstrably the
  record the program counter is in, and nothing is being assumed.  That is why
  v4 is accepted here and refused by ``trace verify`` -- verify has to judge
  every event, this only has to collect the ones that judge themselves.
* **The character has to check out.**  The logged ``ch`` must equal the bytes at
  the offset it resolves to.  This is the same self-check that separated 18,659
  real events from 39 impostors in the 2026-09-06 pass; without it a stale
  triple contributes a boundary to a record it never touched.

Records are identified by **content** -- ``(record id, length, FNV-1a)`` -- not by
the trace's file label, for the same reason overlay v6 is: the label is written
on load and routinely names a script that is not running.
"""
from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass, field

from . import container, files, overlay, paths, records, script
from .trace import core

OBSERVED_DIR = os.path.join(paths.REPO_ROOT, "tests", "data", "observed")

#: Census states.  ``data`` is not a tiling result: it says the file is never
#: opened by the script loader at all, so its records are not code and the
#: tokenizer's opinion of them is beside the point (see ``docs/limits.md``).
TILED, STRADDLE, PREFIX, UNTILED, DATA = "tiled", "straddle", "prefix", "untiled", "data"


# --- the census -------------------------------------------------------------
@dataclass
class Row:
    rel: str
    ci: int
    rec_id: int
    length: int
    state: str
    error: "str | None" = None

    def key(self):
        return (self.rel, self.ci, self.rec_id)


def data_files() -> "frozenset[str]":
    """Files the script loader never opens.  See :mod:`giten.loaders`."""
    from . import loaders
    return loaders.DATA_FILES


def census(root: "str | None" = None, families=("ms", "id")) -> "list[Row]":
    """Every record of every script file, as a census row."""
    root = root or paths.game_root()
    data = data_files()
    out = []
    for rel in files.iter_files(families, root):
        sc = script.parse(rel, files.read_source(rel, root))
        if not sc.ok:
            continue
        for ci, cont in enumerate(sc.containers):
            for r in cont:
                if not r.data:
                    continue
                if rel in data:
                    state, err = DATA, None
                elif r.blocked == script.PREFIX_NOTE:
                    state, err = PREFIX, r.tile_error
                elif r.blocked == script.STRADDLE_NOTE:
                    state, err = STRADDLE, r.tile_error
                elif r.tokens is None:
                    state, err = UNTILED, r.tile_error
                else:
                    state, err = TILED, None
                out.append(Row(rel, ci, r.id, len(r.data), state, err))
    return out


def residue(rows=None, root=None) -> "list[Row]":
    rows = census(root) if rows is None else rows
    return [r for r in rows if r.state != TILED]


def census_report(rows=None, root=None) -> str:
    rows = census(root) if rows is None else rows
    res = residue(rows)
    lines = ["%-16s %-4s %-5s %6s  %-9s %s"
             % ("file", "cont", "rec", "bytes", "state", "error"),
             "-" * 96]
    for r in res:
        if r.state == DATA:
            continue                # summarised per file below; see giten/loaders
        lines.append("%-16s c%-3d r%02X  %6d  %-9s %s"
                     % (r.rel, r.ci, r.rec_id, r.length, r.state, r.error or ""))
    per_file = {}
    for r in res:
        if r.state == DATA:
            per_file[r.rel] = per_file.get(r.rel, 0) + 1
    for rel in sorted(per_file):
        lines.append("%-16s %s  %d records, never opened by the script loader "
                     "(giten/loaders.py)" % (rel, " " * 22, per_file[rel]))
    totals = {}
    for r in rows:
        totals[r.state] = totals.get(r.state, 0) + 1
    lines.append("-" * 96)
    lines.append("%d records in %d files; %s"
                 % (len(rows), len({r.rel for r in rows}),
                    ", ".join("%s %d" % (k, totals[k]) for k in
                              (TILED, STRADDLE, PREFIX, UNTILED, DATA)
                              if totals.get(k))))
    return "\n".join(lines)


# --- the engine's own tiling ------------------------------------------------
@dataclass
class Ev:
    n: int
    file: int
    rec: int
    pc: int
    ch: int
    idx_off: int
    idx_len: int
    pc0: int
    flags: int
    rec_hash: int
    image_end: int
    handle: int

    @property
    def virtual(self) -> bool:
        return bool(self.flags & core.VIRTUAL)

    @property
    def from_pc(self) -> bool:
        return bool(self.flags & core.REC_FROM_PC)

    @property
    def width(self) -> int:
        return 2 if self.ch > 0xFF else 1


class TooOld(ValueError):
    pass


def read_events(path: str):
    """``(version, iterator of Ev)`` for a v4 or v5 trace.  Refuses anything older.

    v3 and below log no ``rec_hash``, and without it a record cannot be
    identified by content -- only by the file label, which is the thing that
    cannot be trusted.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    rs, body = core._pick(data, path)
    ver = {core.RECORD_V4: 4, core.RECORD_V5: 5}.get(rs)
    if ver is None:
        raise TooOld("%s carries no record hash; `tile observe` identifies a "
                     "record by its content, so it needs v4 or better" % path)

    def gen():
        for i in range(len(body) // rs.size):
            f = rs.unpack_from(body, i * rs.size)
            yield Ev(i, f[0], f[1], f[2], f[3], f[7], f[8], f[9], f[10], f[12],
                     f[13], f[14] if ver >= 5 else 0)
    return ver, gen()


def record_index(root: "str | None" = None) -> "dict[tuple[int, int, int], list]":
    """``{(id, length, FNV-1a): [(rel, ci, rec_id, bytes)]}`` over a tree.

    The same key the overlay uses.  A key can name more than one place: 92
    ``(id, offset, length)`` slots in the corpus hold more than one record and
    byte-identical records across files are one key by construction.  Every
    match is kept, and ``observe`` reports when a key is not unique.
    """
    root = root or paths.game_root()
    out = {}
    for sub in ("m", "et"):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.lower().endswith(".bin"):
                continue
            rel = "%s/%s" % (sub, name)
            try:
                with open(os.path.join(d, name), "rb") as fh:
                    conts, _ = container.split(fh.read())
            except Exception:
                continue
            for c in conts:
                try:
                    recs = records.parse_body(c.body).records
                except Exception:
                    continue
                for r in recs:
                    if not r.data:
                        continue
                    key = (r.id, len(r.data), overlay.fnv1a(r.data))
                    out.setdefault(key, []).append((rel, c.index, r.id, r.data))
    return out


def served_keys(build_dir: str) -> "frozenset[tuple]":
    """``(id, length, hash)`` of every record a build tree's overlay translates.

    A record the overlay serves is one the engine was handed *different bytes*
    for, so its program counters say nothing about the Japanese tokenisation.
    Measured, not assumed: the keys come out of ``overlay.dat`` itself, which is
    the same table the hook matches on.
    """
    path = os.path.join(build_dir, "overlay.dat")
    if not os.path.exists(path):
        return frozenset()
    with open(path, "rb") as fh:
        entries = overlay.parse(fh.read())
    return frozenset(e.key for e in entries)


@dataclass
class Seen:
    """What the engine did inside one record."""
    rel: str
    ci: int
    rec_id: int
    data: bytes
    ambiguous: bool = False
    boundaries: "set[int]" = field(default_factory=set)
    events: int = 0
    self_check_failed: int = 0


@dataclass
class Report:
    version: int = 0
    events: int = 0
    usable: int = 0
    virtual: int = 0
    not_from_pc: int = 0
    no_record: int = 0
    unplaced: int = 0
    out_of_record: int = 0
    self_check_failed: int = 0
    overlaid: int = 0
    served_keys: int = 0
    seen: "dict" = field(default_factory=dict)

    @property
    def agree(self) -> int:
        return sum(s["agree"] for s in self.seen.values())

    @property
    def disagree(self) -> int:
        return sum(len(s["disagree"]) for s in self.seen.values())


def observe(trace_path: str, build_dir: "str | None" = None) -> Report:
    """The engine's boundaries per record, against the model's token starts."""
    build_dir = build_dir or paths.game_root()
    index = record_index(build_dir)
    served = served_keys(build_dir)
    ver, events = read_events(trace_path)
    rep = Report(version=ver, served_keys=len(served))
    found: "dict[tuple, Seen]" = {}
    for ev in events:
        rep.events += 1
        if ver >= 5:
            if ev.virtual:
                rep.virtual += 1
                continue
            if not ev.from_pc:
                rep.not_from_pc += 1
                continue
        if not ev.idx_len or not ev.pc0:
            rep.no_record += 1
            continue
        key = (ev.rec, ev.idx_len, ev.rec_hash)
        if key in served:
            # The overlay answered addresses inside this record, so the bytes the
            # engine was handed are not the bytes on disk and a boundary read off
            # this event would be measured against the wrong text.  Dropped, not
            # judged.  A warp tree has no overlay.dat, which is the whole reason
            # `giten warp` builds one without it.
            rep.overlaid += 1
            continue
        hit = index.get(key)
        if not hit:
            rep.unplaced += 1
            continue
        rel, ci, rec_id, data = hit[0]
        off = ev.pc0 - ev.width - ev.idx_off
        if not (0 <= off and off + ev.width <= len(data)):
            # v4: the record came from the stale global and the pc is not in it,
            # so nothing can be concluded.  v5 with REC_FROM_PC: only a wide
            # character straddling the record's first byte can land here.
            rep.out_of_record += 1
            continue
        want = (bytes([ev.ch >> 8, ev.ch & 0xFF]) if ev.ch > 0xFF
                else bytes([ev.ch]))
        if data[off:off + ev.width] != want:
            rep.self_check_failed += 1
            continue
        s = found.get((rel, ci, rec_id))
        if s is None:
            s = found[(rel, ci, rec_id)] = Seen(rel, ci, rec_id, data,
                                                ambiguous=len(hit) > 1)
        s.events += 1
        rep.usable += 1
        s.boundaries.add(off)

    sc_cache = {}
    for (rel, ci, rec_id), s in sorted(found.items()):
        if rel not in sc_cache:
            sc_cache[rel] = script.parse(rel, files.read_source(rel, build_dir))
        sc = sc_cache[rel]
        rec = next((r for r in sc.containers[ci] if r.id == rec_id), None)
        toks = rec.span_tokens if rec is not None else None
        starts = {t.off for t in toks} if toks else set()
        agree = sorted(b for b in s.boundaries if b in starts)
        disagree = sorted(b for b in s.boundaries if b not in starts)
        rep.seen[(rel, ci, rec_id)] = {
            "rel": rel, "ci": ci, "rec": rec_id, "len": len(s.data),
            "hash": overlay.fnv1a(s.data),
            "state": (UNTILED if toks is None else
                      (rec.blocked or TILED).lstrip("@")),
            "events": s.events, "ambiguous_key": s.ambiguous,
            "boundaries": sorted(s.boundaries),
            "agree": len(agree), "disagree": disagree,
            "model_only": sorted(t for t in starts if t not in s.boundaries),
            "model_tokens": len(starts),
        }
    return rep


def observe_report(rep: Report, verbose: bool = True) -> str:
    lines = ["v%d trace, %d events: %d usable, %d virtual, %d without "
             "REC_FROM_PC, %d with no record, %d in a record the overlay "
             "serves (%d such keys), %d whose record content is in no file, "
             "%d whose record does not contain pc0, %d failing the character "
             "self-check"
             % (rep.version, rep.events, rep.usable, rep.virtual,
                rep.not_from_pc, rep.no_record, rep.overlaid, rep.served_keys,
                rep.unplaced, rep.out_of_record, rep.self_check_failed),
             ""]
    lines.append("%-16s %-4s %-5s %-9s %7s %8s %9s %11s"
                 % ("file", "cont", "rec", "state", "events", "agree",
                    "disagree", "never seen"))
    lines.append("-" * 84)
    for key in sorted(rep.seen):
        s = rep.seen[key]
        lines.append("%-16s c%-3d r%02X  %-9s %7d %8d %9d %11d"
                     % (s["rel"], s["ci"], s["rec"], s["state"], s["events"],
                        s["agree"], len(s["disagree"]), len(s["model_only"])))
    lines.append("-" * 84)
    lines.append("%d records observed, %d engine boundaries agree, %d disagree"
                 % (len(rep.seen), rep.agree, rep.disagree))
    if verbose:
        for key in sorted(rep.seen):
            s = rep.seen[key]
            if not s["disagree"]:
                continue
            lines.append("")
            lines.append("%s c%d r%02X:" % (s["rel"], s["ci"], s["rec"]))
            toks = _model_tokens(s["rel"], s["ci"], s["rec"])
            for off in s["disagree"]:
                t = _enclosing(toks, off)
                lines.append("   engine starts a token at 0x%04X; the model has "
                             "%s there" % (off, t))
    return "\n".join(lines)


def _model_tokens(rel, ci, rec_id, root=None):
    sc = script.parse(rel, files.read_source(rel, root))
    rec = next((r for r in sc.containers[ci] if r.id == rec_id), None)
    return (rec.span_tokens or []) if rec is not None else []


def _enclosing(toks, off) -> str:
    for t in toks:
        if t.off <= off < t.off + t.size:
            kind = "text" if t.kind == "text" else "opcode 0x%03X" % t.idx
            return "%s starting at 0x%04X, %d bytes" % (kind, t.off, t.size)
    return "no token (the walk never reached that byte)"


def fixture_name(rel: str, ci: int, rec_id: int) -> str:
    return "%s_c%d_r%02X.json" % (os.path.basename(rel).replace(".BIN", ""),
                                  ci, rec_id)


def write_fixtures(rep: Report, trace_path: str, out_dir: str = OBSERVED_DIR) -> "list[str]":
    """One fixture per observed record: the engine's boundaries, and nothing else."""
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for key in sorted(rep.seen):
        s = dict(rep.seen[key])
        s["trace"] = os.path.basename(trace_path)
        # the comparison is re-derived by the test; the fixture holds only what
        # the engine said, so a model change cannot quietly rewrite the evidence
        for drop in ("agree", "disagree", "model_only", "model_tokens", "state"):
            s.pop(drop, None)
        path = os.path.join(out_dir, fixture_name(s["rel"], s["ci"], s["rec"]))
        old = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                old = json.load(fh)
        if old.get("hash") == s["hash"]:
            # merge: two sessions of the same record are more evidence, not less
            s["boundaries"] = sorted(set(old.get("boundaries", [])) | set(s["boundaries"]))
            s["events"] = old.get("events", 0) + s["events"]
            s["trace"] = "%s, %s" % (old.get("trace", "?"), s["trace"])
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(s, fh, indent=1, sort_keys=True)
            fh.write("\n")
        written.append(path)
    return written


def load_fixtures(out_dir: str = OBSERVED_DIR) -> "list[dict]":
    if not os.path.isdir(out_dir):
        return []
    out = []
    for name in sorted(os.listdir(out_dir)):
        if name.endswith(".json"):
            with open(os.path.join(out_dir, name), encoding="utf-8") as fh:
                out.append(json.load(fh))
    return out
