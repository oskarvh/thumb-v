/* The board demo: FreeRTOS with three tasks.
 *
 * - two blinkies, the same C code (demo_blinky.c) built for RISC-V and for
 *   Cortex-M0 (Thumb): a scanner on LEDs 0-6, with LED 7 on for Thumb;
 * - the orchestrator (RISC-V): each press of the board's button switches
 *   which of them runs, by suspending one and resuming the other, and says
 *   so over the UART.
 *
 * The button interrupt (line 1) wakes the orchestrator with a task
 * notification. DEMO_SWITCHES stops after that many switches (for the
 * simulation; 0: forever). */
#include "FreeRTOS.h"
#include "task.h"
#include "demo.h"
#include "soc.h"
#include "thumbv.h"

#ifndef DEMO_STEP
#define DEMO_STEP pdMS_TO_TICKS(80)     /* ticks per scanner step */
#endif
#ifndef DEMO_SETTLE
#define DEMO_SETTLE pdMS_TO_TICKS(150)  /* presses this soon after a switch are ignored */
#endif
#ifndef DEMO_SWITCHES
#define DEMO_SWITCHES 0
#endif

#define BUTTON (*(volatile uint32_t *)0x10000010)   /* bit 0 held, bit 1 pressed (write 1 to clear) */
#define BUTTON_IRQ 1

void rv_blinky(void *arg);

static struct scanner scan = {0, 1};
static struct blinky blinkies[2] = {
    {&scan, 0x00, DEMO_STEP, 0},     /* RISC-V */
    {&scan, 0x80, DEMO_STEP, 0},     /* Thumb */
};
static const char *const names[2] = {"RISC-V", "Thumb (Cortex-M0)"};
static TaskHandle_t tasks[2], orchestrator_task;

static void button_handler(void)
{
    BUTTON = 2;                         /* clear the press: the line is level-sensitive */
    BaseType_t woken = pdFALSE;
    vTaskNotifyGiveFromISR(orchestrator_task, &woken);
    portYIELD_FROM_ISR(woken);
}

static void say(const char *what, int now)
{
    soc_puts(what);
    soc_puts(names[now]);
    soc_puts(" blinky; steps so far: RISC-V ");
    soc_put_hex(blinkies[0].steps);
    soc_puts(", Thumb ");
    soc_put_hex(blinkies[1].steps);
    soc_putc('\n');
}

static void orchestrator(void *arg)
{
    (void)arg;
    int now = 0;
    say("running the ", now);
    for (unsigned n = 1;; n++) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        vTaskSuspend(tasks[now]);
        now ^= 1;
        vTaskResume(tasks[now]);
        say("button: switched to the ", now);
        if (n == DEMO_SWITCHES)
            __asm__ volatile("csrc mstatus, 8\n li a0, 0\n j done");
        vTaskDelay(DEMO_SETTLE);
        ulTaskNotifyTake(pdTRUE, 0);    /* drop presses during the settle time */
    }
}

int main(void)
{
    soc_puts("Thumb-V demo: press the button to switch between the RISC-V and Thumb builds\n");
    thumbv_set_handler(THUMBV_IRQ(BUTTON_IRQ), button_handler);
    BUTTON = 2;
    thumbv_irq_enable(BUTTON_IRQ);
    xTaskCreate(orchestrator, "orch", 192, NULL, 2, &orchestrator_task);
    xTaskCreate(rv_blinky, "rv", 160, &blinkies[0], 1, &tasks[0]);
    xTaskCreate(t_blinky, "thumb", 160, &blinkies[1], 1, &tasks[1]);
    vTaskSuspend(tasks[1]);
    vTaskStartScheduler();
    return -1;
}
