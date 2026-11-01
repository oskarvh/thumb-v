/* Phase 3.3: RISC-V main for rtl_thumb_misc.S. */

int thumb_misc(int a, int b);

int main(void)
{
    return thumb_misc(0x80123456, 7) ^ thumb_misc(0x1234abcd, 99);
}
