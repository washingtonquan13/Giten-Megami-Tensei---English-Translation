"""Timing constants the engine counts in *game ticks*.

The main loop advances one tick whenever ``pace()`` says one is due
(``hook.c``), which the release exe pins at 60 Hz.  Anything the engine counts
in ticks therefore has a real duration of ``ticks / 60`` seconds -- and the
values baked into the 1999 binary were chosen for a loop that free-ran as fast
as the machine could draw.

**The popup auto-close timer.**  ``0x004716F4`` is a countdown decremented once
per tick, straight from the main loop::

    0x004510B8  main loop, just past the pacing gate
      -> 0x004019D0   per-tick update (also drives the battle clock)
         -> 0x00401980
            -> 0x00402740   cmp [0x4716F8],0 / jne ret   (input-wait popups freeze it)
                            dec [0x4716F4] / jg ret
                            jmp 0x00402720               -> destroys the dialog,
                                                            handle 0x468300 = -1

The duration is chosen when the popup opens, by the setter at ``0x00402630``::

    mov eax,[esp+4] ; cmp ax,1 ; jge +5
    mov eax, 15                      <- POPUP_DEFAULT_SITE, the value patched here
    mov [0x4716F4], ax

so a caller passing a positive count gets it, and a caller passing 0 falls back
to the default.  The game does both: ``0x00406211`` opens its popup with
``push 0x3C`` (60 ticks, a second at 60 Hz) while ``0x004027E0`` passes
``push 0`` and lands on the 15-tick default -- 250 ms, which is why some battle
popups linger and others blink.  Raising the default to 60 makes the second
kind behave like the first.  Callers that ask for a specific count are
unaffected, because the ``jge`` skips this instruction entirely.
"""
from __future__ import annotations

import struct

from .pe import PE

#: ``mov eax, 15`` -- the fallback popup duration, in ticks
POPUP_DEFAULT_SITE = 0x0040263A
POPUP_DEFAULT_OLD = bytes.fromhex("b80f000000")          # mov eax, 0x0F

#: What to raise it to.  60 ticks = 1.0 s at the 60 Hz the release exe paces at,
#: matching the popups the game already opens with an explicit ``push 0x3C``.
POPUP_TICKS = 60

#: the tick rate hook.c paces the main loop at, for the arithmetic above
TICKS_PER_SECOND = 60


def seconds(ticks: int) -> float:
    return ticks / float(TICKS_PER_SECOND)


def apply(image: bytes, popup_ticks: int = POPUP_TICKS) -> bytes:
    """Rewrite the tick-counted timing defaults in place.

    Same instruction, same length, only the immediate changes -- nothing moves,
    so no other address in the image is affected.
    """
    if not 1 <= popup_ticks <= 0x7FFF:
        raise RuntimeError("timing: %d ticks is outside the u16 the counter holds"
                           % popup_ticks)
    pe = PE(image, "timing")
    off = pe.va2off(POPUP_DEFAULT_SITE)
    if image[off:off + len(POPUP_DEFAULT_OLD)] != POPUP_DEFAULT_OLD:
        raise RuntimeError("timing: the popup-duration default at 0x%08X is not the "
                           "original's (%s)"
                           % (POPUP_DEFAULT_SITE,
                              image[off:off + len(POPUP_DEFAULT_OLD)].hex(" ")))
    out = bytearray(image)
    struct.pack_into("<I", out, off + 1, popup_ticks)
    return bytes(out)
