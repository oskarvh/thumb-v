/* Phase 4.4: loops.c under interrupts (as irq_main.c in 3.4): the timer
 * interrupt is enabled while the Thumb loops run; the result must not
 * depend on it. The interrupt comes through the controller (Phase 5.2). */
unsigned run_loops(int print);
void irq_handler(void);

volatile unsigned irq_count;

#define CSR(op, csr, value) \
    __asm__ volatile(".option push\n.option arch, +zicsr\n" op " " csr ", %0\n.option pop" \
                     : : "r"(value) : "memory")

int main(void)
{
    CSR("csrw", "mtvec", (unsigned)irq_handler);
    *(volatile unsigned *)0xE000E100 = 1; /* NVIC_ISER: interrupt 0, the testbench's */
    CSR("csrs", "mie", 1u << 11);         /* MEIE: the controller's line */
    CSR("csrs", "mstatus", 1u << 3);      /* MIE */
    unsigned sum = run_loops(0) + run_loops(0);
    CSR("csrc", "mstatus", 1u << 3);
    return (int)sum;
}
