/* Phase 5.5: a FreeRTOS task compiled for Cortex-M0. RISC-V code creates two
 * of them; each takes jobs from one queue and puts results on another, with
 * FreeRTOS's own API (rtos.h). Both run rtos_crunch(), so whenever one is
 * preempted the other changes the flags. */
#include "rtos.h"
#include "rtos_work.h"

#define portMAX_DELAY 0xffffffffu
#define queueSEND_TO_BACK 0

void t_worker(void *arg)
{
    struct rtos_worker *w = arg;
    struct rtos_job job;
    for (;;) {
        xQueueReceive(w->jobs, &job, portMAX_DELAY);
        job.worker = w->id;
        job.result = rtos_crunch(job.seed, RTOS_STEPS);
        xQueueGenericSend(w->results, &job, portMAX_DELAY, queueSEND_TO_BACK);
    }
}
