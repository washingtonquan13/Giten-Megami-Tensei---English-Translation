# Glyph-draw logger for dds.exe (dev builds only) -- the spike for a menu overlay.
#
# The first version of this hooked TextOutA, on the reasoning that it was the
# only text API the exe imports and had exactly one call site.  A play session
# produced no log at all: **the game never calls it.**  It imports
# GetGlyphOutlineA and blits every character itself onto the DirectDraw
# surface, which is why the CreateFontA charset patch matters (the font must be
# Shift-JIS to have the kanji) while TextOutA sits unused at 0x449A30.
#
# The real text path:
#
#     0x451230   draw one glyph.  arg1 is the character code; 0x20..0xDF come
#                from a built-in half-width bitmap font at 0x0046C230 and
#                everything else goes to GetGlyphOutlineA (its only call site,
#                0x4512B6).
#     six callers, each a draw-string variant that walks a char* to its NUL:
#                0x451650  0x451750  0x451850  0x451950  0x451B20  0x451CB0
#                (~35 call sites between them across the game)
#
# So the choke point a menu overlay would hang on is those six functions, each
# of which takes the string as an argument -- swap the pointer and the whole of
# names.py and menus.py could stop rewriting 117 pointers.
#
# This build only answers whether that would work, so it hooks the *glyph*
# level instead: the six `call 0x451230` sites become calls here, and each
# logs the arguments and tail-jumps to the real routine.  Six rel32 operands,
# no trampolines, no displaced instructions -- the same shape as the tracer's
# three exec_token redirects, and dev-only.
#
#     ddswin\textout.bin:  "GTXT" u16 version=2 u16 record_size=20
#     per glyph:           u32 arg1..arg5, exactly as the caller pushed them
#
# The arguments are logged raw rather than interpreted: 0x451230 reads arg1 and
# arg3, and naming the rest here would be a guess.  giten/textlog.py decodes
# them and rebuilds the on-screen text from the character stream.
#
# Position-independent: data is reached via call/pop, imports go through their
# IAT slots, every absolute address arrives as a --defsym.  One WriteFile per
# glyph, like trace.S -- the kernel holds the bytes, so a crash still leaves
# everything drawn so far on disk.

        .intel_syntax noprefix
        .section .text
        .globl  _start

# on entry:  [esp] return address, [esp+4..] the args the caller pushed
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
        lea     eax, [esi + hdr]            # "GTXT" 2 20
        push    eax
        push    dword ptr [esi + hfile]
        call    dword ptr [WRITEFILE_IAT]
2:
        # pushad pushed 32 and pushfd 4, so the caller's first argument -- at
        # [esp+4] on entry -- is now at [esp+40]
        lea     edi, [esi + rec]
        mov     eax, dword ptr [esp + 40]
        mov     dword ptr [edi + 0], eax
        mov     eax, dword ptr [esp + 44]
        mov     dword ptr [edi + 4], eax
        mov     eax, dword ptr [esp + 48]
        mov     dword ptr [edi + 8], eax
        mov     eax, dword ptr [esp + 52]
        mov     dword ptr [edi + 12], eax
        mov     eax, dword ptr [esp + 56]
        mov     dword ptr [edi + 16], eax

        push    0                           # lpOverlapped
        lea     eax, [esi + written]
        push    eax
        push    20
        push    edi
        push    dword ptr [esi + hfile]
        call    dword ptr [WRITEFILE_IAT]

        popfd
        popad
        mov     eax, DRAWGLYPH
        jmp     eax                         # tail call: cdecl, caller cleans up

        .balign 4
hfile:  .long   0
written: .long  0
rec:    .space  20
hdr:    .ascii  "GTXT"
        .short  2                           # format version
        .short  20                          # bytes per record
fname:  .asciz  "textout.bin"
