/*
 * startup.c — Minimal Cortex-M4F startup for AM62x (arm-none-eabi-gcc)
 *
 * Responsibilities:
 *   1. Provide the vector table anchored at 0x00000000 (TCMA base)
 *   2. Reset_Handler: copy .data, zero .bss, call main()
 *
 * FreeRTOS note: vTaskStartScheduler() installs its own SysTick/PendSV/SVC
 * handlers at runtime via NVIC, so only the core fault vectors need to be
 * here. All other IRQ slots are filled with a safe Default_Handler.
 */

#include <stdint.h>

/* -------------------------------------------------------------------------
 * Symbols provided by the linker script (m4f_am62x.ld)
 * ---------------------------------------------------------------------- */
extern uint32_t _sidata;     /* LMA of .data (in TCMA flash/ROM)          */
extern uint32_t _sdata;      /* VMA start of .data (in TCMB RAM)          */
extern uint32_t _edata;      /* VMA end   of .data                        */
extern uint32_t _sbss;       /* Start of .bss                             */
extern uint32_t _ebss;       /* End   of .bss                             */
extern uint32_t __stack_top; /* Top of MSP stack (from linker script)     */

/* -------------------------------------------------------------------------
 * Forward declarations
 * ---------------------------------------------------------------------- */
void Reset_Handler(void);
void Default_Handler(void);
int  main(void);

/* Weak aliases — FreeRTOS or the SDK will override the ones it needs */
void NMI_Handler(void)          __attribute__((weak, alias("Default_Handler")));
void HardFault_Handler(void)    __attribute__((weak, alias("Default_Handler")));
void MemManage_Handler(void)    __attribute__((weak, alias("Default_Handler")));
void BusFault_Handler(void)     __attribute__((weak, alias("Default_Handler")));
void UsageFault_Handler(void)   __attribute__((weak, alias("Default_Handler")));
void SVC_Handler(void)          __attribute__((weak, alias("Default_Handler")));
void DebugMon_Handler(void)     __attribute__((weak, alias("Default_Handler")));
void PendSV_Handler(void)       __attribute__((weak, alias("Default_Handler")));
void SysTick_Handler(void)      __attribute__((weak, alias("Default_Handler")));

/* -------------------------------------------------------------------------
 * Vector table
 * Placed in .vectors so the linker script puts it at address 0x00000000.
 * ---------------------------------------------------------------------- */
__attribute__((section(".vectors"), used))
static const void *vector_table[] = {
    /* Stack pointer initial value */
    (void *)&__stack_top,

    /* Core exception vectors */
    Reset_Handler,
    NMI_Handler,
    HardFault_Handler,
    MemManage_Handler,
    BusFault_Handler,
    UsageFault_Handler,
    (void *)0,              /* Reserved */
    (void *)0,              /* Reserved */
    (void *)0,              /* Reserved */
    (void *)0,              /* Reserved */
    SVC_Handler,
    DebugMon_Handler,
    (void *)0,              /* Reserved */
    PendSV_Handler,
    SysTick_Handler,

    /*
     * Device-specific IRQs [16..]: fill with Default_Handler.
     * The TI SDK / FreeRTOS port will override these at runtime via NVIC.
     * 96 entries covers the full AM62x M4F interrupt table.
     */
    [16 ... 111] = Default_Handler,
};

/* -------------------------------------------------------------------------
 * Reset_Handler
 * Called immediately after power-on / reset.
 * ---------------------------------------------------------------------- */
__attribute__((naked, noreturn))
void Reset_Handler(void)
{
    /* Set MSP explicitly (some boot ROM paths leave SP undefined) */
    __asm volatile (
        "ldr r0, =__stack_top   \n"
        "msr msp, r0            \n"
        ::: "r0"
    );

    /* Copy initialised data from LMA (TCMA) to VMA (TCMB) */
    uint32_t *src = &_sidata;
    uint32_t *dst = &_sdata;
    while (dst < &_edata) {
        *dst++ = *src++;
    }

    /* Zero BSS */
    dst = &_sbss;
    while (dst < &_ebss) {
        *dst++ = 0U;
    }

    /* Call main — should not return under FreeRTOS */
    (void)main();

    /* Safety trap if main() ever returns */
    for (;;) {
        __asm volatile ("bkpt #0");
    }
}

/* -------------------------------------------------------------------------
 * Default_Handler — catches unhandled interrupts / faults
 * ---------------------------------------------------------------------- */
__attribute__((noreturn))
void Default_Handler(void)
{
    for (;;) {
        __asm volatile ("bkpt #0");
    }
}
