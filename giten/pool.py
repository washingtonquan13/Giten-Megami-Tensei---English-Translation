"""The eight macro pools ``m/MS7F00.BIN`` .. ``m/MS7F07.BIN``.

``docs/format-notes.md`` §2.5, VERIFIED: opcodes ``01 nn`` .. ``08 nn`` share
handler 0x42FFC7, which computes ``file_id = opcode + 0x7EFF`` and *calls* record
``nn`` of that file.  So ``01`` is always ``m/MS7F00.BIN``, ``08`` always
``m/MS7F07.BIN`` (the 20 000-use "dictionary"), with no selector opcode anywhere.
A pool record may itself contain pool calls -- ``MS7F00`` record 1 is
``08 02 08 33 00`` -- so expansion is recursive.

Nothing in the v2 pipeline *rewrites* a pool call: ``{08:1F}`` round-trips as the
two bytes ``08 1F``.  This module exists only so the extractor can put a
human-readable gloss in the ``note`` column and so the width validator can charge
a pool call the columns it will actually draw.

An out-of-range record number is harmless rather than a crash: the loader
pre-fills all 256 index slots with a single ``0x00``, so an absent record expands
to the empty string (§2.7).
"""
from __future__ import annotations

from . import codec, paths, records, vmops

POOL_FILES = ["m/MS7F%02X.BIN" % i for i in range(8)]

MAX_DEPTH = 6

_CACHE = None


def _load(root=None) -> "dict[int, dict[int, bytes]]":
    """``{opcode index 1..8: {record id: record bytes}}``."""
    import os

    base = root or paths.game_root()
    out = {}
    for k, rel in enumerate(POOL_FILES, start=1):
        p = os.path.join(base, *rel.split("/"))
        table = {}
        if os.path.exists(p):
            with open(p, "rb") as fh:
                img = records.load(rel, fh.read())
            if img.ok:
                for _ci, r in img.iter_records():
                    table.setdefault(r.id, r.data)
        out[k] = table
    return out


def load(root=None) -> "dict[int, dict[int, bytes]]":
    global _CACHE
    if root is not None:
        return _load(root)
    if _CACHE is None:
        _CACHE = _load(None)
    return _CACHE


def expand(op_idx: int, record_no: int, pools=None, depth: int = 0) -> str:
    """The text a pool call draws, as a plain string (no tokens)."""
    pools = pools if pools is not None else load()
    if depth >= MAX_DEPTH:
        return ""
    data = pools.get(op_idx, {}).get(record_no)
    if not data:
        return ""
    try:
        toks = vmops.tokenize(data)
    except vmops.TileError:
        return ""
    out = []
    for t in toks:
        if t.kind == "text":
            try:
                out.append(data[t.off:t.end].decode("cp932"))
            except UnicodeDecodeError:
                pass
        elif t.idx in codec.POOL_OPS and t.ops:
            out.append(expand(t.idx, t.ops[0].value, pools, depth + 1))
        elif t.idx == codec.NEWLINE_OP:
            out.append("\n")
    return "".join(out)


_CALL_RE = None


def _call_re():
    global _CALL_RE
    if _CALL_RE is None:
        import re
        _CALL_RE = re.compile(r"\{(0[1-8]):([0-9A-Fa-f]{2})\}")
    return _CALL_RE


def has_calls(text: str) -> bool:
    return bool(_call_re().search(text))


def reading(text: str, pools=None) -> str:
    """The rendered span with every pool call replaced by the text it draws.

    ``信用出来{08:25}な{02:08}`` -> ``信用出来ないな``.  The ``jp`` column stays
    byte-faithful -- a translator has to be able to see that a macro was there,
    and the width validator has to charge it -- so this readable form goes in the
    ``note`` column instead.  It is exactly what the v1 tables showed as ``jp``.
    """
    pools = pools if pools is not None else load()

    def sub(m):
        return expand(int(m.group(1), 16), int(m.group(2), 16), pools)

    out = _call_re().sub(sub, text)
    return out.replace("\t", " ").replace("\n", " ")


def gloss(text: str, pools=None) -> str:
    """``"{01:03}さん"`` -> ``"{01:03}=ニュートン"`` -- per-call, for short spans."""
    pools = pools if pools is not None else load()
    seen = []
    for m in _call_re().finditer(text):
        s = expand(int(m.group(1), 16), int(m.group(2), 16), pools).replace("\n", " ")
        if s and m.group(0) not in [x[0] for x in seen]:
            seen.append((m.group(0), s))
    return ", ".join("%s=%s" % (a, b) for a, b in seen)


def call_width(op_idx: int, record_no: int, pools=None) -> int:
    """Columns a pool call draws (8 px each), for the width validator."""
    s = expand(op_idx, record_no, pools)
    w = 0
    for ch in s:
        if ch == "\n":
            continue
        o = ord(ch)
        w += 1 if (o < 0x80 or 0xFF61 <= o <= 0xFF9F) else 2
    return w
