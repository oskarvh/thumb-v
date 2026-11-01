/* Phase 2.2: RISC-V main for rtl_thumb_ops.S. Marks the Thumb library's
 * window as a Thumb region (CSRs 0x7C0-0x7C1), then calls into it. */

int thumb_ops(int a, int b);

static void thumb_region(unsigned base, unsigned limit)
{
    __asm__ volatile(".option push\n"
                     ".option arch, +zicsr, +zifencei\n"
                     "csrw 0x7c0, %0\n"
                     "csrw 0x7c1, %1\n"
                     "fence.i\n"
                     ".option pop" : : "r"(base), "r"(limit) : "memory");
}

int main(void)
{
    thumb_region(0x10000, 0x20000);   /* tests/link/thumb_lib.ld */
    return thumb_ops(1234, 567) ^ thumb_ops(-5, 99);
}
