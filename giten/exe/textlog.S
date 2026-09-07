# TextOutA logger for dds.exe (dev builds only) -- the spike for a menu overlay.
#
# The game imports exactly one text-drawing API, GDI32!TextOutA, and calls it
# from exactly one instruction: VA 0x449A30, `call dword ptr [0x00464050]`.
# Every string the engine draws through GDI passes that one point, which makes
# it a narrower choke point than the script overlay's five byte-fetch sites.
#
# The question this build answers is whether an overlay hung there could
# replace the 117 pointer rewrites in names.py/menus.py (and possibly the
# mapnames.py parser hook): does every string we currently patch actually reach
# TextOutA, and in what form?  So this hook only *records*; it changes nothing.
#
# WHY THE CALL SITE AND NOT THE IAT SLOT
#
# Patching the import slot on disk does nothing: the Windows loader overwrites
# FirstThunk with the resolved address at load time, so our value never
# survives to be called.  The hook therefore replaces the six-byte
# `call dword ptr [IAT]` with `call <thunk>` + `nop`, and the thunk reaches the
# real function through the same IAT slot the loader filled in.  One site, six
# bytes, and the operand is a rel32 like every other redirect in this file's
# neighbours.
#
# TextOutA is __stdcall with five arguments, so the thunk tail-*jumps* to it:
# the real function pops the 20 bytes and returns straight to the game's
# caller, leaving the stack discipline exactly as it was.
#
#     ddswin\textout.bin:  "GTXT" u16 version=1 u16 0
#     then per call:       u16 n, i16 x, i16 y, then n bytes of the string
#
# `n` is capped at 512.  Two WriteFile calls per record rather than a staging
# buffer: TextOutA cannot re-enter itself, and the kernel holds the bytes, so a
# crash still leaves every completed record on disk.  Same reasoning as
# trace.S -- no flush, no CloseHandle.
#
# Position-independent: data is reached via call/pop, imports go through their
# IAT slots, and every absolute address arrives as a --defsym.

        .intel_syntax noprefix
        .section .text
        .globl  _start

# on entry:  [esp+4] hdc  [esp+8] x  [esp+12] y  [esp+16] lpString  [esp+20] c
_start:
        pushad
        pushfd

        call    1f
1:      pop     esi
        sub     esi, offset 1b              # esi = cave base (PIC)

        mov     eax, dword ptr [esi + hfile]
        test    eax, eax
        jnz     2f
        push    0                           # hTemplateFile
        push    0x80                        # FILE_ATTRIBUTE_NORMAL
        push    2                           # CREATE_ALWAYS
        push    0                           # lpSecurityAttributes
        push    1                           # FILE_SHARE_READ
        push    0x40000000                  # GENERIC_WRITE
        lea     eax, [esi + fname]
        push    eax
        call    dword ptr [CREATEFILE_IAT]
        mov     dword ptr [esi + hfile], eax
        push    0                           # lpOverlapped
        lea     eax, [esi + written]
        push    eax
        push    8
        lea     eax, [esi + hdr]            # "GTXT" 1 0
        push    eax
        push    dword ptr [esi + hfile]
        call    dword ptr [WRITEFILE_IAT]
2:
        # pushad pushed 32 bytes and pushfd 4, so the caller's frame is at +36
        mov     edi, dword ptr [esp + 36 + 16]      # lpString
        mov     ecx, dword ptr [esp + 36 + 20]      # c (byte count, may be < 0)
        test    edi, edi
        jz      9f                          # nothing to record
        test    ecx, ecx
        jg      3f
        # a non-positive count: measure the string instead, still bounded
        xor     ecx, ecx
4:      cmp     byte ptr [edi + ecx], 0
        je      3f
        inc     ecx
        cmp     ecx, 512
        jb      4b
3:      cmp     ecx, 512
        jbe     5f
        mov     ecx, 512
5:      test    ecx, ecx
        jz      9f

        mov     eax, dword ptr [esp + 36 + 8]       # x
        mov     word ptr [esi + hx], ax
        mov     eax, dword ptr [esp + 36 + 12]      # y
        mov     word ptr [esi + hy], ax
        mov     word ptr [esi + hn], cx
        mov     dword ptr [esi + savedn], ecx

        push    0                           # lpOverlapped
        lea     eax, [esi + written]
        push    eax
        push    6                           # u16 n, i16 x, i16 y
        lea     eax, [esi + hn]
        push    eax
        push    dword ptr [esi + hfile]
        call    dword ptr [WRITEFILE_IAT]

        push    0                           # lpOverlapped
        lea     eax, [esi + written]
        push    eax
        push    dword ptr [esi + savedn]
        push    edi                         # the string itself
        push    dword ptr [esi + hfile]
        call    dword ptr [WRITEFILE_IAT]
9:
        popfd
        popad
        jmp     dword ptr [TEXTOUT_IAT]     # tail call: it pops the 20 bytes

        .balign 4
hfile:  .long   0
written: .long  0
savedn: .long   0
hn:     .short  0                           # u16 n   -- these three are one
hx:     .short  0                           # i16 x      6-byte record header,
hy:     .short  0                           # i16 y      written in one call
hdr:    .ascii  "GTXT"
        .short  1                           # format version
        .short  0
fname:  .asciz  "textout.bin"
