/* Phase 5.5: FreeRTOS with Thumb tasks beside RISC-V tasks.
 *
 * - producer (RISC-V): puts RTOS_JOBS jobs a round on the job queue, then
 *   waits RTOS_PAUSE ticks;
 * - two workers (Thumb, rtos_thumb.c): take a job, run rtos_crunch(), put
 *   the result on the result queue;
 * - checker (RISC-V, higher priority): recomputes each result in RISC-V and
 *   prints a line a round: jobs done by each worker, errors, a checksum;
 * - spinner (RISC-V): runs rtos_crunch() too, a step at a time with a
 *   one-tick delay, so the idle task runs as well.
 *
 * Everything runs at priority 1 but the checker (2), time-sliced by
 * SysTick. After RTOS_ROUNDS rounds (0: forever, as on the board) it stops
 * with the number of errors in a0. */
#include "FreeRTOS.h"
#include "task.h"
#include "queue.h"
#include "rtos.h"
#include "rtos_work.h"
#include "soc.h"

#ifndef RTOS_ROUNDS
#define RTOS_ROUNDS 0
#endif
#ifndef RTOS_JOBS
#define RTOS_JOBS 8
#endif
#ifndef RTOS_PAUSE
#define RTOS_PAUSE pdMS_TO_TICKS(500)
#endif

#define STACK 192   /* words */

static QueueHandle_t jobs, results;
static struct rtos_worker workers[2];
static volatile uint32_t spins;

static uint32_t seed(uint32_t round, uint32_t i)
{
    uint32_t x = round * 0x9e3779b9u + i * 0x85ebca6bu + 1;
    return x ^ (x >> 15);
}

static void producer(void *arg)
{
    (void)arg;
    for (uint32_t round = 1;; round++) {
        for (uint32_t i = 0; i < RTOS_JOBS; i++) {
            struct rtos_job job = {round * 256 + i, seed(round, i), 0, 0};
            xQueueSend(jobs, &job, portMAX_DELAY);
        }
        vTaskDelay(RTOS_PAUSE);
    }
}

static void spinner(void *arg)
{
    (void)arg;
    uint32_t x = 1;
    for (;;) {
        x = rtos_crunch(x, RTOS_STEPS / 4);
        spins++;
        vTaskDelay(1);
    }
}

static void finish(uint32_t errors)
{
    __asm__ volatile("csrc mstatus, 8\n mv a0, %0\n j done" : : "r"(errors));
}

static void checker(void *arg)
{
    (void)arg;
    uint32_t errors = 0;
    for (uint32_t round = 1;; round++) {
        uint32_t by[2] = {0, 0}, sum = 0;
        for (uint32_t i = 0; i < RTOS_JOBS; i++) {
            struct rtos_job job;
            xQueueReceive(results, &job, portMAX_DELAY);
            if (job.result != rtos_crunch(job.seed, RTOS_STEPS) || job.worker > 1 || job.id >> 8 != round)
                errors++;
            else
                by[job.worker]++;
            sum = (sum << 5 | sum >> 27) ^ job.result;
        }
        LEDS = round;
        soc_puts("round ");
        soc_put_hex(round);
        soc_puts(": Thumb tasks ");
        soc_put_hex(by[0]);
        soc_puts(" ");
        soc_put_hex(by[1]);
        soc_puts(", errors ");
        soc_put_hex(errors);
        soc_puts(", checksum ");
        soc_put_hex(sum);
        soc_puts(", tick ");
        soc_put_hex(xTaskGetTickCount());
        soc_puts(", spins ");
        soc_put_hex(spins);
        soc_putc('\n');
        if (round == RTOS_ROUNDS)
            finish(errors);
    }
}

static void create(TaskFunction_t code, const char *name, void *arg, UBaseType_t priority)
{
    if (xTaskCreate(code, name, STACK, arg, priority, NULL) != pdPASS) {
        soc_puts("xTaskCreate failed\n");
        finish(~0u);
    }
}

int main(void)
{
    soc_puts("FreeRTOS: two Thumb tasks beside RISC-V tasks\n");
    jobs = xQueueCreate(4, sizeof(struct rtos_job));
    results = xQueueCreate(4, sizeof(struct rtos_job));
    for (uint32_t i = 0; i < 2; i++)
        workers[i] = (struct rtos_worker){jobs, results, i};
    create(producer, "produce", NULL, 1);
    create(t_worker, "thumb0", &workers[0], 1);
    create(t_worker, "thumb1", &workers[1], 1);
    create(spinner, "spin", NULL, 1);
    create(checker, "check", NULL, 2);
    vTaskStartScheduler();
    soc_puts("vTaskStartScheduler returned\n");
    return -1;
}
