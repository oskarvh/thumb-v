/* Thumb-V firmware: the C side of the trap entry routine, and the API in
 * thumbv.h (Phase 5.3). */
#include "thumbv.h"

#define CSR_READ(csr) ({ uint32_t v_; __asm__ volatile(".option push\n.option arch, +zicsr\n" \
                         "csrr %0, " #csr "\n.option pop" : "=r"(v_)); v_; })
#define CSR_WRITE(op, csr, value) __asm__ volatile(".option push\n.option arch, +zicsr\n" \
                         op " " #csr ", %0\n.option pop" : : "r"(value) : "memory")

#define UART_DATA   THUMBV_REG(0x10000000)
#define UART_STATUS THUMBV_REG(0x10000004)

void thumbv_trap_entry(void);

static thumbv_handler vectors[THUMBV_EXCEPTIONS];
static thumbv_svc_handler svcs[THUMBV_SVCS];

void thumbv_init(void)
{
    CSR_WRITE("csrw", mtvec, (uint32_t)thumbv_trap_entry);
    CSR_WRITE("csrs", mie, 1u << 11);       /* MEIE: the controller's line */
}

void thumbv_set_handler(int exception, thumbv_handler handler)
{
    if (exception >= 0 && exception < THUMBV_EXCEPTIONS)
        vectors[exception] = handler;
}

void thumbv_set_svc(int number, thumbv_svc_handler handler)
{
    if (number >= 0 && number < THUMBV_SVCS)
        svcs[number] = handler;
}

void thumbv_irq_enable(int irq) { NVIC_ISER = 1u << irq; }
void thumbv_irq_disable(int irq) { NVIC_ICER = 1u << irq; }
void thumbv_irq_pend(int irq) { NVIC_ISPR = 1u << irq; }

void thumbv_irq_priority(int irq, int priority)
{
    uint32_t shift = 8 * (irq % 4) + 6;
    NVIC_IPR(irq) = (NVIC_IPR(irq) & ~(3u << shift)) | (uint32_t)(priority & 3) << shift;
}

void thumbv_systick_start(uint32_t reload, int priority)
{
    SCB_SHPR3 = (SCB_SHPR3 & ~(3u << 30)) | (uint32_t)(priority & 3) << 30;
    SYST_RVR = reload;
    SYST_CVR = 0;
    SYST_CSR = 3;                           /* ENABLE, TICKINT */
}

void thumbv_systick_stop(void) { SYST_CSR = 0; }

void thumbv_pendsv_priority(int priority)
{
    SCB_SHPR3 = (SCB_SHPR3 & ~(3u << 22)) | (uint32_t)(priority & 3) << 22;
}

void thumbv_pendsv(void) { SCB_ICSR = SCB_ICSR_PENDSVSET; }
void thumbv_interrupts_on(void) { CSR_WRITE("csrs", mstatus, 1u << 3); }
void thumbv_interrupts_off(void) { CSR_WRITE("csrc", mstatus, 1u << 3); }

int thumbv_in_thumb(uint32_t addr)
{
    return (CSR_READ(0x7c0) <= addr && addr < CSR_READ(0x7c1)) ||
           (CSR_READ(0x7c2) <= addr && addr < CSR_READ(0x7c3));
}

/* --- Called by the entry routine ----------------------------------------- */

void thumbv_dispatch(uint32_t exception)
{
    thumbv_handler handler = exception < THUMBV_EXCEPTIONS ? vectors[exception] : 0;
    if (handler)
        handler();
}

static uint32_t thumb_length(uint32_t addr)
{
    uint16_t hw = *(volatile uint16_t *)addr;
    return (hw >> 11) >= 0x1d ? 4 : 2;      /* bits 15:11 = 11101, 11110 or 11111 */
}

uint32_t thumbv_trap(uint32_t cause, uint32_t *frame)
{
    uint32_t epc = frame[16];
    if (cause == 11) {                      /* SVC from Thumb, or ecall from RISC-V */
        int thumb = thumbv_in_thumb(epc);
        uint32_t number = thumb ? (*(volatile uint16_t *)epc & 0xff) : frame[11];
        if (number < THUMBV_SVCS && svcs[number]) {
            frame[4] = svcs[number](&frame[4]);
            return epc + (thumb ? 2 : 4);
        }
    }
    return thumbv_fault(cause, epc, CSR_READ(mtval), frame);
}

static void put(const char *s)
{
    while (*s) {
        while (UART_STATUS & 1)
            ;
        UART_DATA = (uint8_t)*s++;
    }
}

static void put_hex(uint32_t v)
{
    char s[9];
    for (int i = 0; i < 8; i++)
        s[i] = "0123456789abcdef"[(v >> (28 - 4 * i)) & 0xF];
    s[8] = 0;
    put(s);
}

static const char *const cause_names[] = {
    "instruction misaligned", "instruction access fault", "illegal instruction", "breakpoint",
    "load misaligned", "load access fault", "store misaligned", "store access fault",
    0, 0, 0, "unhandled SVC/ecall",
};

__attribute__((weak)) uint32_t thumbv_fault(uint32_t cause, uint32_t epc, uint32_t tval, uint32_t *frame)
{
    (void)frame;
    int thumb = thumbv_in_thumb(epc);
    put("thumbv: ");
    put(cause < 12 && cause_names[cause] ? cause_names[cause] : "trap");
    put(" at ");
    put_hex(epc);
    put(thumb ? " (Thumb), mtval " : " (RISC-V), mtval ");
    put_hex(tval);
    put("\n");
    if (cause == 3)                         /* BKPT / ebreak: report and go on */
        return epc + (thumb ? thumb_length(epc) : 4);
    for (;;)
        ;
}
