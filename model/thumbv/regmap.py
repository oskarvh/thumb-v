"""Register assignment for Thumb code (decision D2 in docs/plan.md).

ARM registers sit in the RISC-V registers with the same role in AAPCS and
ilp32, so calls between the two instruction sets need no glue.
"""

# ARM r0-r14 -> RISC-V register number. r15 (PC) is the core's real PC.
ARM_TO_RV = (
    10, 11, 12, 13,          # r0-r3   -> a0-a3   arguments, caller-saved
    8, 9, 18, 19,            # r4-r7   -> s0, s1, s2, s3
    20, 21, 22, 23,          # r8-r11  -> s4-s7   callee-saved
    5,                       # r12     -> t0      scratch
    2,                       # SP      -> sp
    1,                       # LR      -> ra
    None,                    # PC
)

SP = 2
LR = 1
PC = 15  # ARM register number of the PC

# Expander temporaries, only live inside one Thumb instruction's sequence.
T1, T2, T3, T4, T5, T6 = 6, 7, 14, 15, 16, 17     # t1, t2, a4-a7

# Flag state for strategy A: each flag as 0 or 1 in its own register.
FN, FZ, FC, FV = 28, 29, 30, 31                    # t3-t6


def rv(arm_reg: int) -> int:
    """RISC-V register holding ARM register `arm_reg` (0-14)."""
    reg = ARM_TO_RV[arm_reg]
    if reg is None:
        raise ValueError("the PC has no register; the expander handles it")
    return reg
