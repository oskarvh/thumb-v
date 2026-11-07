/* Phase 5.5: the interface between rtos_thumb.c (a FreeRTOS task compiled
 * for Cortex-M0) and the RISC-V side (FreeRTOS itself and rtos_main.c).
 *
 * The Thumb task calls FreeRTOS's queue API by name: the kernel is RISC-V
 * code, reached through the import table. Every signature is one that both
 * ABIs pass the same way, so the calls are direct. The types are the RISC-V
 * port's (BaseType_t is int32_t, TickType_t uint32_t, handles are pointers);
 * RISC-V code gets the kernel's own declarations from its headers. */
#include <stdint.h>
#include "thumbv_interface.h"

/* Thumb implements this; RISC-V creates two tasks running it. */
THUMBV_THUMB void t_worker(void *worker);   /* struct rtos_worker * */

#ifndef INC_FREERTOS_H
/* FreeRTOS implements these (xQueueSend is a macro for the second). */
THUMBV_RISCV int32_t xQueueReceive(void *queue, void *buffer, uint32_t ticks);
THUMBV_RISCV int32_t xQueueGenericSend(void *queue, const void *item, uint32_t ticks, int32_t position);
#endif
