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
popups linger and others blink.  Callers that ask for a specific count are
unaffected, because the ``jge`` skips this instruction entirely.

This repo raised that default to 60 for most of its life, so English had a full
second to be read.  **It is back to 15 as of 2026-09-08**, because the dwell is
also how long the battle command UI is refused -- see :data:`POPUP_TICKS`.
"""
from __future__ import annotations

import struct

from .pe import PE

#: ``mov eax, 15`` -- the fallback popup duration, in ticks
POPUP_DEFAULT_SITE = 0x0040263A
POPUP_DEFAULT_OLD = bytes.fromhex("b80f000000")          # mov eax, 0x0F

#: What the release ships.  **This was 60 and is now back to the stock 15**,
#: decided 2026-09-08 by the person playing it, together with restoring the turn
#: gauge below.  The two are one decision: the dwell is also the length of time
#: the battle command UI is refused (``docs/combat-pacing.md`` §2), so 60 gave
#: back with one hand what the gauge fix gave with the other.  Battle messages
#: are short and the pacing matters more than the extra 750 ms of reading time.
#:
#: At 15 this is a **verified no-op** -- :func:`apply` still asserts the
#: instruction is the one we reverse-engineered, then writes the value already
#: there.  Pass a different number to change it; nothing else moves.
POPUP_TICKS = 15

#: the tick rate hook.c paces the main loop at, for the arithmetic above
TICKS_PER_SECOND = 60


# --- the turn gauge ---------------------------------------------------------
#
# Every combatant carries a u16 wait counter -- party at ``unit+0x17F``, enemy
# at ``enemy+0x199`` -- reloaded to 255 when its owner acts and decremented once
# per tick by ``0x0043F510``.  That is the game's turn order: there is no
# initiative sort (``docs/combat-pacing.md``).
#
# The 1997 PC-9801 release has the same routine, at file offset ``0x0321AA`` of
# ``DDS98.EXE``, and it differs by **one instruction**::
#
#     PC-98    add ax, 5              ; step =    1 + rand()%speed  + 5
#     Windows  lea ecx,[eax+eax*1+5]  ; step = 2*(1 + rand()%speed) + 5
#
# Everything else is verified identical -- the reload, both struct layouts, the
# master gate, and the arguments reaching the random helper.  So the port's
# whole edit to the turn gauge is a factor of two, and undoing it restores the
# original's arithmetic exactly (``docs/pc98-comparison.md`` §3).
#
# **This ships in the release** as of 2026-09-08.  It was dev-only first, on the
# reasoning that combat speed is a gameplay decision rather than a translation
# one -- and it still is a gameplay decision, which is why it was put to the
# person playing rather than decided here.  Their verdict, having played both
# releases: *"it's technically faithful and actually makes battles, battles (the
# speed it ran at before was impossible to fight at)."*  Measured 80 party
# actions to 11 enemy, against 1 : 1.22, 1 : 11.88 and 1 : 18.50 in the three
# archived pre-patch sessions (``docs/combat-pacing.md`` §4b).
#
# ``build_image(atb_pc98=False)`` builds without it; ``dds_dev_x2.exe`` is that
# build, kept so the comparison stays reproducible.

#: ``lea ecx,[eax+eax*1+5]`` -- the doubled step the Windows port introduced
ATB_STEP_SITE = 0x0043F52F
ATB_STEP_DOUBLED = bytes.fromhex("8d4c0005")
#: ``lea ecx,[eax+5] ; nop`` -- the PC-98 arithmetic, same four bytes
ATB_STEP_PC98 = bytes.fromhex("8d480590")


def atb_pc98(image: bytes) -> bytes:
    """Restore the PC-98 turn-gauge step: halve it, in place, four bytes.

    ``eax`` is dead immediately after (``mov ax,[esi+1]`` overwrites it and only
    ``cx`` is compared), so dropping the second addend is a safe drop-in and the
    trailing ``nop`` keeps every following address where it was.
    """
    pe = PE(image, "timing")
    off = pe.va2off(ATB_STEP_SITE)
    found = image[off:off + 4]
    if found != ATB_STEP_DOUBLED:
        raise RuntimeError("timing: the turn-gauge step at 0x%08X is not the "
                           "port's (%s)" % (ATB_STEP_SITE, found.hex(" ")))
    out = bytearray(image)
    out[off:off + 4] = ATB_STEP_PC98
    return bytes(out)


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
