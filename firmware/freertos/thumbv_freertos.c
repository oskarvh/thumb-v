/* FreeRTOS on Thumb-V (Phase 5.5): what the RISC-V port leaves to the chip.
 *
 * - The tick: SysTick, through the interrupt controller, at the lowest
 *   priority as on Cortex-M. The port's trap handler becomes mtvec; it calls
 *   freertos_risc_v_application_interrupt_handler() for the controller's line
 *   (cause 11), which claims the exception, ticks the kernel for SysTick or
 *   calls the handler set with thumbv_set_handler() for anything else (either
 *   instruction set), and completes it.
 * - NZCV in each task's context: freertos_risc_v_chip_specific_extensions.h.
 * - Faults, assertions, stack overflows and a full heap are reported over the
 *   UART, and stop.
 *
 * Handlers run on the interrupt stack with interrupts disabled: the port does
 * not nest interrupts. A handler wakes a task with the FromISR API, which
 * switches context on the way out (portYIELD_FROM_ISR).
 *
 * Thumb tasks call the kernel's API by name, through the import table, like
 * any RISC-V function; the kernel's own code is RISC-V. They must not use SVC:
 * the port takes every ecall as a yield and resumes 4 bytes on. */
#include "FreeRTOS.h"
#include "task.h"
#include "thumbv.h"

void freertos_risc_v_trap_handler(void);
void thumbv_dispatch(uint32_t exception);     /* thumbv.c */

#define CSR_WRITE(op, csr, value) __asm__ volatile(op " " #csr ", %0" : : "r"(value) : "memory")

#define UART_DATA   THUMBV_REG(0x10000000)
#define UART_STATUS THUMBV_REG(0x10000004)

static void put(const char *s)
{
    while (*s) {
        while (UART_STATUS & 1)
            ;
        UART_DATA = (uint8_t)*s++;
    }
}

static void put_dec(unsigned v)
{
    char s[11];
    int i = 10;
    s[i] = 0;
    do
        s[--i] = (char)('0' + v % 10);
    while (v /= 10);
    put(&s[i]);
}

static void stop(void)
{
    portDISABLE_INTERRUPTS();
    for (;;)
        ;
}

/* Called by xPortStartScheduler(), with interrupts still disabled. */
void vPortSetupTimerInterrupt(void)
{
    CSR_WRITE("csrw", mtvec, (uint32_t)freertos_risc_v_trap_handler);
    CSR_WRITE("csrs", mie, 1u << 11);               /* MEIE: the controller's line */
    thumbv_systick_start(configCPU_CLOCK_HZ / configTICK_RATE_HZ - 1, 3);
}

void freertos_risc_v_application_interrupt_handler(void)
{
    uint32_t exception = THUMBV_CLAIM;
    if (exception == 0)                             /* nothing to claim any more */
        return;
    if (exception == THUMBV_SYSTICK) {
        if (xTaskIncrementTick() != pdFALSE)
            vTaskSwitchContext();
    } else {
        thumbv_dispatch(exception);
    }
    THUMBV_COMPLETE = exception;
}

void freertos_risc_v_application_exception_handler(uint32_t cause)
{
    uint32_t epc, tval;
    __asm__ volatile("csrr %0, mepc" : "=r"(epc));
    __asm__ volatile("csrr %0, mtval" : "=r"(tval));
    thumbv_fault(cause, epc, tval, 0);              /* reports */
    stop();
}

void thumbv_freertos_assert(const char *file, int line)
{
    put("FreeRTOS: assertion failed at ");
    put(file);
    put(":");
    put_dec((unsigned)line);
    put("\n");
    stop();
}

void vApplicationStackOverflowHook(TaskHandle_t task, char *name)
{
    (void)task;
    put("FreeRTOS: stack overflow in ");
    put(name);
    put("\n");
    stop();
}

void vApplicationMallocFailedHook(void)
{
    put("FreeRTOS: out of heap\n");
    stop();
}
