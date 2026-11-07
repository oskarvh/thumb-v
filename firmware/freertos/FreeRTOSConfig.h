/* FreeRTOS configuration for Thumb-V (Phase 5.5): the RISC-V port, ticked by
 * SysTick through the interrupt controller (thumbv_freertos.c).
 *
 * Sized for the board: the RISC-V side has 8 KiB of data RAM there,
 * shared with main's stack (docs/board.md), which the port reuses as the
 * interrupt stack once the scheduler runs. Programs can override the tick
 * rate and heap size with -D. */
#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

#define configCPU_CLOCK_HZ                  12000000    /* the board's clock */
#ifndef configTICK_RATE_HZ
#define configTICK_RATE_HZ                  1000
#endif
#define configTICK_TYPE_WIDTH_IN_BITS       TICK_TYPE_WIDTH_32_BITS

/* No mtime: SysTick instead. */
#define configMTIME_BASE_ADDRESS            0
#define configMTIMECMP_BASE_ADDRESS         0

#define configUSE_PREEMPTION                1
#define configUSE_TIME_SLICING              1
#define configUSE_PORT_OPTIMISED_TASK_SELECTION 0
#define configMAX_PRIORITIES                4
#define configMINIMAL_STACK_SIZE            128         /* words */
#define configMAX_TASK_NAME_LEN             8
#define configIDLE_SHOULD_YIELD             1

#define configSUPPORT_DYNAMIC_ALLOCATION    1
#define configSUPPORT_STATIC_ALLOCATION     0
#ifndef configTOTAL_HEAP_SIZE
#define configTOTAL_HEAP_SIZE               6144
#endif

#define configUSE_IDLE_HOOK                 1   /* thumbv_freertos.c */
#define configUSE_TICK_HOOK                 0
#define configUSE_MALLOC_FAILED_HOOK        1
#define configCHECK_FOR_STACK_OVERFLOW      2
#define configUSE_MUTEXES                   0
#define configUSE_RECURSIVE_MUTEXES         0
#define configUSE_COUNTING_SEMAPHORES       0
#define configUSE_TIMERS                    0
#define configUSE_TRACE_FACILITY            0
#define configUSE_CO_ROUTINES               0
#define configQUEUE_REGISTRY_SIZE           0

#define INCLUDE_vTaskDelay                  1
#define INCLUDE_vTaskDelete                 0
#define INCLUDE_vTaskSuspend                1
#define INCLUDE_xTaskGetSchedulerState      0

/* An assertion reports where over the UART and stops (thumbv_freertos.c). */
void thumbv_freertos_assert(const char *file, int line);
#define configASSERT(x) do { if (!(x)) thumbv_freertos_assert(__FILE_NAME__, __LINE__); } while (0)

#endif
