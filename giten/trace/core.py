"""Decode and diff interpreter traces written by the dev exe's ``.trc`` hook.

A trace is a flat file of 12-byte records (see ``exe/trace.S``)::

    u16 file, u16 rec, u16 pc, u16 ch, i16 r, u8 capflag, u8 caplen

``decode`` maps each record back to the script: the hook logs after exec_token
returns, so ``pc`` is the byte after the whole token (operands included), and
the token is the one that *ends* there in the runtime image; the runtime
image is ``records.bases`` over the loaded container.  From the token we get the
span index, the same numbering the tables use -- so a trace line names a table
row.

``diff`` compares two traces for the same route on different builds.  Byte
offsets differ between a Japanese and an English build, so records are first
normalised to *structural events* ``(file, rec, anchor, kind)`` where ``anchor``
is the number of non-inline opcodes before the token (the notion ``audit`` keys
on) and runs of text collapse to one ``TEXT`` event.  Two builds that run the
same script produce the same event sequence; the first difference is the bug,
and the record's ``r`` and ``caplen`` say which kind (``r == -1``: page full and
the interpreter loop exited; ``caplen`` near 255: capture-buffer overflow).

What this does not know
-----------------------
* Which *container* of a multi-container file (``m/MS6xxx``, ``et/ID*``) is
  loaded: the record carries no container index.  Container 0 is assumed and
  the self-check flags a mismatch.
* Whether ``FILEID``/``RECID`` are current on every path (they are written at
  two sites).  The self-check compares the logged ``ch`` with the bytes at the
  decoded offset; a run of mismatches means the globals were stale there.
"""
from __future__ import annotations

import difflib
import os
import struct
from dataclasses import dataclass

from .. import codec, files, paths, records, script, vmops

RECORD = struct.Struct("<HHHHhBB")


@dataclass
class Event:
    n: int                  # record index in the trace
    file: int
    rec: int
    pc: int
    ch: int
    r: int
    capflag: int
    caplen: int
    rel: str = ""           # "m/MS0017.BIN"
    span: "int | None" = None
    anchor: "int | None" = None
    kind: str = "?"         # opcode encoding, "TEXT", or "?"
    ok: bool = False        # self-check: logged ch matches the bytes at pc

    def key(self):
        return (self.rel, self.rec, self.anchor, self.kind)


def _rel_of(file_id: int) -> str:
    return "m/MS%04X.BIN" % file_id


class _Image:
    """One parsed script file: runtime bases and per-record token lookup."""

    def __init__(self, rel: str, raw: bytes):
        self.sc = script.parse(rel, raw)
        self.by_id = {}
        self.base = {}
        if self.sc.ok and self.sc.containers:
            recs = self.sc.containers[0]              # limitation: container 0
            self.base = records.bases([records.Record(r.id, r.data) for r in recs])
            for r in recs:
                self.by_id.setdefault(r.id, r)

    def locate(self, rec_id: int, pc: int, ch: int):
        r = self.by_id.get(rec_id)
        if r is None or r.tokens is None:
            return None
        # The hook logs *after* exec_token returns, and an opcode's handler has
        # consumed its operands by then -- so pc is the END of the token, for
        # text (1 or 2 bytes) and opcodes alike.  Measured: consecutive opcode
        # steps in a real trace sit exactly one token length apart.
        end = pc - self.base[rec_id]
        if not 0 <= end <= len(r.data):
            return None
        want = bytes([ch]) if ch <= 0xFF else bytes([ch >> 8, ch & 0xFF])
        def hit(k, t, jumped):
            anchor = sum(1 for u in r.tokens[:k]
                         if u.kind == "op" and u.idx not in codec.INLINE_OPS)
            span = next((s.idx for s in r.spans if s.tok_lo <= k < s.tok_hi), None)
            if jumped:
                # a control opcode ran and execution *landed* here: name the
                # opcode that ran (ch) and the place it went (this token)
                kind = "%s->" % vmops.table().encoding(ch)
                return span, anchor, kind, ch < 0x20
            got = r.data[t.off:t.end]
            kind = "TEXT" if t.kind == "text" else vmops.table().encoding(t.idx)
            return span, anchor, kind, got == want or (t.kind == "op" and got[:1] == want[:1])
        # 1. the token that ends at pc: text, or an opcode that fell through
        for k, t in enumerate(r.tokens):
            if t.end == end and (t.kind == "text" or r.data[t.off] == ch):
                return hit(k, t, False)
        # 2. the token that starts at pc: a taken branch, a call, a return
        for k, t in enumerate(r.tokens):
            if t.off == end:
                return hit(k, t, True)
        return None


def decode(trace_path: str, build_dir: "str | None" = None) -> "list[Event]":
    """Every record of a trace, resolved against the build that produced it."""
    build_dir = build_dir or paths.game_root()
    with open(trace_path, "rb") as fh:
        data = fh.read()
    images = {}
    out = []
    for n in range(len(data) // RECORD.size):
        f, rec, pc, ch, r, capflag, caplen = RECORD.unpack_from(data, n * RECORD.size)
        ev = Event(n, f, rec, pc, ch, r, capflag, caplen, rel=_rel_of(f))
        if ev.rel not in images:
            p = os.path.join(build_dir, *ev.rel.split("/"))
            images[ev.rel] = _Image(ev.rel, open(p, "rb").read()) if os.path.exists(p) else None
        img = images[ev.rel]
        hit = img.locate(rec, pc, ch) if img else None
        if hit:
            ev.span, ev.anchor, ev.kind, ev.ok = hit
        out.append(ev)
    return out


def normalise(events: "list[Event]") -> "list[Event]":
    """Collapse runs of text into one event per (file, rec, anchor)."""
    out = []
    for ev in events:
        if out and ev.kind == "TEXT" and out[-1].kind == "TEXT" and out[-1].key() == ev.key():
            out[-1].r = ev.r                      # keep the *last* r of the run
            out[-1].caplen = max(out[-1].caplen, ev.caplen)
            continue
        out.append(ev)
    return out


def diff(jp_trace: str, en_trace: str, jp_build: str, en_build: str, context: int = 6):
    """First divergence between two traces of the same route.

    Returns ``(index_jp, index_en, jp_events, en_events)`` or ``None`` when the
    normalised event sequences are identical.
    """
    a = normalise(decode(jp_trace, jp_build))
    b = normalise(decode(en_trace, en_build))
    sm = difflib.SequenceMatcher(None, [e.key() for e in a], [e.key() for e in b], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            return i1, j1, a, b
    return None


def describe(ev: Event) -> str:
    where = "%s r%02X" % (ev.rel, ev.rec)
    if ev.span is not None:
        where += "[%d]" % ev.span
    return "%-24s anchor=%-5s %-6s pc=0x%04X ch=0x%04X r=%d cap=%s/%d%s" % (
        where, ev.anchor, ev.kind, ev.pc, ev.ch, ev.r, "on" if ev.capflag else "off",
        ev.caplen, "" if ev.ok else "  (self-check: bytes at pc differ)")


def report_diff(jp_trace, en_trace, jp_build, en_build, context=6) -> str:
    res = diff(jp_trace, en_trace, jp_build, en_build)
    if res is None:
        return "no divergence: both traces run the same script"
    i, j, a, b = res
    lines = ["first divergence at JP event %d / EN event %d" % (i, j), "", "JP:"]
    for ev in a[max(0, i - context):i + 2]:
        lines.append(("  >> " if ev is a[i] else "     ") + describe(ev))
    lines += ["", "EN:"]
    for ev in b[max(0, j - context):j + 2]:
        lines.append(("  >> " if ev is b[j] else "     ") + describe(ev))
    return "\n".join(lines)


def selfcheck(trace_path: str, build_dir: str) -> "tuple[int, int]":
    """``(records, records whose logged bytes did not match the build)``."""
    evs = decode(trace_path, build_dir)
    return len(evs), sum(1 for e in evs if not e.ok)
