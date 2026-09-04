"""Opcode-aware tokenizer for the script stream, driven by ``docs/opcodes.json``.

This is the pipeline's copy of the tiling proof in ``tools/exe_analysis/vm.py``:
the same model, the same tables, but producing a *structured* token list the
builder can edit and re-serialise rather than a coverage statistic.

The model (``docs/format-notes.md`` §2.1 / §2.2 / §2.8, all VERIFIED)

* a byte ``>= 0x20`` is literal text -- two bytes when the first is a Shift-JIS
  lead byte.  **Text is bare**: there is no message opcode and no length field
  anywhere, so a text run may be lengthened or shortened freely;
* ``0x00`` ends a record fragment (it dispatches, and it is opcode index 0);
* ``0x1D`` / ``0x1E`` / ``0x1F`` are escape prefixes selecting dispatch index
  ``0x300`` / ``0x200`` / ``0x100`` plus the next byte;
* anything else is opcode index == the byte;
* an opcode's operands are an ordered list of typed slots -- ``u8``, ``u16``,
  ``u32``, ``rel16``, a recursive ``expr`` tree, a ``0xFF``-terminated
  ``list_ff``, or the one data-dependent ``rule:wait_1E10``.

Nothing here guesses.  When the table says an opcode's operands run past the end
of the record, tokenizing *fails* and the caller must treat the record as
non-editable (``@untiled``) rather than resynchronise -- resynchronising one byte
late is exactly what produced the old pipeline's ``{DICT:92}`` phantoms and its
``{0B}ｼ`` / ``{02}じゃd`` operand leakage.
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
OPCODES_JSON = os.path.normpath(os.path.join(_HERE, "..", "..", "docs", "opcodes.json"))

FIXED_SIZE = {"u8": 1, "u16": 2, "u32": 4, "rel16": 2}

#: Dispatch-index bases for the three escape prefixes.
ESCAPE = {0x1D: 0x300, 0x1E: 0x200, 0x1F: 0x100}

MAX_EXPR_DEPTH = 24


class TileError(ValueError):
    """The opcode table could not tile this record."""


# --- table ------------------------------------------------------------------
class Table:
    """The opcode + expression tables, loaded once from ``docs/opcodes.json``."""

    def __init__(self, doc: dict):
        self.doc = doc
        self.ops = {}
        for key, v in doc["opcodes"].items():
            self.ops[int(key, 16)] = v
        self.nodes = {int(k, 16): v for k, v in doc["expressions"]["nodes"].items()}
        self.implemented = {i for i, v in self.ops.items() if v["implemented"]}

    def operands(self, idx: int):
        v = self.ops.get(idx)
        return v["operands"] if v else []

    def encoding(self, idx: int) -> str:
        v = self.ops.get(idx)
        if v:
            return v["encoding"].replace(" ", "")
        return "%02X" % idx if idx < 0x100 else "%03X" % idx

    def is_implemented(self, idx: int) -> bool:
        return idx in self.implemented


_TABLE = None


def table() -> Table:
    global _TABLE
    if _TABLE is None:
        with open(OPCODES_JSON, "r", encoding="utf-8") as fh:
            _TABLE = Table(json.load(fh))
    return _TABLE


# --- byte classes -----------------------------------------------------------
def is_sjis_lead(b: int) -> bool:
    """Shift-JIS lead byte, per the CRT ``_mbctype`` table the engine consults.

    ``0x81..0x9F`` and ``0xE0..0xFC``.  The upper end runs to 0xFC, not 0xEF:
    ``tools/exe_analysis/vm.py`` uses that range and it is what tiles the corpus.
    """
    return 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xFC


# --- tokens -----------------------------------------------------------------
class Operand:
    """One decoded operand slot of one opcode."""

    __slots__ = ("kind", "off", "size", "raw")

    def __init__(self, kind: str, off: int, size: int, raw: bytes):
        self.kind = kind
        self.off = off          # offset of the slot within the record data
        self.size = size
        self.raw = raw

    @property
    def value(self) -> int:
        return int.from_bytes(self.raw, "little")

    def __repr__(self):
        return "Operand(%s@%d=%s)" % (self.kind, self.off, self.raw.hex())


class Token:
    """One tiled unit: a text character or a complete opcode with its operands."""

    __slots__ = ("kind", "off", "size", "idx", "ops")

    def __init__(self, kind, off, size, idx=None, ops=()):
        self.kind = kind        # "text" | "op"
        self.off = off          # offset within the record data
        self.size = size
        self.idx = idx          # dispatch index for "op"
        self.ops = ops          # tuple[Operand]

    @property
    def end(self) -> int:
        return self.off + self.size

    def raw(self, data: bytes) -> bytes:
        return data[self.off:self.end]

    def __repr__(self):
        if self.kind == "text":
            return "Text(@%d,%d)" % (self.off, self.size)
        return "Op(0x%03X@%d,%d)" % (self.idx, self.off, self.size)


# --- the walk ---------------------------------------------------------------
def _read_expr(data: bytes, i: int, depth: int, tab: Table) -> int:
    if depth > MAX_EXPR_DEPTH:
        raise TileError("expression nested deeper than %d at 0x%X"
                        % (MAX_EXPR_DEPTH, i))
    if i >= len(data):
        raise TileError("expression selector past end of record at 0x%X" % i)
    sel = data[i]
    i += 1
    for payload in tab.nodes.get(sel, ()):
        if payload == "expr":
            i = _read_expr(data, i, depth + 1, tab)
        elif payload == "expr2":
            continue                       # an evaluated value, consumes no bytes
        else:
            i += FIXED_SIZE[payload]
            if i > len(data):
                raise TileError("expression node 0x%02X payload past end" % sel)
    return i


def _wait_1e10(data: bytes, i: int) -> int:
    """``1E 10``: ``a = u8; b = u8; if b in (0, 2) a third u8 follows``."""
    if i + 2 > len(data):
        raise TileError("1E 10 operands past end of record at 0x%X" % i)
    n = 3 if data[i + 1] in (0, 2) else 2
    if i + n > len(data):
        raise TileError("1E 10 third operand past end of record at 0x%X" % i)
    return i + n


def _read_operands(data: bytes, i: int, slots, tab: Table) -> "tuple[int, list]":
    out = []
    for slot in slots:
        kind = slot["kind"]
        start = i
        if kind == "expr":
            i = _read_expr(data, i, 0, tab)
        elif kind == "list_ff":
            j = i
            while j < len(data) and data[j] != 0xFF:
                j += 1
            if j >= len(data):
                raise TileError("unterminated list_ff at 0x%X" % i)
            i = j + 1
        elif kind == "rule:wait_1E10":
            i = _wait_1e10(data, i)
        else:
            i += FIXED_SIZE[kind]
            if i > len(data):
                raise TileError("%s operand past end of record at 0x%X" % (kind, start))
        out.append(Operand(kind, start, i - start, data[start:i]))
    return i, out


def tokenize(data: bytes, tab: "Table | None" = None,
             allow_unimplemented: bool = True) -> "list[Token]":
    """Tile one record's bytes.  Raises :class:`TileError` if the table cannot.

    ``allow_unimplemented=False`` also refuses a record that dispatches to one of
    the 267 no-op table slots.  Those consume prefix+byte and do nothing, so they
    tile fine; they are only suspicious because reaching one usually means the
    walk is a byte out.  The extractor keeps them (130 records corpus-wide) but
    flags the record.
    """
    tab = tab or table()
    out: "list[Token]" = []
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b >= 0x20:
            size = 2 if (is_sjis_lead(b) and i + 1 < n) else 1
            out.append(Token("text", i, size))
            i += size
            continue
        if b in ESCAPE:
            if i + 1 >= n:
                raise TileError("escape prefix %02X at end of record (0x%X)" % (b, i))
            idx = ESCAPE[b] + data[i + 1]
            head = 2
        else:
            idx = b
            head = 1
        if not allow_unimplemented and not tab.is_implemented(idx):
            raise TileError("opcode index 0x%03X at 0x%X is an engine no-op" % (idx, i))
        j, ops = _read_operands(data, i + head, tab.operands(idx), tab)
        out.append(Token("op", i, j - i, idx, tuple(ops)))
        i = j
    return out


def tiles(data: bytes, tab: "Table | None" = None) -> bool:
    try:
        tokenize(data, tab)
    except TileError:
        return False
    return True


def uses_unimplemented(toks: "list[Token]", tab: "Table | None" = None) -> bool:
    tab = tab or table()
    return any(t.kind == "op" and not tab.is_implemented(t.idx) for t in toks)


# --- rel16 helpers ----------------------------------------------------------
def rel16_target(base: int, tok: Token, op: Operand) -> int:
    """Absolute runtime-buffer offset a ``rel16`` operand points at.

    ``docs/format-notes.md`` §2.3: the displacement is measured from the byte
    *immediately after the operand*, in the runtime buffer's coordinates, and
    wraps mod 2**16 (so a backward branch reads as a large u16)::

        target = (pc_after_operand + imm16) & 0xFFFF

    ``base`` is the record's runtime offset -- ``records.bases()[id]``.
    """
    pc_after = base + op.off + op.size
    return (pc_after + op.value) & 0xFFFF


def rel16_imm(base: int, op_off: int, op_size: int, target: int) -> int:
    """Inverse of :func:`rel16_target`: the displacement that reaches ``target``."""
    return (target - (base + op_off + op_size)) & 0xFFFF
