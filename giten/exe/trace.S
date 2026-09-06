# Interpreter trace hook for dds.exe (dev builds only).
#
# Every call to exec_token (0x439020) is redirected here.  We call the real
# function, then append one 12-byte record to ddswin\trace.bin:
#
#     u16 file      ds:FILEID      current script file id (0x7F00-07 = pools)
#     u16 rec       ds:RECID       current record id
#     u16 pc        [ds:CTX]+0x0E  program counter, just past the char
#     u16 ch        the character/opcode byte(s) exec_token was given
#     i16 r         exec_token's return value (-1 = page full, loop exits)
#     u8  capflag   ds:CAPFLAG     text-capture mode on/off
#     u8  caplen    strlen(CAPBUF) capped at 255 (256-byte buffer, no bound)
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
_start:
        push    ebp
        mov     ebp, esp
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
2:
        lea     edi, [esi + rec]
        mov     ax, word ptr [FILEID]
        mov     word ptr [edi+0], ax
        mov     ax, word ptr [RECID]
        mov     word ptr [edi+2], ax
        # CTX is null between scripts -- the engine clears it when a script
        # ends (the last record before it does so logs r=-1, pc=0), and
        # exec_token is still reached once afterwards.  Dereferencing it there
        # is an access violation that kills the game, and it killed it in the
        # post-battle reward sequence.  The second read of CTX below already
        # guarded this; this one did not.
        mov     ecx, dword ptr [CTX]
        xor     eax, eax                    # no context -> log pc 0
        test    ecx, ecx
        jz      6f
        mov     ax, word ptr [ecx+0x0E]
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

        # the engine's own index entry for the current record: the script
        # buffer (base = handle table[ctx.handle]) starts with 256 entries of
        # {u16 data_offset, u16 length}; this is the truth our layout model
        # is checked against
        mov     dword ptr [edi+12], 0       # default: not logged
        mov     ecx, dword ptr [CTX]
        test    ecx, ecx
        jz      5f
        mov     eax, dword ptr [ecx+0x0A]   # buffer handle; 0 = no script loaded
        test    eax, eax                    # (the engine's byte fetch guards this too)
        jz      5f
        cmp     eax, 0x1000                 # a sane handle index, not a stray pointer
        jae     5f
        mov     eax, dword ptr [HANDLE_TABLE + eax*8]
        test    eax, eax
        jz      5f
        movzx   ecx, byte ptr [RECID]       # 256 entries: the id is one byte
        mov     eax, dword ptr [eax + ecx*4]
        mov     dword ptr [edi+12], eax     # u16 idx_off, u16 idx_len
5:

        push    0                           # lpOverlapped
        lea     eax, [esi + written]
        push    eax
        push    16
        push    edi                         # lpBuffer = rec
        push    dword ptr [esi + hfile]
        call    dword ptr [WRITEFILE_IAT]

        popfd
        popad
        pop     ebp
        ret

        .balign 4
hfile:  .long   0
written: .long  0
rec:    .space  16
fname:  .asciz  "trace.bin"
