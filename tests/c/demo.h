/* The board demo (demo_main.c): the interface between the Thumb build of
 * demo_blinky.c and the RISC-V side. One source, two compilers: the RISC-V
 * build is rv_blinky, the Cortex-M0 build t_blinky. */
#include <stdint.h>
#include "thumbv_interface.h"

/* What a blinky task gets. The scanner's position is shared, so the two
 * builds take over from each other where the other stopped. */
struct scanner {
    uint32_t pos;       /* the lit LED, 0-6 */
    int32_t dir;        /* +1 or -1 */
};

struct blinky {
    struct scanner *scan;
    uint32_t mark;      /* LED 7: on for the Thumb build */
    uint32_t delay;     /* ticks per step */
    uint32_t steps;     /* how many steps this build has made */
};

THUMBV_THUMB void t_blinky(void *blinky);   /* struct blinky * */

/* FreeRTOS implements these; both builds call them by name (the Thumb one
 * through the import table), with the RISC-V port's types: TickType_t is
 * uint32_t, BaseType_t int32_t. Kept out where FreeRTOS's own headers are
 * included. */
#ifndef INC_FREERTOS_H
THUMBV_RISCV void vTaskDelay(uint32_t ticks);
THUMBV_RISCV void vTaskSuspendAll(void);
THUMBV_RISCV int32_t xTaskResumeAll(void);
#endif
