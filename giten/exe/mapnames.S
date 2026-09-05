# English location names for dds.exe.
#
# Each m\M####.bin holds its own name -- the string the location bar shows --
# at the offset in its second header word.  The map parser 0x00421470 turns
# that into a pointer exactly once:
#
#     0042147C  mov ax, word ptr [edx+2]     ; header[1]
#     00421480  push ebp
#     00421481  add eax, edx                 ; + body base
#     00421483  xor ebp, ebp
#     00421485  mov dword ptr [ebx+2], eax   ; mapstruct+2 = the name
#
# So one hook covers all 109 map files and none of them has to be edited: we
# replace the seven bytes at 0042147C with `push ebp; call lookup; nop` and
# return an English pointer instead.
#
# Which map is being parsed comes from ds:0x4716E0, which the filename router
# writes on every open (0x00401DE9).  The map is opened, read and closed
# immediately before this parse with no other file in between, so the slot
# still holds the map id.
#
# A map with no English falls through to the original computation, so an
# untranslated map keeps its Japanese name rather than showing nothing.
#
# MAPTABLE is 256 u32 slots laid out at the very start of the section, so its
# address is the section base and the code can be assembled before the table
# is filled in.
#
# Assembled with `as --32`; every absolute address is a --defsym.

        .intel_syntax noprefix
        .section .text

# ---------------------------------------------------------------------------
# const char *lookup(void)   edx = map body base; returns the name in eax.
# Clobbers eax only -- edx, ebx, ebp, esi and edi all carry live values here.
# ---------------------------------------------------------------------------
        .globl  lookup
lookup:
        push    ecx
        movzx   ecx, word ptr [MAPID]       # id of the file just opened
        cmp     ecx, MAPSLOTS
        jae     .Lfallback
        mov     eax, [MAPTABLE + ecx*4]
        test    eax, eax                    # 0 = no English for this map
        jz      .Lfallback
        pop     ecx
        ret

.Lfallback:
        movzx   eax, word ptr [edx+2]       # what the original did
        add     eax, edx
        pop     ecx
        ret
