"""Decode and diff interpreter traces written by the dev exe's ``.trc`` hook.

A trace is a flat file of fixed-size records (see ``exe/trace.S``).  v2 carries
an 8-byte ``"GTRC"`` header and 20-byte records::

    u16 file, u16 rec, u16 pc, u16 ch, i16 r, u8 capflag, u8 caplen,
    u16 idx_off, u16 idx_len, u16 pc0, u16 flags

v1 is headerless with 16-byte records (no ``pc0``/``flags``); both decode, since
the traces taken before 2026-09-06 are still the oracle the opcode model is
checked against.

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

Closed in v2: a token that *ended* a script used to be unplaceable.  The engine
clears the context when a script ends, and v1 read ``file``/``rec``/``pc`` and
the index entry only after ``exec_token`` returned -- so all four came back
zero.  That was 106 of 18,683 events on the traced routes, a hole in the oracle
rather than in the model.  v2 snapshots them before the call and adds ``pc0``,
the PC the token started at, which places the event even when the post-call PC
is gone.  ``pc0`` with ``pc`` also gives the engine's own length for every
token, which is the thing an operand model is judged on.
"""
from __future__ import annotations

import difflib
import os
import struct
from dataclasses import dataclass

from .. import codec, files, overlay, paths, records, script, vmops

#: v1: file, rec, pc, ch, r, capflag, caplen, idx_off, idx_len.  Headerless, and
#: everything was read *after* exec_token returned -- so a token that ended a
#: script logged pc 0 and idx_off 0, because the engine had already cleared the
#: context.  Those events cannot be placed at all.  Kept because the traces taken
#: before 2026-09-06 are still the oracle.
RECORD_V1 = struct.Struct("<HHHHhBBHH")

#: v2 adds pc0 (the PC *before* the token, i.e. where it starts) and flags, and
#: takes file/rec/pc0/idx from a snapshot made before the call, when the context
#: is guaranteed live.  Behind an 8-byte header so both formats decode.
RECORD_V2 = struct.Struct("<HHHHhBBHHHH")
MAGIC = b"GTRC"
HEADER = struct.Struct("<4sHH")

#: ``flags``
CTX_NULL_BEFORE = 1
CTX_NULL_AFTER = 2

RECORD = RECORD_V1          # kept for callers that only want the v1 field order


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
    idx_off: int = 0        # where the ENGINE put this record (0 = not logged)
    idx_len: int = 0        # how long the ENGINE thinks it is
    pc0: int = 0            # PC before the token ran, i.e. where it starts (v2)
    flags: int = 0          # CTX_NULL_BEFORE | CTX_NULL_AFTER (v2)
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

    def __init__(self, rel: str, raw: bytes, entries=None):
        self.sc = script.parse(rel, raw)
        self.by_id = {}
        self.base = {}
        self.entry = None                             # overlay entry, if the build has one
        if self.sc.ok and self.sc.containers:
            recs = self.sc.containers[0]              # limitation: container 0
            rr = [records.Record(r.id, r.data) for r in recs]
            self.base = records.bases(rr)
            for r in recs:
                self.by_id.setdefault(r.id, r)
            if entries:
                fid, fp = int(rel[4:8], 16), overlay.fingerprint(rr)
                self.entry = next((e for e in entries if e.fid == fid and e.fp == fp), None)

    def _overlay_hit(self, pc: int, ch: int):
        """A logged pc produced by the overlay: inside a virtual range, or the
        real span end the last English byte hands the PC back to."""
        e = self.entry
        if e is None:
            return None
        for s in e.spans:
            # inside the in-place head, inside the virtual tail, or the hand-back to s.end after the
            # last English token -- which must then be what was logged: the
            # last character, or the opcode byte of a trailing inline opcode
            # (a page wait or newline ending the line).  A jump can land on
            # s.end too, and its ch is a different opcode, so it is not taken.
            toks = vmops.tokenize(s.data)
            lt = toks[-1]
            if lt.kind == "op":
                last, kind = s.data[lt.off], vmops.table().encoding(lt.idx)
            else:
                last, kind = int.from_bytes(s.data[lt.off:lt.end], "big"), "TEXT"
            in_head = s.start < pc <= s.start + s.head
            in_tail = s.tail and s.virt < pc <= s.vend
            if in_head or in_tail:
                kind = "TEXT"
            if in_head or in_tail or (pc == s.end and ch == last):
                rec_id = max((i for i, b in self.base.items() if b <= s.start), default=None)
                r = self.by_id.get(rec_id)
                if r is None or r.tokens is None:
                    return None
                off = s.start - self.base[rec_id]
                k = next((i for i, t in enumerate(r.tokens) if t.off == off), None)
                if k is None:
                    return None
                anchor = sum(1 for u in r.tokens[:k] if u.kind == "op" and u.idx not in codec.INLINE_OPS)
                span = next((sp.idx for sp in r.spans if sp.tok_lo <= k < sp.tok_hi), None)
                return span, anchor, kind, True
        return None

    def locate(self, rec_id: int, pc: int, ch: int, base: "int | None" = None,
               pc0: "int | None" = None):
        r = self.by_id.get(rec_id)
        if r is None or r.tokens is None:
            return None
        # The hook logs *after* exec_token returns, and an opcode's handler has
        # consumed its operands by then -- so pc is the END of the token, for
        # text (1 or 2 bytes) and opcodes alike.  Measured: consecutive opcode
        # steps in a real trace sit exactly one token length apart.
        # ``base`` is the engine's own index entry when the trace carries it;
        # our model's base is only the fallback.
        hit_ = self._overlay_hit(pc, ch)
        if hit_ is not None:
            return hit_
        b = base if base else self.base[rec_id]
        end = pc - b
        if not 0 <= end <= len(r.data):
            # a v2 trace can still place this by where the token started
            if pc0 is None:
                return None
            end = -1
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
        # 3. v2 only: the token that *starts* at pc0.  The post-call pc is 0
        #    whenever the token ended the script, because the engine clears the
        #    context before the hook reads it back -- but pc0 was snapshotted
        #    before the call and is always good.  This is what rescues those
        #    events; it is a weaker anchor than 1., so it is tried last.
        if pc0 is not None:
            start = pc0 - b
            if 0 <= start < len(r.data):
                for k, t in enumerate(r.tokens):
                    if t.off == start:
                        return hit(k, t, False)
        return None


def decode(trace_path: str, build_dir: "str | None" = None) -> "list[Event]":
    """Every record of a trace, resolved against the build that produced it."""
    build_dir = build_dir or paths.game_root()
    with open(trace_path, "rb") as fh:
        data = fh.read()
    entries = None
    ovl = os.path.join(build_dir, "overlay.dat")
    if os.path.exists(ovl):
        with open(ovl, "rb") as fh:
            entries = overlay.parse(fh.read())
    if data[:4] == MAGIC:
        _, ver, size = HEADER.unpack_from(data, 0)
        if ver != 2 or size != RECORD_V2.size:
            raise ValueError("%s: unknown trace format v%d, %d-byte records"
                             % (trace_path, ver, size))
        rs, body = RECORD_V2, data[HEADER.size:]
    else:
        rs, body = RECORD_V1, data          # pre-2026-09-06, headerless
    images = {}
    out = []
    for n in range(len(body) // rs.size):
        f = rs.unpack_from(body, n * rs.size)
        pc0, flags = (f[9], f[10]) if rs is RECORD_V2 else (0, 0)
        ev = Event(n, f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8],
                   pc0, flags, rel=_rel_of(f[0]))
        if ev.rel not in images:
            p = os.path.join(build_dir, *ev.rel.split("/"))
            images[ev.rel] = _Image(ev.rel, open(p, "rb").read(), entries) if os.path.exists(p) else None
        img = images[ev.rel]
        hit = img.locate(ev.rec, ev.pc, ev.ch, ev.idx_off or None,
                         ev.pc0 or None) if img else None
        if hit:
            ev.span, ev.anchor, ev.kind, ev.ok = hit
        out.append(ev)
    return out


POOL_CALLS = {"%02X->" % k for k in range(1, 9)}
#: inline opcodes (newline ``0A``, page wait ``1E10``): translators add and
#: remove these freely inside a span, so they are text, not flow
INLINE_KINDS = {vmops.table().encoding(k) for k in codec.INLINE_OPS} - POOL_CALLS
MAX_CYCLE = 12


def normalise(events: "list[Event]") -> "list[Event]":
    """Reduce a trace to the structural flow two builds must share.

    Three things that legitimately differ between a Japanese and an English run
    are folded away, each learned from the first real pair of traces:

    * **text** -- runs of characters collapse to one TEXT event per anchor;
    * **pool words** -- a ``01``-``08`` call and everything executed inside the
      pool files ``m/MS7F0x`` is part of the text run (English inlines the
      dictionary word the Japanese fetched), so those events become TEXT too;
    * **inline opcodes** -- newlines and page waits inside a span are re-flowed
      by the translator, so they fold into the text run as well;
    * **idle polling** -- the engine spins in a tiny cycle (``1F57`` / jump /
      jump / ``18`` back in ``m/MS002D`` r01) until input arrives, so how long
      the player waited shows up as thousands of repeated events.  Immediately
      repeating cycles of up to :data:`MAX_CYCLE` events collapse to one.
    """
    out = []
    for ev in events:
        if ev.rel.startswith("m/MS7F0") or ev.kind in POOL_CALLS:
            continue                          # a word, not flow: see above
        if ev.kind in INLINE_KINDS:
            ev.kind = "TEXT"                  # a newline or page wait is part of the text
        if out and ev.kind == "TEXT" and out[-1].kind == "TEXT" and out[-1].key() == ev.key():
            out[-1].r = ev.r                      # keep the *last* r of the run
            out[-1].caplen = max(out[-1].caplen, ev.caplen)
            continue
        out.append(ev)
        # drop an immediate repeat of the last p events, for any small p
        for p_ in range(1, MAX_CYCLE + 1):
            if len(out) >= 2 * p_ and [e.key() for e in out[-p_:]] == [e.key() for e in out[-2 * p_:-p_]]:
                del out[-p_:]
                break
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


def bases(trace_path: str, build_dir: str):
    """The engine's record placement against our model, per (file, record).

    Returns ``[(rel, rec, engine_off, engine_len, model_off, model_len)]`` for
    every record the trace visited with the index entry logged.  Any non-zero
    difference is the layout rule we have not modelled; the whole point of
    logging the entry is to read that rule off real numbers instead of fitting
    a theory to displaced branches.
    """
    build_dir = build_dir or paths.game_root()
    seen = {}
    images = {}
    for ev in decode(trace_path, build_dir):
        if not ev.idx_off or (ev.rel, ev.rec) in seen:
            continue
        if ev.rel not in images:
            p = os.path.join(build_dir, *ev.rel.split("/"))
            images[ev.rel] = _Image(ev.rel, open(p, "rb").read()) if os.path.exists(p) else None
        img = images[ev.rel]
        r = img.by_id.get(ev.rec) if img else None
        seen[(ev.rel, ev.rec)] = (ev.rel, ev.rec, ev.idx_off, ev.idx_len,
                                  img.base.get(ev.rec) if img else None,
                                  len(r.data) if r else None)
    return list(seen.values())
