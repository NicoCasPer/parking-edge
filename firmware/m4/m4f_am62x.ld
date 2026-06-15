/*
 * m4f_am62x.ld — GNU ld linker script for AM62x M4FSS0-0 (Cortex-M4F)
 *
 * Toolchain : arm-none-eabi-gcc  (NOT ti-arm-clang)
 * OS        : FreeRTOS
 * Board     : BeaglePlay (AM62x)
 *
 * Memory map — AM62x TRM + SDK ipc_rpmsg_echo_linux example:
 *
 *   TCMA_M4F  0x00000000  32 KB   Tightly-Coupled Memory A (code, VT)
 *   TCMB_M4F  0x41010000  32 KB   Tightly-Coupled Memory B (data/stack)
 *   DDR_M4F   0x9C000000   1 MB   DDR shared region for M4F
 *
 * IPC / RPMsg resource table MUST land in DDR_M4F so Linux can find it.
 * All other sections follow standard Cortex-M layout.
 *
 * Usage in Makefile:
 *   LDFLAGS += -Wl,-T,m4f_am62x.ld
 */

MEMORY
{
    /*
     * TCMA: code + vector table.
     * Starts at 0x0 so the Cortex-M4 reset vector is at the right address.
     */
    TCMA_M4F   (RX)  : ORIGIN = 0x00000000, LENGTH = 0x00008000   /* 32 KB */

    /*
     * TCMB: data, BSS, stack, heap.
     */
    TCMB_M4F   (RW)  : ORIGIN = 0x41010000, LENGTH = 0x00008000   /* 32 KB */

    /*
     * DDR: large code/data overflow + RPMsg resource table.
     * Linux reads the resource table from this region via remoteproc.
     */
    DDR_M4F    (RWX) : ORIGIN = 0x9C000000, LENGTH = 0x00100000   /* 1 MB  */
}

/*
 * Stack and heap sizes.
 * FreeRTOSConfig.h sets configTOTAL_HEAP_SIZE = 64 KB;
 * the Cortex-M MSP is used only during init before vTaskStartScheduler.
 */
__stack_size = 0x1000;   /* 4 KB  MSP (pre-scheduler) */
__heap_size  = 0x0800;   /* 2 KB  newlib _sbrk region  */

ENTRY(Reset_Handler)

SECTIONS
{
    /* ------------------------------------------------------------------ */
    /* Vector table — must be at TCMA base (0x00000000)                   */
    /* ------------------------------------------------------------------ */
    .vectors :
    {
        KEEP(*(.vectors))
        KEEP(*(.isr_vector))
    } > TCMA_M4F

    /* ------------------------------------------------------------------ */
    /* Code                                                                */
    /* ------------------------------------------------------------------ */
    .text :
    {
        *(.text*)
        *(.rodata*)
        *(.glue_7)
        *(.glue_7t)
        *(.eh_frame)
        KEEP(*(.init))
        KEEP(*(.fini))
    } > TCMA_M4F

    /* ARM exception unwinding — keep for C++ / newlib */
    .ARM.extab : { *(.ARM.extab* .gnu.linkonce.armextab.*) } > TCMA_M4F
    .ARM       : {
        __exidx_start = .;
        *(.ARM.exidx*)
        __exidx_end = .;
    } > TCMA_M4F

    /* ------------------------------------------------------------------ */
    /* Init/fini arrays (needed by newlib __libc_init_array)               */
    /* ------------------------------------------------------------------ */
    .preinit_array :
    {
        PROVIDE_HIDDEN (__preinit_array_start = .);
        KEEP(*(.preinit_array*))
        PROVIDE_HIDDEN (__preinit_array_end = .);
    } > TCMA_M4F

    .init_array :
    {
        PROVIDE_HIDDEN (__init_array_start = .);
        KEEP(*(SORT(.init_array.*)))
        KEEP(*(.init_array*))
        PROVIDE_HIDDEN (__init_array_end = .);
    } > TCMA_M4F

    .fini_array :
    {
        PROVIDE_HIDDEN (__fini_array_start = .);
        KEEP(*(SORT(.fini_array.*)))
        KEEP(*(.fini_array*))
        PROVIDE_HIDDEN (__fini_array_end = .);
    } > TCMA_M4F

    /* ------------------------------------------------------------------ */
    /* Initialised data — stored in TCMA, copied to TCMB at boot           */
    /* ------------------------------------------------------------------ */
    _sidata = LOADADDR(.data);

    .data :
    {
        _sdata = .;
        *(.data*)
        . = ALIGN(4);
        _edata = .;
    } > TCMB_M4F AT > TCMA_M4F

    /* ------------------------------------------------------------------ */
    /* Zero-initialised data (BSS)                                         */
    /* ------------------------------------------------------------------ */
    .bss :
    {
        _sbss = .;
        __bss_start__ = _sbss;
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
        __bss_end__ = _ebss;
    } > TCMB_M4F

    /* ------------------------------------------------------------------ */
    /* Heap                                                                */
    /* ------------------------------------------------------------------ */
    .heap (NOLOAD) :
    {
        . = ALIGN(8);
        __heap_start = .;
        . += __heap_size;
        __heap_end = .;
    } > TCMB_M4F

    /* ------------------------------------------------------------------ */
    /* Stack (MSP — used before FreeRTOS scheduler takes over)             */
    /* ------------------------------------------------------------------ */
    .stack (NOLOAD) :
    {
        . = ALIGN(8);
        __stack_bottom = .;
        . += __stack_size;
        __stack_top = .;     /* SCB->VTOR reset handler reads SP from here */
    } > TCMB_M4F

    /* ------------------------------------------------------------------ */
    /* RPMsg / IPC resource table — in DDR so Linux remoteproc can map it  */
    /* ------------------------------------------------------------------ */
    .resource_table :
    {
        . = ALIGN(4);
        KEEP(*(.resource_table))
    } > DDR_M4F

    /* Large overflow code/data that does not fit in TCM */
    .ddr_text :
    {
        *(.ddr_text*)
    } > DDR_M4F

    .ddr_data :
    {
        *(.ddr_data*)
    } > DDR_M4F

    /* ------------------------------------------------------------------ */
    /* Discard C++ exception tables we don't use                           */
    /* ------------------------------------------------------------------ */
    /DISCARD/ :
    {
        *(.note.GNU-stack)
        *(.note.gnu.build-id)
    }
}

/*
 * Symbols exported for the startup / crt0 code.
 * A minimal Reset_Handler that calls SystemInit then main() is all that
 * is needed when using -nostartfiles with FreeRTOS.
 */
PROVIDE(__stack = __stack_top);
