# Interpreter trace hook for dds.exe (dev builds only).
#
# Every call to exec_token (0x439020) is redirected here.  We snapshot the
# interpreter state, call the real function, then append one 20-byte record to
# ddswin\trace.bin, behind an 8-byte file header:
#
#     header  "GTRC" u16 version=2 u16 record_size=20   (written once, at create)
#
#     u16 file      ds:FILEID      script file id (0x7F00-07 = pools)   [before]
#     u16 rec       ds:RECID       record id                            [before]
#     u16 pc        [ds:CTX]+0x0E  program counter, just past the char  [after]
#     u16 ch        the character/opcode byte(s) exec_token was given
#     i16 r         exec_token's return value (-1 = page full, loop exits)
#     u8  capflag   ds:CAPFLAG     text-capture mode on/off
#     u8  caplen    strlen(CAPBUF) capped at 255 (256-byte buffer, no bound)
#     u16 idx_off   the engine's own index entry for this record        [before]
#     u16 idx_len                                                       [before]
#     u16 pc0       [ds:CTX]+0x0E  program counter BEFORE the token     [before]
#     u16 flags     bit0: CTX was null before the call
#                   bit1: CTX was null after it
#
# WHY THE SNAPSHOT IS TAKEN BEFORE THE CALL
#
# CTX is null between scripts -- the engine clears it when a script ends, and
# exec_token is still reached once afterwards.  v1 read file/rec/pc and the
# index entry *after* the real call, so for every token that ended a script all
# four were lost: pc logged 0 and idx_off logged 0, and the decoder could not
# place the event at all.  That was 106 of 18,683 events on the traced routes,
# and it is a hole in the oracle, not in the model.  Reading them first records
# the state the token was actually dispatched from, which is what the decoder
# needs; the post-call pc is still logged, so its meaning is unchanged.
#
# WHY THE SNAPSHOT LIVES ON THE STACK
#
# It spans the real call, so a token whose handler reaches one of the three
# hooked call sites would overwrite a shared buffer before the outer invocation
# got to write it.  Stack locals are per-invocation, so re-entry is safe.  The
# cave's `rec` buffer is only touched after the call returns, and nothing in
# that stretch re-enters the engine, so it stays shared.
#
# Position-independent: data is reached via call/pop, the only absolute callee
# is loaded into eax as an immediate, and imports go through their IAT slots.
# Assembled with `as --32`, extracted with `objcopy -O binary`; no linker.
# Every absolute address is a --defsym so docs/exe-patches.md stays the truth.
#
# One WriteFile per token: the kernel holds the bytes, so a crash right after
# a token still leaves that token on disk.  No flush, no CloseHandle.

        .intel_syntax noprefix
        .section .text
        .globl  _start

# stack locals, all filled before the real call
#   [ebp-12] u16 file      [ebp-10] u16 rec
#   [ebp-8]  u16 pc0       [ebp-6]  u16 flags
#   [ebp-4]  u32 index entry (u16 off, u16 len)
_start:
        push    ebp
        mov     ebp, esp
        sub     esp, 12
        pushad
        pushfd

        xor     eax, eax
        mov     word ptr [ebp-8], ax        # pc0    = 0
        mov     word ptr [ebp-6], ax        # flags  = 0
        mov     dword ptr [ebp-4], eax      # index  = not logged
        mov     ax, word ptr [FILEID]
        mov     word ptr [ebp-12], ax
        mov     ax, word ptr [RECID]
        mov     word ptr [ebp-10], ax

        mov     ecx, dword ptr [CTX]
        test    ecx, ecx
        jnz     7f
        or      word ptr [ebp-6], 1         # no context to snapshot
        jmp     8f
7:
        mov     ax, word ptr [ecx+0x0E]
        mov     word ptr [ebp-8], ax        # pc0 = where this token starts
        # the engine's own index entry for the current record: the script
        # buffer (base = handle table[ctx.handle]) starts with 256 entries of
        # {u16 data_offset, u16 length}; this is the truth our layout model
        # is checked against
        mov     eax, dword ptr [ecx+0x0A]   # buffer handle; 0 = no script loaded
        test    eax, eax                    # (the engine's byte fetch guards this too)
        jz      8f
        cmp     eax, 0x1000                 # a sane handle index, not a stray pointer
        jae     8f
        mov     eax, dword ptr [HANDLE_TABLE + eax*8]
        test    eax, eax
        jz      8f
        movzx   ecx, byte ptr [RECID]       # 256 entries: the id is one byte
        mov     eax, dword ptr [eax + ecx*4]
        mov     dword ptr [ebp-4], eax
8:
        popfd
        popad

        push    dword ptr [ebp+12]          # ch
        push    dword ptr [ebp+8]           # win
        mov     eax, EXEC_TOKEN
        call    eax
        add     esp, 8

        pushad
        pushfd
        mov     ebx, eax                    # r
        mov     edx, dword ptr [ebp+12]     # ch
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
        lea     eax, [esi + hdr]            # "GTRC" 2 20
        push    eax
        push    dword ptr [esi + hfile]
        call    dword ptr [WRITEFILE_IAT]
2:
        lea     edi, [esi + rec]
        mov     ax, word ptr [ebp-12]       # file   (snapshot)
        mov     word ptr [edi+0], ax
        mov     ax, word ptr [ebp-10]       # rec    (snapshot)
        mov     word ptr [edi+2], ax
        mov     eax, dword ptr [ebp-4]      # index entry (snapshot)
        mov     dword ptr [edi+12], eax
        mov     ax, word ptr [ebp-8]        # pc0    (snapshot)
        mov     word ptr [edi+16], ax
        mov     ax, word ptr [ebp-6]        # flags  (snapshot)
        mov     word ptr [edi+18], ax

        mov     ecx, dword ptr [CTX]
        xor     eax, eax                    # no context -> log pc 0
        test    ecx, ecx
        jz      5f
        mov     ax, word ptr [ecx+0x0E]
        jmp     6f
5:      or      word ptr [edi+18], 2        # context went away during the token
6:      mov     word ptr [edi+4], ax
        mov     word ptr [edi+6], dx        # ch
        mov     word ptr [edi+8], bx        # r
        mov     al, byte ptr [CAPFLAG]
        mov     byte ptr [edi+10], al
        xor     ecx, ecx
3:      cmp     byte ptr [CAPBUF + ecx], 0
        je      4f
        inc     ecx
        cmp     ecx, 255
        jb      3b
4:      mov     byte ptr [edi+11], cl

        push    0                           # lpOverlapped
        lea     eax, [esi + written]
        push    eax
        push    20
        push    edi                         # lpBuffer = rec
        push    dword ptr [esi + hfile]
        call    dword ptr [WRITEFILE_IAT]

        popfd
        popad
        leave
        ret

        .balign 4
hfile:  .long   0
written: .long  0
rec:    .space  20
hdr:    .ascii  "GTRC"
        .short  2                           # format version
        .short  20                          # bytes per record
fname:  .asciz  "trace.bin"
