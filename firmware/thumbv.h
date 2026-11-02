/* Thumb-V firmware for mixed programs (Phase 5.3): one trap entry routine
 * (thumbv_entry.S) for interrupts and traps from both instruction sets, and
 * a small C API. RISC-V side; Thumb code uses the SCS registers directly
 * (thumbv_scs.h), as Cortex-M code does.
 *
 * Interrupt handlers are plain functions of either instruction set, called
 * by the entry routine with interrupts enabled, so that higher priorities
 * preempt. The routine saves the caller-saved registers, mepc, mstatus and
 * NZCV around them, claims the exception from the controller and completes
 * it afterwards. A handler acknowledges its device before returning: lines
 * are level-sensitive.
 *
 * SVC from Thumb and ecall from RISC-V go to SVC handlers by number (Thumb:
 * the instruction's immediate; RISC-V: a7), with the arguments in r0-r3 /
 * a0-a3; the return value goes back in r0 / a0. Other traps go to
 * thumbv_fault(), which reports over the UART: BKPT resumes after the
 * instruction, everything else stops. Programs can replace it. */
#ifndef THUMBV_H
#define THUMBV_H

#include <stdint.h>
#include "thumbv_scs.h"

typedef void (*thumbv_handler)(void);
typedef uint32_t (*thumbv_svc_handler)(uint32_t *args);   /* args: r0-r3; returns r0 */

#define THUMBV_EXCEPTIONS 48                /* up to interrupt 31 */
#define THUMBV_SVCS 16

/* mtvec = the entry routine, mie.MEIE; interrupts stay disabled. */
void thumbv_init(void);
void thumbv_set_handler(int exception, thumbv_handler handler);
void thumbv_set_svc(int number, thumbv_svc_handler handler);

void thumbv_irq_enable(int irq);
void thumbv_irq_disable(int irq);
void thumbv_irq_pend(int irq);
void thumbv_irq_priority(int irq, int priority);          /* 0 (highest) to 3 */
void thumbv_systick_start(uint32_t reload, int priority); /* reload + 1 cycles per tick */
void thumbv_systick_stop(void);
void thumbv_pendsv_priority(int priority);
void thumbv_pendsv(void);

/* PRIMASK's RISC-V side: mstatus.MIE. */
void thumbv_interrupts_on(void);
void thumbv_interrupts_off(void);

/* In a Thumb region (the region CSRs 0x7C0-0x7C3)? */
int thumbv_in_thumb(uint32_t addr);

/* Synchronous traps other than SVC/ecall: returns where to resume. Weak:
 * programs can replace it. `frame` is the entry routine's: ra, t0-t2,
 * a0-a7, t3-t6, mepc, mstatus, NZCV. */
uint32_t thumbv_fault(uint32_t cause, uint32_t epc, uint32_t tval, uint32_t *frame);

#endif
