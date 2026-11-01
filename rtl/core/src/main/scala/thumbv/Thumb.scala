package thumbv

import spinal.core._

/** RV32 instruction encoders, mirroring model/thumbv/rv32.py.
  *
  * Registers are 5-bit UInts, immediates Bits of the instruction's width.
  * Constants are defs, not vals: hardware values belong to one elaboration,
  * and GenCore elaborates two designs.
  */
object Rv {
  def X0 = U(0, 5 bits)
  def RA = U(1, 5 bits)
  def SP = U(2, 5 bits)

  def ILLEGAL = B(0x00000000L, 32 bits)
  def NOP     = B(0x00000013L, 32 bits)   // addi x0, x0, 0
  def FENCE   = B(0x0FF0000FL, 32 bits)   // fence iorw, iorw
  def FENCE_I = B(0x0000100FL, 32 bits)
  def ECALL   = B(0x00000073L, 32 bits)
  def EBREAK  = B(0x00100073L, 32 bits)
  def WFI     = B(0x10500073L, 32 bits)
  def CSRRCI_MSTATUS_MIE = B(0x30047073L, 32 bits)   // csrrci x0, mstatus, 8
  def CSRRSI_MSTATUS_MIE = B(0x30046073L, 32 bits)   // csrrsi x0, mstatus, 8

  private def op(v: Int) = B(v, 7 bits)
  private def f3(v: Int) = B(v, 3 bits)

  def r(funct7: Int, funct3: Int, rd: UInt, rs1: UInt, rs2: UInt, opcode: Int = 0x33): Bits =
    B(funct7, 7 bits) ## rs2 ## rs1 ## f3(funct3) ## rd ## op(opcode)

  def i(funct3: Int, rd: UInt, rs1: UInt, imm: Bits, opcode: Int = 0x13): Bits = {
    assert(imm.getWidth == 12)
    imm ## rs1 ## f3(funct3) ## rd ## op(opcode)
  }

  def s(funct3: Int, rs2: UInt, rs1: UInt, imm: Bits): Bits = {
    assert(imm.getWidth == 12)
    imm(11 downto 5) ## rs2 ## rs1 ## f3(funct3) ## imm(4 downto 0) ## op(0x23)
  }

  def jal(rd: UInt, off: Bits): Bits = {
    assert(off.getWidth == 21)
    off(20) ## off(10 downto 1) ## off(11) ## off(19 downto 12) ## rd ## op(0x6F)
  }

  // The ones the expander uses, with model/thumbv/rv32.py's argument order.
  def add(rd: UInt, rs1: UInt, rs2: UInt) = r(0x00, 0, rd, rs1, rs2)
  def sub(rd: UInt, rs1: UInt, rs2: UInt) = r(0x20, 0, rd, rs1, rs2)
  def and(rd: UInt, rs1: UInt, rs2: UInt) = r(0x00, 7, rd, rs1, rs2)
  def or(rd: UInt, rs1: UInt, rs2: UInt)  = r(0x00, 6, rd, rs1, rs2)
  def xor(rd: UInt, rs1: UInt, rs2: UInt) = r(0x00, 4, rd, rs1, rs2)
  def mul(rd: UInt, rs1: UInt, rs2: UInt) = r(0x01, 0, rd, rs1, rs2)
  def addi(rd: UInt, rs1: UInt, imm: Bits) = i(0, rd, rs1, imm)
  def xori(rd: UInt, rs1: UInt, imm: Bits) = i(4, rd, rs1, imm)
  def andi(rd: UInt, rs1: UInt, imm: Bits) = i(7, rd, rs1, imm)
  def slli(rd: UInt, rs1: UInt, shamt: UInt) = r(0x00, 1, rd, rs1, shamt, 0x13)
  def srli(rd: UInt, rs1: UInt, shamt: UInt) = r(0x00, 5, rd, rs1, shamt, 0x13)
  def srai(rd: UInt, rs1: UInt, shamt: UInt) = r(0x20, 5, rd, rs1, shamt, 0x13)
  def lw(rd: UInt, rs1: UInt, off: Bits)  = i(2, rd, rs1, off, 0x03)
  def lbu(rd: UInt, rs1: UInt, off: Bits) = i(4, rd, rs1, off, 0x03)
  def lhu(rd: UInt, rs1: UInt, off: Bits) = i(5, rd, rs1, off, 0x03)
  def sw(rs2: UInt, rs1: UInt, off: Bits) = s(2, rs2, rs1, off)
  def sh(rs2: UInt, rs1: UInt, off: Bits) = s(1, rs2, rs1, off)
  def sb(rs2: UInt, rs1: UInt, off: Bits) = s(0, rs2, rs1, off)
  def jalr(rd: UInt, rs1: UInt) = i(0, rd, rs1, B(0, 12 bits), 0x67)

  /** A 12-bit immediate: an unsigned value, or its negation. */
  def imm(v: UInt): Bits = v.resize(12).asBits
  def negImm(v: UInt): Bits = (U(0, 12 bits) - v.resize(12)).asBits
}

/** The Thumb instruction set, in hardware: the length rule and the expander. */
object Thumb {
  import Rv._

  /** The first halfword of a 32-bit Thumb instruction: bits 15:11 are 11101,
    * 11110 or 11111 (BL, MRS, MSR and the barriers on ARMv6-M). */
  def is32(hw: Bits): Bool = hw(15 downto 13) === B"111" && hw(12 downto 11) =/= B"00"

  /** ARM register -> RISC-V register (decision D2, model/thumbv/regmap.py).
    * r15, the PC, has no register: callers handle it before using this. */
  private val armToRv = Seq(10, 11, 12, 13, 8, 9, 18, 19, 20, 21, 22, 23, 5, 2, 1, 0)
  def reg(arm: Bits): UInt = {
    val table = Vec(armToRv.map(v => U(v, 5 bits)))
    table(arm.resize(4).asUInt)
  }

  /** The RV32 op for a Thumb instruction (hw2 only matters for 32-bit ones).
    *
    * Phase 2.2: every instruction whose expansion is a single op, with the
    * model's Options(flags = "none"), bit for bit; everything else is the
    * all-zero illegal instruction, until the sequencer (Phase 3) and the
    * flags unit (Phase 4). The rule is checked for every halfword against
    * the model (tests/test_expander_rtl.py).
    */
  def expand(hw1: Bits, hw2: Bits): Bits = is32(hw1) ? expand32(hw1, hw2) | expand16(hw1)

  private def expand16(hw: Bits): Bits = {
    val out = cloneOf(ILLEGAL)
    out := ILLEGAL

    // Common fields: low registers at bits 2:0, 5:3, 8:6 and 10:8.
    val r20 = reg(hw(2 downto 0))
    val r53 = reg(hw(5 downto 3))
    val r86 = reg(hw(8 downto 6))
    val r108 = reg(hw(10 downto 8))
    val imm3 = hw(8 downto 6).asUInt
    val imm5 = hw(10 downto 6).asUInt
    val imm7 = hw(6 downto 0).asUInt
    val imm8 = hw(7 downto 0).asUInt

    switch(hw(15 downto 11)) {
      // --- Shift (immediate), add, subtract, move, compare ---------------------
      is(B"00000") {        // LSLS rd, rm, #imm5 (imm5 = 0: MOVS rd, rm)
        out := (imm5 === 0) ? addi(r20, r53, imm(U(0))) | slli(r20, r53, imm5)
      }
      is(B"00001") {        // LSRS rd, rm, #imm5 (imm5 = 0 shifts by 32: rd = 0)
        out := (imm5 === 0) ? addi(r20, X0, imm(U(0))) | srli(r20, r53, imm5)
      }
      is(B"00010") {        // ASRS rd, rm, #imm5 (imm5 = 0 shifts by 32: as by 31)
        out := srai(r20, r53, (imm5 === 0) ? U(31, 5 bits) | imm5)
      }
      is(B"00011") {
        switch(hw(10 downto 9)) {
          is(B"00") { out := add(r20, r53, r86) }              // ADDS rd, rn, rm
          is(B"01") { out := sub(r20, r53, r86) }              // SUBS rd, rn, rm
          is(B"10") { out := addi(r20, r53, imm(imm3)) }       // ADDS rd, rn, #imm3
          is(B"11") { out := addi(r20, r53, negImm(imm3)) }    // SUBS rd, rn, #imm3
        }
      }
      is(B"00100") { out := addi(r108, X0, imm(imm8)) }        // MOVS rd, #imm8
      is(B"00101") { out := NOP }                              // CMP rn, #imm8
      is(B"00110") { out := addi(r108, r108, imm(imm8)) }      // ADDS rdn, #imm8
      is(B"00111") { out := addi(r108, r108, negImm(imm8)) }   // SUBS rdn, #imm8

      is(B"01000") {
        when(!hw(10)) {
          // --- Data processing (register): 010000 oooo mmm ddd ----------------
          switch(hw(9 downto 6)) {
            is(B"0000") { out := and(r20, r20, r53) }          // ANDS
            is(B"0001") { out := xor(r20, r20, r53) }          // EORS
            // LSLS, LSRS, ASRS (register): several ops. ADCS, SBCS: read C.
            // RORS: several ops.
            is(B"1000") { out := NOP }                         // TST
            is(B"1001") { out := sub(r20, X0, r53) }           // RSBS rd, rn, #0
            is(B"1010") { out := NOP }                         // CMP rn, rm
            is(B"1011") { out := NOP }                         // CMN
            is(B"1100") { out := or(r20, r20, r53) }           // ORRS
            is(B"1101") { out := mul(r20, r53, r20) }          // MULS rdm, rn, rdm
            // BICS: two ops.
            is(B"1111") { out := xori(r20, r53, B"xFFF") }     // MVNS
          }
        } otherwise {
          // --- Special data processing, branch exchange: 010001 oo ... --------
          val rdn = hw(7) ## hw(2 downto 0)     // D:ddd
          val rm = hw(6 downto 3)
          val pc = B"1111"
          switch(hw(9 downto 8)) {
            is(B"00") {                          // ADD rdn, rm (PC as either: several ops)
              when(rdn =/= pc && rm =/= pc) { out := add(reg(rdn), reg(rdn), reg(rm)) }
            }
            is(B"01") { out := NOP }             // CMP rn, rm (high registers)
            is(B"10") {                          // MOV rd, rm
              when(rdn === pc) {
                when(rm =/= pc) { out := jalr(X0, reg(rm)) }          // MOV pc, rm: a jump
              } elsewhen (rm =/= pc) {
                out := addi(reg(rdn), reg(rm), imm(U(0)))
              }
            }
            is(B"11") {                          // BX rm, BLX rm (bits 2:0 must be 0)
              when(hw(2 downto 0) === 0 && rm =/= pc) {
                out := jalr(hw(7) ? RA | X0, reg(rm))
              }
            }
          }
        }
      }
      // 01001 LDR (literal), 0101x loads and stores (register offset): two ops.

      // --- Loads and stores, immediate offset: ooooo iiiii nnn ttt -----------
      is(B"01100") { out := sw(r20, r53, imm(imm5 << 2)) }     // STR
      is(B"01101") { out := lw(r20, r53, imm(imm5 << 2)) }     // LDR
      is(B"01110") { out := sb(r20, r53, imm(imm5)) }          // STRB
      is(B"01111") { out := lbu(r20, r53, imm(imm5)) }         // LDRB
      is(B"10000") { out := sh(r20, r53, imm(imm5 << 1)) }     // STRH
      is(B"10001") { out := lhu(r20, r53, imm(imm5 << 1)) }    // LDRH
      is(B"10010") { out := sw(r108, SP, imm(imm8 << 2)) }     // STR rt, [sp, #imm8*4]
      is(B"10011") { out := lw(r108, SP, imm(imm8 << 2)) }     // LDR rt, [sp, #imm8*4]

      // --- Address generation (ADR: two ops) and stack adjustment ------------
      is(B"10101") { out := addi(r108, SP, imm(imm8 << 2)) }   // ADD rd, sp, #imm8*4

      is(B"10110") {
        when(hw(10 downto 8) === B"000") {                     // ADD/SUB sp, sp, #imm7*4
          out := addi(SP, SP, hw(7) ? negImm(imm7 << 2) | imm(imm7 << 2))
        }
        when(hw(10 downto 6) === B"01011") {                   // UXTB (SXTH, SXTB, UXTH: two ops)
          out := andi(r20, r53, B"x0FF")
        }
        when(hw(10 downto 9) === B"10" && hw(8 downto 0) === 0) { out := NOP }   // PUSH {}
        when(hw === B"xB672") { out := CSRRCI_MSTATUS_MIE }    // CPSID i
        when(hw === B"xB662") { out := CSRRSI_MSTATUS_MIE }    // CPSIE i
      }
      is(B"10111") {
        when(hw(10 downto 9) === B"10" && hw(8 downto 0) === 0) { out := NOP }   // POP {}
        when(hw(10 downto 8) === B"110") { out := EBREAK }     // BKPT
        when(hw(10 downto 8) === B"111" && hw(3 downto 0) === 0) {
          switch(hw(7 downto 4)) {
            is(B"0000", B"0001", B"0010", B"0100") { out := NOP }   // NOP, YIELD, WFE (Q5), SEV
            is(B"0011") { out := WFI }
          }
        }
        // REV, REV16, REVSH: several ops.
      }

      // --- Load and store multiple: ooooo nnn rrrrrrrr ------------------------
      is(B"11000") {                                           // STM rn!, {}
        when(imm8 === 0) { out := NOP }
      }
      is(B"11001") {
        when(imm8 === 0) { out := NOP }                        // LDM rn!, {}
        when(imm8 === (U(1, 8 bits) |<< hw(10 downto 8).asUInt)) {
          out := lw(r108, r108, imm(U(0)))                     // LDM rn, {rn}
        }
      }

      // --- Branches and exception generation ----------------------------------
      is(B"11010", B"11011") {
        // B<cond> reads the flags and UDF is undefined: both illegal.
        when(hw(11 downto 8) === B"1111") { out := ECALL }     // SVC
      }
      is(B"11100") {                                           // B: pc + 4 + imm11 * 2
        val off = (hw(10 downto 0).asSInt.resize(21) |<< 1) + 4
        out := jal(X0, off.asBits)
      }
    }
    out
  }

  private def expand32(hw1: Bits, hw2: Bits): Bits = {
    val out = cloneOf(ILLEGAL)
    out := ILLEGAL

    // BL: 11110 s iiiiiiiiii, 11 j 1 k iiiiiiiiiii. Beyond jal's +-1 MiB: two ops.
    when(hw1(15 downto 11) === B"11110" && hw2(15 downto 14) === B"11" && hw2(12)) {
      val s = hw1(10)
      val i1 = !(hw2(13) ^ s)
      val i2 = !(hw2(11) ^ s)
      val offset = (s ## i1 ## i2 ## hw1(9 downto 0) ## hw2(10 downto 0) ## B"0").asSInt
      val off = offset.resize(26) + 4
      val top = off(25 downto 20).asBits
      when(top === 0 || top.andR) { out := jal(RA, off(20 downto 0).asBits) }
    }
    // DSB, DMB, ISB: 1111001110111111, 1000111101oo oooo (any option).
    when(hw1 === B"xF3BF") {
      switch(hw2(15 downto 4)) {
        is(B"x8F4", B"x8F5") { out := FENCE }
        is(B"x8F6") { out := FENCE_I }
      }
    }
    // MSR, MRS: illegal without a flags unit (APSR), several ops (PRIMASK) or
    // emulated by the trap handler (the rest).
    out
  }
}

/** The expander alone, for the exhaustive check against the model
  * (sim/expander_tb.sv, tests/test_expander_rtl.py). The core uses
  * Thumb.expand directly, in the fetcher. */
class ThumbExpander extends Component {
  val io = new Bundle {
    val hw1 = in Bits(16 bits)
    val hw2 = in Bits(16 bits)
    val op = out Bits(32 bits)
  }
  io.op := Thumb.expand(io.hw1, io.hw2)
}
