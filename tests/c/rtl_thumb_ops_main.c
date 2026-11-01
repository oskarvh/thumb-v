/* Phase 2.2: RISC-V main for rtl_thumb_ops.S. The startup code (crt_rv32.S)
 * has marked the Thumb library's window as a Thumb region. */

int thumb_ops(int a, int b);

int main(void)
{
    return thumb_ops(1234, 567) ^ thumb_ops(-5, 99);
}
