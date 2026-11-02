/* Phase 4.4: loops.c under interrupts (as irq_main.c in 3.4): the timer
 * interrupt is enabled while the Thumb loops run; the result must not
 * depend on it. Also the native reference, built all-RISC-V. */
unsigned run_loops(int print);
void irq_handler(void);

volatile unsigned irq_count;

#define CSR(op, csr, value) \
    __asm__ volatile(".option push\n.option arch, +zicsr\n" op " " csr ", %0\n.option pop" \
                     : : "r"(value) : "memory")

int main(void)
{
    CSR("csrw", "mtvec", (unsigned)irq_handler);
    CSR("csrs", "mie", 1u << 7);          /* MTIE */
    CSR("csrs", "mstatus", 1u << 3);      /* MIE */
    unsigned sum = run_loops(0) + run_loops(0);
    CSR("csrc", "mstatus", 1u << 3);
    return (int)sum;
}
