/* Phase 4.4: loops.c without printing or interrupts, for runs without the
 * SoC (the model's lockstep against Unicorn, the all-RISC-V reference).
 * Returns what irq_loops_main.c returns. */
unsigned run_loops(int print);

int main(void)
{
    return (int)(run_loops(0) + run_loops(0));
}
