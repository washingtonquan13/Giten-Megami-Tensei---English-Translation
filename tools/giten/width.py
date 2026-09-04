"""The real line-width budgets, in the engine's own units.

``docs/format-notes.md`` §3, VERIFIED:

* the character emitter (0x445410) advances **1 column for a half-width byte and
  2 for a two-byte Shift-JIS character**, and one column is **8 pixels**;
* ``0x453C50`` auto-wraps before drawing: it breaks the line when
  ``cur_col + width > max_cols + slack``, with ``slack = -2`` for ordinary
  characters (kinsoku shori gives ``0`` to the closing bracket set and ``-4`` to
  the opening set).  **The effective budget for ordinary text is therefore
  ``max_cols - 2``**;
* when a wrap would pass the last row the interpreter stops and waits for the
  reader, so ``max_rows`` is a real lines-per-page limit;
* narration and dialogue are drawn into the bottom message box, window type 1/12
  in the geometry table at 0x46D030: **76 columns x 4 rows**, i.e. 74 usable
  columns and 4 lines per page.  Type 0 is the tall variant, 76 x 6;
* menus are ``1F B1 <expr>`` … ``1F B2`` … ``1F B7`` and the ``1F B1`` operand is
  the **per-option width in columns**; 1690 of the 1752 shipped menus declare 20.

Because the engine wraps rather than clips, an over-wide line is a *cosmetic*
failure -- it breaks where the engine chooses instead of where the writer meant
-- so every finding here is a warning.  About 500 lines of the shipped English
already exceed 76 columns, which is exactly why this must not be an error.
"""
from __future__ import annotations

import re

from . import codec

#: Bottom message box, window type 1/12: 76 columns, 2 of them eaten by the
#: kinsoku slack.
LINE_COLUMNS = 74

#: ...and 4 rows before the engine stops for a page turn.  Type 0 gives 6.
PAGE_ROWS = 4
TALL_PAGE_ROWS = 6

#: Fallback when a menu's ``1F B1`` operand is not a plain literal.
CHOICE_COLUMNS = 20

_POOL_RE = re.compile(r"\{(0[1-8]):([0-9A-Fa-f]{2})\}")


def text_width(text: str, pools=None) -> int:
    """Columns one rendered line will occupy, pool calls included.

    A pool call draws the text of the record it calls, so ``{08:1F}`` is not
    zero-width: it is as wide as the fragment it splices in.  Passing
    ``pools=None`` charges pool calls nothing, which is the right answer for an
    English line (a translator writes the word out instead of calling the macro).
    """
    w = codec.display_width(text)
    if pools is not None:
        from . import pool
        for m in _POOL_RE.finditer(text):
            w += pool.call_width(int(m.group(1), 16), int(m.group(2), 16), pools)
    return w


def pages(text: str) -> "list[list[str]]":
    """Split a rendered span into pages (on ``<wait>``) of lines (on ``\\n``).

    Walks the escape grammar rather than using a regex so that ``\\\\n`` -- an
    escaped backslash followed by the letter n -- is not read as a line break.
    """
    out = [[[]]]
    i = 0
    n = len(text)
    while i < n:
        if text.startswith(codec.WAIT_TOKEN, i):
            out.append([[]])
            i += len(codec.WAIT_TOKEN)
            continue
        if text[i] == "\\" and i + 1 < n:
            if text[i + 1] == "n":
                out[-1].append([])
            else:
                out[-1][-1].append(text[i:i + 2])
            i += 2
            continue
        out[-1][-1].append(text[i])
        i += 1
    return [["".join(line) for line in page] for page in out]


def lines(text: str) -> "list[str]":
    """Every display line, page breaks flattened away."""
    return [ln for page in pages(text) for ln in page]


def findings(text: str, is_choice: bool = False, choice_width: int = CHOICE_COLUMNS,
             line_columns: int = LINE_COLUMNS, page_rows: int = PAGE_ROWS,
             pools=None) -> "list[tuple[str, str]]":
    """``[(rule, message)]`` for one rendered span.  Empty means it fits."""
    out = []
    if is_choice:
        for ln in lines(text):
            w = text_width(ln, pools)
            if w > choice_width:
                out.append(("width-choice",
                            "menu option is %d columns, the menu declares %d: %r"
                            % (w, choice_width, ln[:60])))
        return out
    for p, page in enumerate(pages(text)):
        body = [ln for ln in page]
        while body and not body[-1].strip():
            body.pop()
        if len(body) > page_rows:
            out.append(("page-rows",
                        "page %d has %d lines, the message box shows %d before a "
                        "<wait>" % (p + 1, len(body), page_rows)))
        for i, ln in enumerate(body):
            w = text_width(ln, pools)
            if w > line_columns:
                out.append(("width",
                            "page %d line %d is %d columns, the box is %d wide "
                            "(the engine will wrap it): %r"
                            % (p + 1, i + 1, w, line_columns, ln[:60])))
    return out
