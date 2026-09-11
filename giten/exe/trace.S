# Interpreter trace hook for dds.exe (dev builds only).
#
# Every call to exec_token (0x439020) is redirected here.  We snapshot the
# interpreter state, call the real function, then append one 30-byte record to
# ddswin\trace.bin, behind an 8-byte file header:
#
#     header  "GTRC" u16 version=5 u16 record_size=30   (written once, at create)
#
#     u16 file      ds:FILEID      script file id (0x7F00-07 = pools)   [before]
#     u16 rec       the record the PROGRAM COUNTER is in, found by the  [before]
#                   scan below; ds:RECID only when the scan found none
#     u16 pc        [ds:CTX]+0x0E  program counter, just past the char  [after]
#     u16 ch        the character/opcode byte(s) exec_token was given
#     i16 r         exec_token's return value (-1 = page full, loop exits)
#     u8  capflag   ds:CAPFLAG     text-capture mode on/off
#     u8  caplen    strlen(CAPBUF) capped at 255 (256-byte buffer, no bound)
#     u16 idx_off   the engine's own index entry for THAT record        [before]
#     u16 idx_len                                                       [before]
#     u16 pc0       [ds:CTX]+0x0E  program counter BEFORE the token     [before]
#     u16 flags     bit0: CTX was null before the call
#                   bit1: CTX was null after it
#                   bit2: VIRTUAL -- pc0 is at or above the image end, so it
#                         names no record and idx/hash are logged as 0
#                   bit3: REC_FROM_PC -- `rec` came from the scan, not RECID
#     u16 state     ds:STATE       top-level engine state                [after]
#                   Read at write time, like capflag, so a token that changes
#                   state is logged with the state it left behind.  Good enough
#                   for "which state is a battle in" and it costs no stack slot.
#     u32 rec_hash  FNV-1a over that record's own bytes                 [before]
#     u16 image_end idx[255].off + idx[255].len                         [before]
#     u16 handle    [ds:CTX]+0x0A  the script buffer handle             [before]
#
# WHY THE RECORD IS FOUND FROM THE PROGRAM COUNTER (v5, 2026-09-11)
#
# Through v4 this hook took the record id from ds:RECID, an engine global
# written on *load*.  The interpreter runs whichever buffer its context points
# at, and several are resident at once, so the global goes stale -- and the
# whole point of the trace is to be an oracle the hook can be checked against,
# which it cannot be while it reads a different thing than hook.c does.
# hook.c's `find_record` searches the live index for the record containing the
# program counter and never reads RECID; so does this now.
#
# Measured cost of not doing it, on the 2026-09-11 Roppongi session: 165 false
# "program counter outside the record" findings, 450 events reported
# unverified, and 611 served events attributed to the wrong record -- all of
# them the Alice scene of m/MS0032 c0, where the pc was in record 0x22 and
# RECID still said 0x59.
#
# The test is `pc0 >= image_end`, not `pc0 - 1 >= image_end`, and that is not a
# fencepost slip.  The byte was fetched at pc0 - 1 only when the program
# counter advanced by one; at a handoff it did not, and the handoff that hands
# it to a record's FIRST virtual tail lands on image_end exactly (the first
# tail of a record has virt_off 0).  2,429 of the Roppongi session's events sit
# there.  Scanning for image_end - 1 would attribute every one of them to
# whichever record happens to end the buffer.  At or above the image end the
# address names no record at all, so the honest answer is VIRTUAL and an
# offline reader attributes it to the last non-virtual event on the same
# handle -- which is why the handle is logged.
#
# WHY THE HASH AND THE IMAGE END ARE LOGGED (v4, 2026-09-10)
#
# The overlay stopped identifying files.  A translated span is keyed on the
# CONTENT of the record it lives in -- (record id, record length, FNV-1a of the
# record's bytes) -- because that is the only thing about a running buffer that
# cannot go stale.  So a trace that carries only the engine's file label cannot
# be checked against the overlay at all: the label is written on load, not on
# every context switch, and the same id is reused for every shop on a map.
#
# The hash is taken from the same index entry the snapshot already reads, under
# the same guards, so it costs one pass over the record per token and no new
# engine state.  `image_end` is the four bytes the hook itself reads to decide
# whether a program counter is real or virtual; logging it is what lets an
# offline replay resolve a virtual PC without guessing which file was loaded.
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
#   [ebp-16] u32 rec_hash  [ebp-20] u16 image_end  [ebp-22] u16 handle
_start:
        push    ebp
        mov     ebp, esp
        sub     esp, 24
        pushad
        pushfd

        xor     eax, eax
        mov     word ptr [ebp-8], ax        # pc0       = 0
        mov     word ptr [ebp-6], ax        # flags     = 0
        mov     dword ptr [ebp-4], eax      # index     = not logged
        mov     dword ptr [ebp-16], eax     # rec_hash  = not logged
        mov     dword ptr [ebp-20], eax     # image_end = not logged
        mov     word ptr [ebp-22], ax       # handle    = not logged

        # WHICH of exec_token's three call sites reached us.
        #
        # All three are redirected to this one wrapper, so nothing in the record
        # said which -- and that matters: 0x4390F0 ("run this script until it
        # blocks") is reached from the per-tick background script AND from
        # 0x42F334, and a soft loop was analysed for hours on the assumption it
        # was the first without that ever being checked.
        #
        # The only thing that distinguishes them is our own return address, at
        # [ebp+4] -- we are past `push ebp; mov ebp,esp` and inside pushad, so
        # eax is free.  Their low bytes differ (0xC9, 0x08, 0x41), and flags
        # bits 8-15 were spare, so the record layout and the trace version do
        # not change; a v2 decoder that ignores them still reads this file.
        mov     eax, dword ptr [ebp+4]
        mov     ah, al
        xor     al, al
        or      word ptr [ebp-6], ax

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
        mov     word ptr [ebp-22], ax       # logged: a virtual program counter
                                            # is attributed through this offline
        test    eax, eax                    # (the engine's byte fetch guards this too)
        jz      8f
        cmp     eax, 0x1000                 # a sane handle index, not a stray pointer
        jae     8f
        mov     eax, dword ptr [HANDLE_TABLE + eax*8]
        test    eax, eax
        jz      8f
        mov     edx, eax                    # edx = the buffer base
        # Everything below reads the buffer as an index, so it is only done for
        # a real script buffer: entry 0 always sits at 0x400 there, and if it
        # does not, the offsets are not offsets and the hash loop would read
        # whatever follows.
        cmp     word ptr [edx], 0x400
        jne     8f
        movzx   ebx, word ptr [edx + 0x3FC] # idx[255].off
        movzx   esi, word ptr [edx + 0x3FE] # idx[255].len
        add     ebx, esi
        mov     word ptr [ebp-20], bx       # image_end, kept in ebx below

        # WHICH RECORD IS THE PROGRAM COUNTER IN?  The same question hook.c's
        # `find_record` answers, answered the same way: offsets are
        # non-decreasing in id (an absent record occupies one byte at its
        # slot), so the last entry at or below the address is the only
        # candidate, and it holds the address only if the address is inside its
        # length.  A linear scan down from 255 is fine -- one WriteFile per
        # token already dwarfs it.
        movzx   ecx, word ptr [ebp-8]       # pc0
        test    ecx, ecx
        jz      8f                          # no program counter: no record
        cmp     ecx, ebx
        jb      .Lreal
        or      word ptr [ebp-6], 4         # VIRTUAL: at or above the image end,
        jmp     8f                          # so idx and hash stay 0
.Lreal:
        dec     ecx                         # the address the byte came from
        cmp     ecx, 0x400
        jb      8f                          # inside the index itself: the engine
                                            # is walking a name buffer, not a record
        mov     eax, 255
.Lscan: movzx   esi, word ptr [edx + eax*4] # idx[i].off
        cmp     esi, ecx
        jbe     .Lhit
        dec     eax
        jns     .Lscan
        jmp     .Lrecid                     # no entry at or below the address
.Lhit:  movzx   edi, word ptr [edx + eax*4 + 2]
        add     edi, esi                    # idx[i].off + idx[i].len
        cmp     ecx, edi
        jae     .Lrecid                     # the candidate does not reach it
        mov     word ptr [ebp-10], ax       # rec = the record the pc is in
        or      word ptr [ebp-6], 8         # REC_FROM_PC
        jmp     .Lentry
.Lrecid:
        movzx   eax, byte ptr [RECID]       # the engine's own global, stale or
                                            # not: decode and bases still want
                                            # an id, and the flag says which
                                            # of the two this is
.Lentry:
        mov     eax, dword ptr [edx + eax*4]
        mov     dword ptr [ebp-4], eax
        # The record's own CONTENT, which is what the overlay keys on.
        movzx   esi, ax                     # this record's offset...
        shr     eax, 16                     # ...and its length
        add     esi, edx                    # esi = base + offset
        mov     edi, 0x811C9DC5             # FNV-1a over the record's bytes
        mov     ecx, eax
        test    ecx, ecx
        jz      0f
9:      movzx   eax, byte ptr [esi]
        xor     edi, eax
        imul    edi, edi, 0x01000193
        inc     esi
        dec     ecx
        jnz     9b
0:      mov     dword ptr [ebp-16], edi
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
        lea     eax, [esi + hdr]            # "GTRC" 5 30
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
        mov     eax, dword ptr [ebp-16]     # rec_hash (snapshot)
        mov     dword ptr [edi+22], eax
        mov     ax, word ptr [ebp-20]       # image_end (snapshot)
        mov     word ptr [edi+26], ax
        mov     ax, word ptr [ebp-22]       # handle   (snapshot)
        mov     word ptr [edi+28], ax

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
        mov     ax, word ptr [STATE]        # ds:0x0047BB70, top-level engine
        mov     word ptr [edi+20], ax       # state.  Fixed .data, cannot fault.

        push    0                           # lpOverlapped
        lea     eax, [esi + written]
        push    eax
        push    30
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
rec:    .space  30
hdr:    .ascii  "GTRC"
        .short  5                           # format version
        .short  30                          # bytes per record
fname:  .asciz  "trace.bin"
