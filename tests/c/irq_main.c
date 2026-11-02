/* Phase 3.4: Thumb code under interrupts. Runs the Thumb functions of the
 * Phase 3 tests (register lists, multi-op instructions, PRIMASK changes) with
 * the timer interrupt enabled; the testbench raises it every few cycles when
 * run with +irq. The result must not depend on the interrupts. */

int thumb_lists(int a, int b);
int thumb_seq(int a, int b);
int thumb_misc(int a, int b);
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
    unsigned sum = 0;
    for (int i = 0; i < 6; i++)
        sum = sum * 31 + thumb_lists(i, sum) + thumb_seq(sum, i) + thumb_misc(sum, i);
    CSR("csrc", "mstatus", 1u << 3);
    return (int)sum;
}
