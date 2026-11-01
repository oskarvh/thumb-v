/* Phase 2.4: leaf Thumb functions, compiled by arm-none-eabi-gcc, that the
 * hardware runs today: arithmetic on the arguments only.
 *
 * Until the sequencer (Phase 3), a function must not call another (gcc saves
 * LR with PUSH/POP), load constants above 255 or table addresses (literal
 * pools), or branch on a condition (no flags until Phase 4).
 * tests/test_rtl.py checks that every instruction gcc emitted is a single op.
 */

int mix(int a, int b)
{
    return ((a << 3) ^ b) * 7 + (a >> 2) - (b & 0xff);
}

unsigned xorshift(unsigned x, unsigned y)
{
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    return x + y * 33;
}
