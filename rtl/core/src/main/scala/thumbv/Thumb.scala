package thumbv

import spinal.core._

/** The Thumb instruction set, in hardware: the length rule and the expander. */
object Thumb {
  /** The first halfword of a 32-bit Thumb instruction: bits 15:11 are 11101,
    * 11110 or 11111 (BL, MRS, MSR and the barriers on ARMv6-M). */
  def is32(hw: Bits): Bool = hw(15 downto 13) === B"111" && hw(12 downto 11) =/= B"00"

  /** The RV32 op for a Thumb instruction (hw2 is only meaningful for 32-bit ones).
    *
    * Phase 2.1 stub: just enough to test the mode switch. Everything else is
    * the all-zero illegal instruction, which traps. The real expander, a
    * translation of model/thumbv/expander.py, replaces this in 2.2.
    */
  def expand(hw1: Bits, hw2: Bits): Bits = {
    val op = B(0, 32 bits)                                    // illegal
    when(hw1 === B"x_BF00") { op := B"x_0000_0013" }          // NOP          -> addi x0, x0, 0
    when(hw1 === B"x_4770") { op := B"x_0000_8067" }          // BX LR        -> jalr x0, 0(ra)
    when(hw1 === B"x_F3BF") {
      when(hw2 === B"x_8F4F" || hw2 === B"x_8F5F") { op := B"x_0FF0_000F" }   // DSB/DMB SY -> fence
      when(hw2 === B"x_8F6F") { op := B"x_0000_100F" }        // ISB SY       -> fence.i
    }
    op
  }
}
