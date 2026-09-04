"""The v2 text codec: tokenized script bytes <-> the editable ``jp``/``en`` string.

The v1 codec (:mod:`.tokens`) scanned bytes and rendered anything it could not
classify as ``{XX}``.  That is what leaked operand bytes into the text -- ``{0B}ｼ``
was really ``0B tt tt cc cc`` with its condition byte read as a kana, and
``{DICT:92}`` was a resync landing one byte late.  This codec never sees a raw
byte stream: it renders a *token list* produced by :mod:`.vmops`, so an operand
byte can no more become text than a text byte can become an opcode.

Token language
--------------
==========================  ====================================================
rendered                    bytes
==========================  ====================================================
``\\n``                      ``0A`` (newline opcode)
``<wait>``                  ``1E 10 01 01`` (the canonical page wait)
``{01:03}`` ... ``{08:1F}``  a pool call: opcode ``01``..``08`` + its u8 record
``{1E10:010005}``           any other ``1E 10`` form, operands folded in
``{=E9}``                   one literal byte that is not valid cp932 on its own
``\\\\``  ``\\{``  ``\\<``       literal backslash / brace / angle bracket
==========================  ====================================================

**Operands are folded into their opcode's token.**  ``{01:03}`` is one token
meaning "opcode 01, operand byte 03" -- never ``{01}`` followed by ``{03}``, and
never ``{01}`` followed by a stray ``0x03`` masquerading as text.  A token's
payload is exactly the operand bytes the engine will consume.

Only *inline* opcodes may appear inside a span (:data:`INLINE_OPS`): the eight
pool calls, the newline, and the page wait.  Those are the only opcodes that take
part in rendering a line of text; every other opcode ends the span and is
re-emitted from the source bytes, so a translator can neither see nor damage a
branch displacement, a window type or a variable index.
"""
from __future__ import annotations

import re

from . import vmops

NEWLINE_OP = 0x00A
WAIT_OP = 0x210
POOL_OPS = frozenset(range(0x001, 0x009))
WAIT_BYTES = b"\x1e\x10\x01\x01"
WAIT_TOKEN = "<wait>"

#: Opcodes that may live inside a translatable span.
INLINE_OPS = frozenset({NEWLINE_OP, WAIT_OP}) | POOL_OPS

#: Opcodes that render text of their own (their width has to be looked up).
TEXT_PRODUCING_OPS = POOL_OPS

_ESCAPES = {"\\": "\\\\", "{": "\\{", "<": "\\<"}
_UNESCAPES = {"\\": "\\", "{": "{", "<": "<"}

_TOKEN_RE = re.compile(r"\{([0-9A-Fa-f]{2}|1[DEF][0-9A-Fa-f]{2})"
                       r"(?::([0-9A-Fa-f]*))?\}")
#: A raw text byte.  Spelled ``{=HH}`` rather than ``{HH}`` so that it can never
#: collide with an opcode token: the engine reads a Shift-JIS lead byte and then
#: takes the next byte unconditionally, so a run like ``E9 00`` is two *text*
#: bytes that happen not to decode -- and its second byte, 0x00, would otherwise
#: render as the record-terminator opcode and re-encode into a broken record.
_RAWBYTE_RE = re.compile(r"\{=([0-9A-Fa-f]{2})\}")


class CodecError(ValueError):
    pass


def _escape(s: str) -> str:
    return "".join(_ESCAPES.get(c, c) for c in s)


# --- bytes -> text ----------------------------------------------------------
def op_token(idx: int, operands: bytes) -> str:
    """Render one opcode + its operand bytes as a single ``{...}`` token."""
    if idx == WAIT_OP and operands == b"\x01\x01":
        return WAIT_TOKEN
    enc = vmops.table().encoding(idx)
    return "{%s:%s}" % (enc, operands.hex().upper()) if operands else "{%s}" % enc


def render(data: bytes, toks, expand=None) -> str:
    """Render a token slice as an editable string.

    ``toks`` is a slice of the list :func:`vmops.tokenize` returned for ``data``.
    ``expand`` is unused by the codec itself; :mod:`.pool` uses the same token
    list to build the human-readable gloss that goes in the ``note`` column.
    """
    out = []
    for t in toks:
        if t.kind == "text":
            raw = data[t.off:t.end]
            try:
                out.append(_escape(raw.decode("cp932")))
            except UnicodeDecodeError:
                out.extend("{=%02X}" % b for b in raw)
            continue
        if t.idx == NEWLINE_OP:
            out.append("\\n")
            continue
        out.append(op_token(t.idx, data[t.off + _head_len(t.idx):t.end]))
    return "".join(out)


def _head_len(idx: int) -> int:
    return 1 if idx < 0x100 else 2


# --- text -> bytes ----------------------------------------------------------
def _op_bytes(enc: str) -> bytes:
    return bytes.fromhex(enc)


def encode(text: str, allow: "frozenset[int] | None" = None) -> bytes:
    """Encode an edited span string back to script bytes.

    ``allow`` restricts which opcode indices may appear; it defaults to
    :data:`INLINE_OPS`.  Pass an empty set to forbid every control token.
    """
    allow = INLINE_OPS if allow is None else allow
    out = bytearray()
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in ("\t", "\r", "\n"):
            raise CodecError("raw %r in the text; write \\n for a line break"
                             % c)
        if c == "\\":
            if i + 1 >= n:
                raise CodecError("trailing backslash")
            e = text[i + 1]
            if e == "n":
                if NEWLINE_OP not in allow:
                    raise CodecError("a line break is not allowed here")
                out.append(0x0A)
            elif e in _UNESCAPES:
                out += _UNESCAPES[e].encode("cp932")
            else:
                raise CodecError("unknown escape \\%s" % e)
            i += 2
            continue
        if text.startswith(WAIT_TOKEN, i):
            if WAIT_OP not in allow:
                raise CodecError("<wait> is not allowed here")
            out += WAIT_BYTES
            i += len(WAIT_TOKEN)
            continue
        if c == "{":
            m = _RAWBYTE_RE.match(text, i)
            if m:
                out.append(int(m.group(1), 16))
                i = m.end()
                continue
            m = _TOKEN_RE.match(text, i)
            if not m:
                raise CodecError("malformed token at offset %d "
                                 "(write '\\{' for a literal brace)" % i)
            enc, payload = m.group(1).upper(), (m.group(2) or "")
            if len(payload) % 2:
                raise CodecError("token {%s:%s} has an odd number of hex digits"
                                 % (enc, payload))
            head = _op_bytes(enc)
            if len(head) == 1 and head[0] >= 0x20:
                raise CodecError("{%s} is not an opcode; write {=%s} for the "
                                 "literal byte" % (enc, enc))
            idx = (vmops.ESCAPE[head[0]] + head[1]) if len(head) == 2 else head[0]
            if idx not in allow:
                raise CodecError("opcode {%s} may not appear inside a span "
                                 "(only %s may)" % (enc, _allowed_names(allow)))
            body = bytes.fromhex(payload)
            _check_operands(idx, body, enc)
            out += head + body
            i = m.end()
            continue
        if c == "<":
            raise CodecError("stray '<' at offset %d (write '\\<' for a literal)" % i)
        try:
            out += c.encode("cp932")
        except UnicodeEncodeError:
            raise CodecError("character %r (U+%04X) is not encodable in cp932 "
                             "(the game's code page)" % (c, ord(c)))
        i += 1
    return bytes(out)


def _allowed_names(allow) -> str:
    return ", ".join(sorted(vmops.table().encoding(i) for i in allow))


def _check_operands(idx: int, body: bytes, enc: str) -> None:
    """The payload must be exactly the operand bytes the engine will consume."""
    probe = _op_bytes(enc) + body
    try:
        toks = vmops.tokenize(probe)
    except vmops.TileError as exc:
        raise CodecError("{%s:%s}: %s" % (enc, body.hex().upper(), exc))
    if len(toks) != 1 or toks[0].size != len(probe):
        raise CodecError("{%s:%s}: %d operand bytes, the opcode consumes %d"
                         % (enc, body.hex().upper(), len(body),
                            toks[0].size - len(_op_bytes(enc))))


# --- helpers used by the validators and by stats ----------------------------
_STRIP_RE = re.compile(r"\\.|<wait>|\{[0-9A-Fa-f]{2,4}(?::[0-9A-Fa-f]*)?\}")
_JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff"
                    r"\uff00-\uff9f\u3000-\u303f]")


def strip_tokens(text: str) -> str:
    """Rendered text with every control token removed and escapes resolved."""
    def sub(m):
        s = m.group(0)
        if s.startswith("\\") and len(s) == 2:
            return _UNESCAPES.get(s[1], "")
        return ""
    return _STRIP_RE.sub(sub, text)


def has_japanese(text: str) -> bool:
    return bool(_JP_RE.search(strip_tokens(text)))


def control_tokens(text: str) -> "list[str]":
    """Every ``{...}`` / ``<wait>`` token, in order."""
    return [m.group(0) for m in _STRIP_RE.finditer(text)
            if not m.group(0).startswith("\\")]


def display_width(text: str) -> int:
    """Width of a rendered fragment in **columns** (one column = 8 px).

    ``docs/format-notes.md`` §3.1: the emitter advances 1 column for a byte
    below 0x100 and 2 for a two-byte Shift-JIS character.  Control tokens are 0;
    the caller adds the width of any pool call separately (see :mod:`.pool`).
    """
    w = 0
    for ch in strip_tokens(text):
        o = ord(ch)
        w += 1 if (o < 0x80 or 0xFF61 <= o <= 0xFF9F) else 2
    return w
