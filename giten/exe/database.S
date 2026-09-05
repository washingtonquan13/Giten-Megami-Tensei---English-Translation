# Item-database loader for dds.exe (English builds).
#
# The stock init at 0x004232C0 opens et\et0001.bin, calls 0x00401C30 -- which
# reads exactly *one* container -- and stores the buffer handle at ds:0x4800E8.
# One container is a u16 length, so the database can never exceed 65,535 bytes,
# and the English needs more than that (docs/format-notes.md section 6.3).
#
# This replaces that whole open/read/store/close run with one call.  We open a
# *different* file -- et\et0102.bin, ours, built by giten/itemdb.py with a u32
# offset table -- and walk its container chain, concatenating the plaintext of
# every container into one buffer.  The stock et0001.bin is left untouched on
# disk and is still what an unpatched exe reads, so the two formats can never
# be applied to each other.
#
# Register use follows the code it replaces: the caller has already saved esi
# and edi, and nothing after us reads them before setting them.  We save
# everything anyway (pushad) because the run we replace ended by leaving the
# handle in ds:0x4800E8, not in a register.
#
# The allocator (0x004044C0 -> 0x00449640) masks *both* of its arguments to 16
# bits and multiplies them, so it can never be asked for more than 65,535 bytes
# in one argument -- a fourth 64 KB limit on top of the three in section 6.3.
# It is a calloc, so the size is passed as BUF_CHUNK * BUF_COUNT instead.
#
# If the file is missing the router returns NULL and we store nothing, so the
# very next record lookup dereferences a null base and the game dies at
# startup.  That is deliberate: a loud failure on the first frame beats a
# silently half-loaded item database.
#
# Assembled with `as --32`; every absolute address is a --defsym so
# docs/format-notes.md and docs/exe-patches.md stay the source of truth.

        .intel_syntax noprefix
        .section .text

# ---------------------------------------------------------------------------
# unsigned char *resolve(char *base, unsigned offset)
#
# Replaces the shared helper 0x0040B840, which returns base + (offset & 0xFFFF).
# That mask is the third of the three 64 KB limits; the shared copy has 17
# other callers, so the record locator gets this private one instead.
# ---------------------------------------------------------------------------
        .globl  resolve
resolve:
        mov     eax, [esp+8]                # offset (now a full u32)
        add     eax, [esp+4]                # + base
        ret

# ---------------------------------------------------------------------------
# void load(void)  -- open et0102.bin, concatenate its chain, store the handle
# ---------------------------------------------------------------------------
        .globl  load
load:
        push    ebp
        mov     ebp, esp
        sub     esp, 8                      # [ebp-4]: the u16 container header
        pushad

        push    0                           # flags
        push    11                          # kind 11 = et\et%.4x.bin
        push    ET_ID
        mov     eax, ROUTER
        call    eax
        add     esp, 12
        test    eax, eax
        jz      .Ldone                      # missing file: store nothing
        mov     esi, eax                    # esi = FILE *

        push    BUF_COUNT                   # alloc(chunk, count) -> handle
        push    BUF_CHUNK                   # both are masked to 16 bits and
        mov     eax, ALLOC                  # multiplied, so the size goes in two
        call    eax
        add     esp, 8
        test    eax, eax
        jz      .Lclose
        mov     ebx, eax
        mov     [DEST], eax                 # ds:0x4800E8 = the handle

        push    ebx                         # handle -> base pointer
        mov     eax, HANDLE2PTR
        call    eax
        add     esp, 4
        mov     edi, eax                    # edi = write cursor
        mov     ebx, eax
        add     ebx, BUF_SIZE               # ebx = one past the buffer

.Lnext:
        mov     dword ptr [ebp-4], 0
        push    esi                         # fread(&hdr, 1, 2, f)
        push    2
        push    1
        lea     eax, [ebp-4]
        push    eax
        mov     eax, FREAD
        call    eax
        add     esp, 16
        cmp     eax, 2                      # short read = end of chain
        jne     .Lclose
        movzx   ecx, word ptr [ebp-4]
        test    ecx, ecx                    # a zero header stops the walk
        jz      .Lclose

        mov     eax, edi                    # would this container overrun us?
        add     eax, ecx
        cmp     eax, ebx
        ja      .Lclose

        push    ecx                         # seed the cipher from the header
        mov     eax, SETSEED
        call    eax
        add     esp, 4

        movzx   ecx, word ptr [ebp-4]
        push    edi                         # read + decrypt into the cursor
        push    ecx
        push    esi
        mov     eax, READBODY
        call    eax
        add     esp, 12

        movzx   ecx, word ptr [ebp-4]
        add     edi, ecx
        jmp     .Lnext

.Lclose:
        push    esi
        mov     eax, FCLOSE
        call    eax
        add     esp, 4

.Ldone:
        popad
        mov     esp, ebp
        pop     ebp
        ret
