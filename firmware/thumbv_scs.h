/* Thumb-V's System Control Space and interrupt controller registers
 * (rtl/soc/thumbv_nvic.v, model/thumbv/nvic.py), for C code of either
 * instruction set. The SCS registers are the ARMv6-M ones, so Cortex-M code
 * can use these, or CMSIS's, unchanged. */
#ifndef THUMBV_SCS_H
#define THUMBV_SCS_H

#include <stdint.h>

#define THUMBV_REG(addr) (*(volatile uint32_t *)(addr))

#define SYST_CSR   THUMBV_REG(0xE000E010)   /* ENABLE 0, TICKINT 1, CLKSOURCE 2, COUNTFLAG 16 */
#define SYST_RVR   THUMBV_REG(0xE000E014)
#define SYST_CVR   THUMBV_REG(0xE000E018)
#define NVIC_ISER  THUMBV_REG(0xE000E100)
#define NVIC_ICER  THUMBV_REG(0xE000E180)
#define NVIC_ISPR  THUMBV_REG(0xE000E200)
#define NVIC_ICPR  THUMBV_REG(0xE000E280)
#define NVIC_IPR(n) THUMBV_REG(0xE000E400 + 4 * ((n) / 4))
#define SCB_ICSR   THUMBV_REG(0xE000ED04)   /* PENDSVSET 28, PENDSTSET 26, VECTACTIVE 8:0 */
#define SCB_SHPR3  THUMBV_REG(0xE000ED20)   /* SysTick 31:30, PendSV 23:22 */

/* Thumb-V's: software interrupt entry (thumbv_entry.S). */
#define THUMBV_CLAIM    THUMBV_REG(0x10001000)
#define THUMBV_COMPLETE THUMBV_REG(0x10001004)

/* Exception numbers, as on Cortex-M. */
#define THUMBV_PENDSV   14
#define THUMBV_SYSTICK  15
#define THUMBV_IRQ(n)   (16 + (n))

#define SCB_ICSR_PENDSVSET (1u << 28)

#endif
