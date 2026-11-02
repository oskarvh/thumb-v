/* Phase 3.2: RISC-V main for rtl_thumb_lists.S. */

int thumb_lists(int a, int b);

int main(void)
{
    return thumb_lists(1234, 567) ^ thumb_lists(-5, 99);
}
