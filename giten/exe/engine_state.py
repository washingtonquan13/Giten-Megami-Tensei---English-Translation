"""Every engine address our injected code touches, and the guard it requires.

Our code runs *inside* the game, on paths the game takes millions of times, and
reads engine state through hard-coded absolute addresses.  The failure mode is
never a wrong answer -- it is an access violation that kills the process, in a
state the engine considers perfectly normal.

That is not hypothetical.  ``ds:0x00491160`` (the script context) is nulled by a
function whose entire body is ``mov dword ptr [0x491160], 0 ; ret`` at
``0x0042EA18``, and swapped by ``0x00438D65``.  Null is a *designed* value.  The
game's own byte fetch guards for it; ``trace.S`` guarded it in one of its two
reads and not the other, and the one it missed killed the game at a scene
transition (the Earth Dragon door in the battle simulator).

So each address gets a kind, and each kind gets a rule:

``VALUE``
    A fixed location in ``.data``.  Always mapped, so reading it cannot fault.
    No guard needed.
``POINTER``
    Holds an address the engine may set to null.  **Must be null-checked before
    being dereferenced.**
``INDEX``
    Used to compute an address (``table + i * stride``).  **Must be range-checked
    before the indexed load**, because the load itself faults -- there is nothing
    to null-check afterwards.

:func:`unguarded` is the machine-checkable form of the rule; the tests use it.
"""
from __future__ import annotations

VALUE, POINTER, INDEX = "VALUE", "POINTER", "INDEX"

#: address -> (kind, what it is, who reads it)
ENGINE_STATE = {
    0x00491160: (POINTER, "script context; PC is a u16 at +0x0E",
                 "trace.S"),
    0x004911B0: (VALUE, "current script file id (u16)", "hook.c, trace.S"),
    0x004911B2: (VALUE, "current record id (u16)", "trace.S"),
    0x00481224: (VALUE, "text-capture flag (u16)", "trace.S"),
    0x00481120: (VALUE, "256-byte capture buffer", "trace.S"),
    0x0047605C: (INDEX, "handle table; [base + handle*8] = script buffer",
                 "hook.c, trace.S"),
    0x004716E0: (INDEX, "id of the map file the router last opened (u16)",
                 "mapnames.S"),
    0x004800E8: (POINTER, "item-database image", "database.S"),
}

#: the bound each INDEX must be checked against before use
INDEX_BOUND = {
    0x0047605C: 0x1000,      # keeps base + h*8 inside .data (ends 0x492B54)
    0x004716E0: 0x100,       # map ids are 0x00..0xFF (mapnames.MAPSLOTS)
}

#: functions in the *original* exe that write a null into a POINTER, i.e. the
#: proof that null is a state the engine chooses, not corruption
KNOWN_NULLERS = {
    0x00491160: (0x0042EA18, "mov dword ptr [0x491160], 0 ; ret"),
}


def pointers() -> "list[int]":
    return [a for a, (k, _d, _w) in ENGINE_STATE.items() if k == POINTER]


def indexes() -> "list[int]":
    return [a for a, (k, _d, _w) in ENGINE_STATE.items() if k == INDEX]


def unguarded(code: bytes, addr: int, window: int = 12) -> "list[int]":
    """Offsets in ``code`` that load ``addr`` without a guard close behind.

    Recognises the two guards our code actually emits: ``test ecx,ecx`` /
    ``test eax,eax`` for a POINTER, and ``cmp`` for an INDEX.  A load with no
    guard inside ``window`` bytes is reported.
    """
    import struct

    kind = ENGINE_STATE[addr][0]
    if kind == VALUE:
        return []
    guards = [bytes.fromhex("85c9"), bytes.fromhex("85c0")]      # test reg,reg
    if kind == INDEX:
        guards += [b"\x3d", b"\x81\xf9", b"\x83\xf9", b"\x81\xf8", b"\x83\xf8"]
    packed = struct.pack("<I", addr)

    out, i = [], code.find(packed)
    while i >= 0:
        tail = code[i + 4:i + 4 + window]
        if not any(g in tail for g in guards):
            out.append(i)
        i = code.find(packed, i + 1)
    return out
