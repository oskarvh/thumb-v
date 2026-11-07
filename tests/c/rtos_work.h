/* Phase 5.5: the work shared by rtos_thumb.c (Thumb, Cortex-M0) and
 * rtos_main.c (RISC-V, which checks every result): a job, and a function
 * full of compares and conditional branches, signed and unsigned, so that a
 * Thumb task preempted between a compare and its branch goes wrong unless
 * its NZCV comes back with it. */
#ifndef RTOS_WORK_H
#define RTOS_WORK_H

#include <stdint.h>

struct rtos_job {
    uint32_t id;
    uint32_t seed;
    uint32_t worker;    /* filled in by the worker */
    uint32_t result;
};

/* What a Thumb worker task gets: its queues and its number. */
struct rtos_worker {
    void *jobs;         /* QueueHandle_t of struct rtos_job */
    void *results;
    uint32_t id;
};

#define RTOS_STEPS 300

static inline uint32_t rtos_crunch(uint32_t x, int n)
{
    uint32_t acc = 0;
    int32_t s = 0;
    for (int i = 0; i < n; i++) {
        x = (x & 1) ? 3 * x + 1 : x >> 1;
        if (x < 1000)
            x += 0x9e3779b9u;
        if ((int32_t)x < s)
            acc += x;
        else
            acc ^= x >> 3;
        s += (int32_t)(acc ^ (uint32_t)i);
        if (s == 0 || acc > 0xF0000000u)
            acc = (acc << 1) | (acc >> 31);
    }
    return acc ^ (uint32_t)s;
}

#endif
