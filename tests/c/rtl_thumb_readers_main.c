/* Phase 4.3: RISC-V main for rtl_thumb_readers.S. Returns a hash of every
 * result, which tests/test_rtl.py recomputes in Python. */

void thumb_conds(unsigned short *out);
unsigned thumb_add128(const unsigned *a, const unsigned *b, unsigned *out);
unsigned thumb_sub128(const unsigned *a, const unsigned *b, unsigned *out);
unsigned thumb_apsr(unsigned v);

static const unsigned values[][4] = {
    {0, 0, 0, 0},
    {0xffffffff, 0xffffffff, 0xffffffff, 0xffffffff},
    {1, 0, 0, 0},
    {0xffffffff, 0, 0x7fffffff, 0x80000000},
    {0x12345678, 0x9abcdef0, 0x0fedcba9, 0x87654321},
};
#define N (sizeof values / sizeof values[0])

static unsigned h;

static void mix(unsigned v)
{
    h = h * 31 + v;
}

int main(void)
{
    unsigned short conds[14];
    unsigned out[4];
    thumb_conds(conds);
    for (int i = 0; i < 14; i++)
        mix(conds[i]);
    for (unsigned i = 0; i < N; i++)
        for (unsigned j = 0; j < N; j++) {
            mix(thumb_add128(values[i], values[j], out));
            for (int k = 0; k < 4; k++)
                mix(out[k]);
            mix(thumb_sub128(values[i], values[j], out));
            for (int k = 0; k < 4; k++)
                mix(out[k]);
        }
    for (unsigned k = 0; k < 16; k++)
        mix(thumb_apsr(k << 28 | 0x01234567));
    return h;
}
