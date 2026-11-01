/* Phase 3.1: RISC-V main for rtl_thumb_seq.S. */

int thumb_seq(int a, int b);

int main(void)
{
    return thumb_seq(1234, 567) ^ thumb_seq(-5, 99);
}
