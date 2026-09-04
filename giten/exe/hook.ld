/* Link hook.c as one flat blob at the cave's virtual address (CAVE_VA is a
 * --defsym).  Code, read-only data, data and bss all land in one section, the
 * hook itself first, so the blob's first byte is the function the five fetch
 * call sites are redirected to. */
ENTRY(_hook)
SECTIONS
{
  . = CAVE_VA;
  .text : {
    *(.text.entry)
    *(.text .text.*)
    *(.rdata .rdata.*)
    *(.data .data.*)
    *(.bss .bss.*)
    *(COMMON)
  }
  /DISCARD/ : { *(.drectve) *(.comment) *(.eh_frame) *(.pdata) *(.xdata) *(.rsrc) *(.idata*) *(.reloc) }
}
