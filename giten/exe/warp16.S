# Dev-only warp cave: goto-record with a 16-bit file id and an entry offset.
#
# WHY IT IS NEEDED
#
# `0C <file> <record>` reads two u8 through 0x00433C10, so a script can only
# name `m/MS00xx`.  `m/MS6200` and `m/MS6500` -- which between them hold five of
# the corpus's untiled records -- have a 16-bit id no opcode can express, and
# `et/ET0007`'s merge can only form `0x6000 + t` and `0x6100 + t`.  So there is
# no way, from data alone, to make the engine execute those records.
#
# WHAT IT DOES NOT DO
#
# It does not reimplement the loader.  `0x00433D70` -- the function the `0C`
# handler already calls -- takes the file id in a **u16** register from its
# first stack argument (`cmp di,0xde` at 0x00433D82 compares the whole word),
# resolves it through `0x00433CA0` -> `0x0043B720`, and on a miss loads it via
# `0x0043B650` -> `0x0043AD20` -> `0x00401DD0(id, kind 9, 0)`, i.e. the generic
# `m\ms%.4x.bin` path.  `0x0043AA90` reads exactly **one** container per call
# (one header word, one count word, count records, return), so a plain 16-bit
# load gives container 0 and nothing else -- which is the container the residue
# lives in.  The cave therefore only has to *substitute the arguments*.
#
# HOW IT IS REACHED
#
# The dev build redirects the single `call 0x00433D70` at 0x00433E97 -- the
# mode-0 (goto) arm of the `0C`/`0D` trampoline `0x00433E70` -- to `warp16`.
# A script that executes `0C <SENTINEL> nn` gets the pinned target instead;
# every other `0C` is passed through unchanged, with the same arguments, to the
# same function.  SENTINEL is a file byte that occurs nowhere in the corpus as a
# `0C`/`0D` operand, so nothing real can be shadowed, and it is below 0xE0 so
# that a cave that failed to fire would take the ordinary `m/MS00xx` path rather
# than the demon-merge path at 0x00433CA8.
#
# THE ENTRY OFFSET
#
# `0x00433D70` always starts the record at its own first byte.  Five records of
# `m/MS0080` share a nine-byte head (`1f 00 02 1f 00 01 1f ff 00`) that no
# record reference in the corpus points at, so "entered at 0" may not be the
# entry the engine was built for.  With WARP_ENTRY non-zero the cave adds it to
# the program counter `0x00433D70` just set, through `0x00433C40` -- the
# engine's own `set_pc`, `mov [ctx+0x0E], ax`.
#
# ENGINE STATE, AND THE GUARD RULE (giten/exe/engine_state.py)
#
# The only engine address this reads is CTX (0x00491160), a POINTER: the game
# nulls it deliberately (`0x0042EA18` is `mov dword ptr [0x491160],0 ; ret`), so
# it is null-checked before the dereference.  Everything else here is a call to
# an engine function, not a load.  The target words are assembled in from
# --defsym, not read from game memory, so there is no INDEX anywhere in the
# cave.

        .intel_syntax noprefix
        .section .text
        .globl  warp16

# --- the cave ---------------------------------------------------------------
warp16:
        mov     eax, dword ptr [esp+4]      # arg1: file id, as 0x00433E97 pushes it
        cmp     ax, WARP_SENTINEL
        jne     passthrough
        mov     eax, WARP_FILE
        cmp     ax, 0xFFFF                  # 0xFFFF = "no target pinned"
        je      passthrough

        push    WARP_REC
        push    eax
        mov     eax, GOTO_RECORD            # absolute: the cave is appended at
        call    eax                         # an address `as` does not know
        add     esp, 8                      # 0x00433D70(file, record)

        mov     eax, WARP_ENTRY
        test    ax, ax
        je      done
        mov     ecx, dword ptr [CTX]        # POINTER: null is a designed value
        test    ecx, ecx
        je      done
        movzx   edx, word ptr [ecx+0x0E]    # the pc 0x00433D70 just set
        add     dx, ax
        movzx   edx, dx
        push    edx
        mov     eax, SET_PC
        call    eax                         # 0x00433C40(pc)
        add     esp, 4
done:
        ret

# Not our jump: hand the original arguments to the original function.  Written
# as a real call rather than a jmp so the cave never depends on the caller's
# stack layout being what a tail call would need.
passthrough:
        mov     eax, dword ptr [esp+8]      # record
        mov     ecx, dword ptr [esp+4]      # file
        push    eax
        push    ecx
        mov     eax, GOTO_RECORD
        call    eax
        add     esp, 8
        ret
