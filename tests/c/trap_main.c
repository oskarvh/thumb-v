/* Phase 5.1: synchronous traps from both instruction sets. Thumb functions
 * (trap_lib.S) and RISC-V code trap; the handler records each trap and
 * resumes after the instruction: 2 or 4 bytes on for Thumb, by its length
 * rule, 4 for RISC-V. tests/test_rtl.py checks the records. */
#include <stdint.h>

void t_svc(void);
void t_bkpt(void);
void t_udf(void);
int t_mrs_msp(void);
int t_load(int *p);
int t_load_reg(char *p, int off);
void t_store(int *p, int v);
void trap_entry(void);

struct record {
    uint32_t cause, epc, tval, info;    /* info: the SVC or BKPT number */
};
struct record records[16];
int nrecords;
int results[4];

#define CSR_READ(csr) ({ uint32_t v; __asm__ volatile(".option push\n.option arch, +zicsr\n" \
                         "csrr %0, " #csr "\n.option pop" : "=r"(v)); v; })

static int in_thumb(uint32_t pc)
{
    return (CSR_READ(0x7c0) <= pc && pc < CSR_READ(0x7c1)) || (CSR_READ(0x7c2) <= pc && pc < CSR_READ(0x7c3));
}

uint32_t trap_c(uint32_t cause, uint32_t epc, uint32_t tval)
{
    uint32_t len = 4, info = 0;
    if (in_thumb(epc)) {
        uint16_t hw = *(volatile uint16_t *)epc;
        len = (hw >> 11) >= 0x1d ? 4 : 2;   /* bits 15:11 = 11101, 11110 or 11111 */
        if (cause == 11 || cause == 3)
            info = hw & 0xff;
    }
    if (nrecords < 16)
        records[nrecords++] = (struct record){cause, epc, tval, info};
    return epc + len;
}

int main(void)
{
    static int word = 0x1234;
    __asm__ volatile(".option push\n.option arch, +zicsr\ncsrw mtvec, %0\n.option pop" : : "r"(trap_entry));
    t_svc();
    t_bkpt();
    t_udf();
    results[0] = t_mrs_msp();                       /* skipped: r0 stays 0 */
    results[1] = t_load((int *)((char *)&word + 1));     /* misaligned: r0 stays the address */
    results[2] = t_load_reg((char *)&word, 2);           /* misaligned at op 1 */
    results[3] = t_load((int *)0x30000000);              /* unmapped: an access fault */
    t_store((int *)((char *)&word + 2), 5);              /* misaligned store */
    __asm__ volatile("ecall");
    __asm__ volatile("ebreak");
    uint32_t sum = 0;
    for (int i = 0; i < nrecords; i++)
        sum = sum * 31 + records[i].cause + records[i].info;
    return (int)(sum + nrecords);
}
