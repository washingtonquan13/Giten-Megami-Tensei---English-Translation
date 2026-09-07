# Text logger for dds.exe (dev builds only) -- the spike for a menu overlay.
#
# HOW THE ENGINE DRAWS TEXT
#
# It never calls TextOutA (a build that hooked it produced no log at all).  It
# imports GetGlyphOutlineA and blits every character itself:
#
#     0x451230   draw one glyph.  arg1 is the character code; 0x20..0xDF come
#                from a built-in half-width font at 0x0046C230 and the rest
#                from GetGlyphOutlineA, its only call site (0x4512B6).
#     six draw-string variants, each walking a char* to its NUL:
#                0x451650  0x451750  0x451850  0x451950  0x451B20  0x451CB0
#
# Those six are where a menu overlay would hang: each takes the string as an
# argument, so swapping the pointer would retire the 117 pointer rewrites in
# names.py and menus.py, and mapnames.py's parser hook with them.
#
# WHAT THIS BUILD IS FOR
#
# The six have *different* signatures -- the string is at a different argument
# index in each, behind a different mix of `sub esp` and pushes -- and a wrong
# index means dereferencing a garbage pointer.  Rather than hand-decode six
# stack frames and stake the hook on getting all six right, this logs each
# call's arguments and lets a play session say which one is the string: the
# glyph records that follow a draw-string record spell out the string it drew,
# so the argument that points at those bytes is the answer.
#
#     ddswin\textout.bin:  "GTXT" u16 version=3 u16 record_size=36
#     per record:           u16 kind, u16 pad, u32 arg1..arg8
#                          kind 0     = a glyph, args 1-5 as pushed
#                          kind 1..6  = draw-string variant 1..6, args 1-8
#
# Both hooks are call-site redirects -- six for the glyph, seventy-one for the
# string variants -- so nothing is displaced and no trampoline is needed.  The
# string stubs push a variant id and share one body, which reads the real
# target out of TARGETS rather than duplicating the logger six times.
#
# Position-independent: data is reached via call/pop, imports go through their
# IAT slots, every absolute address arrives as a --defsym.  One WriteFile per
# record, like trace.S: the kernel holds the bytes, so a crash still leaves
# everything drawn so far on disk.

        .intel_syntax noprefix
        .section .text
        .globl  _start

# ---------------------------------------------------------------- glyph ----
# entry: [esp] return address, [esp+4..] the args the caller pushed
_start:
        push    0                           # kind 0
        jmp     common

# ---------------------------------------------------- draw-string stubs ----
# Each pushes its variant id (1..6); `common` uses it both to tag the record
# and to find the real function in TARGETS.
str1:   push    1
        jmp     common
str2:   push    2
        jmp     common
str3:   push    3
        jmp     common
str4:   push    4
        jmp     common
str5:   push    5
        jmp     common
str6:   push    6
        jmp     common

# --------------------------------------------------------------- common ----
# on entry: [esp] = kind, [esp+4] = return address, [esp+8..] = the args
common:
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
        lea     eax, [esi + hdr]            # "GTXT" 3 36
        push    eax
        push    dword ptr [esi + hfile]
        call    dword ptr [WRITEFILE_IAT]
2:
        # pushad pushed 32 and pushfd 4; the kind is below them at [esp+36],
        # the return address at [esp+40], so the caller's arg1 is at [esp+44]
        lea     edi, [esi + rec]
        mov     eax, dword ptr [esp + 36]
        mov     word ptr [edi + 0], ax      # kind
        xor     eax, eax
        mov     word ptr [edi + 2], ax      # pad
        xor     ecx, ecx
3:      mov     eax, dword ptr [esp + ecx*4 + 44]
        mov     dword ptr [edi + ecx*4 + 4], eax
        inc     ecx
        cmp     ecx, 8
        jb      3b

        push    0                           # lpOverlapped
        lea     eax, [esi + written]
        push    eax
        push    36
        push    edi
        push    dword ptr [esi + hfile]
        call    dword ptr [WRITEFILE_IAT]

        # Tail call.  Overwrite the pushed kind with the real target and RET to
        # it: `ret` pops that word into EIP and leaves the stack exactly as the
        # original call site set it up -- return address on top, arguments above
        # -- so the real routine cannot tell it was diverted.  Nothing absolute
        # is needed, which keeps the cave position-independent.
        mov     eax, dword ptr [esp + 36]
        mov     eax, dword ptr [esi + eax*4 + targets]
        mov     dword ptr [esp + 36], eax
        popfd
        popad
        ret

        .balign 4
hfile:  .long   0
written: .long  0
targets:
        .long   DRAWGLYPH                   # kind 0
        .long   DRAWSTR1                    # kind 1..6
        .long   DRAWSTR2
        .long   DRAWSTR3
        .long   DRAWSTR4
        .long   DRAWSTR5
        .long   DRAWSTR6
rec:    .space  36
hdr:    .ascii  "GTXT"
        .short  3                           # format version
        .short  36                          # bytes per record
fname:  .asciz  "textout.bin"
