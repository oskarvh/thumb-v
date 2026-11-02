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
  def T1 = U(6, 5 bits)     // expander temporaries (model/thumbv/regmap.py)
  def T2 = U(7, 5 bits)
  def T3 = U(14, 5 bits)
  def T4 = U(15, 5 bits)

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

  def u(rd: UInt, imm20: Bits, opcode: Int): Bits = {
    assert(imm20.getWidth == 20)
    imm20 ## rd ## op(opcode)
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
  def sll(rd: UInt, rs1: UInt, rs2: UInt) = r(0x00, 1, rd, rs1, rs2)
  def srl(rd: UInt, rs1: UInt, rs2: UInt) = r(0x00, 5, rd, rs1, rs2)
  def sra(rd: UInt, rs1: UInt, rs2: UInt) = r(0x20, 5, rd, rs1, rs2)
  def sltu(rd: UInt, rs1: UInt, rs2: UInt) = r(0x00, 3, rd, rs1, rs2)
  def sltiu(rd: UInt, rs1: UInt, imm: Bits) = i(3, rd, rs1, imm)
  def lui(rd: UInt, imm20: Bits) = u(rd, imm20, 0x37)
  def csrrs(rd: UInt, csr: Int, rs1: UInt) = i(2, rd, rs1, B(csr, 12 bits), 0x73)
  def addi(rd: UInt, rs1: UInt, imm: Bits) = i(0, rd, rs1, imm)
  def xori(rd: UInt, rs1: UInt, imm: Bits) = i(4, rd, rs1, imm)
  def andi(rd: UInt, rs1: UInt, imm: Bits) = i(7, rd, rs1, imm)
  def slli(rd: UInt, rs1: UInt, shamt: UInt) = r(0x00, 1, rd, rs1, shamt.resize(5), 0x13)
  def srli(rd: UInt, rs1: UInt, shamt: UInt) = r(0x00, 5, rd, rs1, shamt.resize(5), 0x13)
  def srai(rd: UInt, rs1: UInt, shamt: UInt) = r(0x20, 5, rd, rs1, shamt.resize(5), 0x13)
  def lb(rd: UInt, rs1: UInt, off: Bits)  = i(0, rd, rs1, off, 0x03)
  def lh(rd: UInt, rs1: UInt, off: Bits)  = i(1, rd, rs1, off, 0x03)
  def lw(rd: UInt, rs1: UInt, off: Bits)  = i(2, rd, rs1, off, 0x03)
  def lbu(rd: UInt, rs1: UInt, off: Bits) = i(4, rd, rs1, off, 0x03)
  def lhu(rd: UInt, rs1: UInt, off: Bits) = i(5, rd, rs1, off, 0x03)
  def sw(rs2: UInt, rs1: UInt, off: Bits) = s(2, rs2, rs1, off)
  def sh(rs2: UInt, rs1: UInt, off: Bits) = s(1, rs2, rs1, off)
  def sb(rs2: UInt, rs1: UInt, off: Bits) = s(0, rs2, rs1, off)
  def jalr(rd: UInt, rs1: UInt, off: Bits = B(0, 12 bits)) = i(0, rd, rs1, off, 0x67)
  def auipc(rd: UInt, imm20: Bits = B(0, 20 bits)) = u(rd, imm20, 0x17)

  /** A 12-bit immediate: an unsigned value, or its negation. */
  def imm(v: UInt): Bits = v.resize(12).asBits
  def negImm(v: UInt): Bits = (U(0, 12 bits) - v.resize(12)).asBits

  /** `op` with a flags kind (and, for BRANCH, an ARM condition) beside it:
    * 40 bits, side-band ## op, as model/thumbv/rv32.py's `flagged`. */
  def flagged(op: Bits, kind: Int, cond: Bits = B(0, 4 bits)): Bits = cond ## B(kind, 4 bits) ## op
}

/** The flags kinds of strategy C (model/thumbv/rv32.py, docs/plan.md Phase 4). */
object Flags {
  val NZ = 1        // N, Z from the result
  val ADD = 2       // rd = rs1 + src2, NZCV from the adder
  val SUB = 3       // rd = rs1 - src2 (also on addi), C = NOT borrow
  val ADC = 4       // rd = rs1 + src2 + C
  val SBC = 5       // rd = rs1 - src2 - NOT C
  val SHL = 6       // N, Z from the result, C = rs1[-shamt mod 32]
  val SHR = 7       // N, Z from the result, C = rs1[(shamt - 1) mod 32]
  val CW = 8        // C = result[0] if result[1] is set
  val BRANCH = 9    // on beq x0, x0: taken only if the condition holds
}

/** The Thumb instruction set, in hardware: the length rule and the expander. */
object Thumb {
  import Rv._
  import Flags._

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

  /** One op of a Thumb instruction's expansion. */
  case class ThumbOp() extends Bundle {
    val op = Bits(32 bits)
    val side = Bits(8 bits) // the flags side-band: condition (7:4), kind (3:0)
    val last = Bool()       // the expansion's last op: the PC moves on after it
  }

  /** Collects the decoded instruction's expansion: `out := op` for a single
    * op, `out.seq(op0, op1, ...)` for a fixed sequence, `out.at(op, last)`
    * for one whose length varies (register lists), with op and last computed
    * from `step` by the caller. `step` picks the op to emit. */
  private class Ops(step: UInt) {
    val result = ThumbOp()
    // An op is a 32-bit RV32 word, or 40 bits with the flags side-band (flagged).
    private val wide = Bits(40 bits)
    wide := B(0, 8 bits) ## ILLEGAL
    result.op := wide(31 downto 0)
    result.side := wide(39 downto 32)
    result.last := True
    private def w(op: Bits): Bits = if (op.getWidth == 40) op else B(0, 8 bits) ## op
    def :=(op: Bits): Unit = seq(op)
    def seq(ops: Bits*): Unit = {
      wide := w(ops.head)
      for (i <- 1 until ops.size) when(step === i) { wide := w(ops(i)) }
      result.last := step === ops.size - 1
    }
    def at(op: Bits, last: Bool): Unit = {
      wide := w(op)
      result.last := last
    }
  }

  // --- Register lists (PUSH, POP, LDM, STM) -----------------------------------

  /** The number of registers in a list. */
  private def count(list: Bits): UInt = list.asBools.map(_.asUInt.resize(4 bits)).reduce(_ + _)

  /** The bit number of the k-th register in a list, from the lowest. */
  private def nth(list: Bits, k: UInt): UInt = {
    val index = U(0, 4 bits)
    for (i <- 0 until list.getWidth) {
      val below = if (i == 0) U(0, 4 bits) else count(list(i - 1 downto 0))
      when(list(i) && below === k) { index := i }
    }
    index
  }

  /** How many registers of a list are below register `index`: its slot. */
  private def rank(list: Bits, index: UInt): UInt = {
    val masked = list & ((U(1, list.getWidth bits) |<< index) - 1).asBits
    count(masked)
  }

  /** A word offset as a 12-bit immediate: slot * 4. */
  private def words(slot: UInt): Bits = imm(slot.resize(10) << 2)

  /** Op `step` of a Thumb instruction's expansion (hw2 only matters for
    * 32-bit instructions; pc1 is bit 1 of the instruction's address).
    *
    * The model, model/thumbv/expander.py with Options(flags = "C",
    * flag_readers = False) (rtlsim.HARDWARE), is the reference, op for op and
    * bit for bit, side-band included, for every instruction. Flag-setting
    * instructions are strategy C (Phase 4.2). Instructions that read the
    * flags (ADCS, SBCS, B<cond>, the APSR) are still the all-zero illegal
    * instruction, as in that mode. tests/test_expander_rtl.py checks this for every 16-bit
    * instruction at both alignments, and a large sweep of 32-bit ones.
    */
  def expand(hw1: Bits, hw2: Bits, pc1: Bool, step: UInt): ThumbOp = {
    val result = ThumbOp()
    when(is32(hw1)) { result := expand32(hw1, hw2, step) } otherwise { result := expand16(hw1, pc1, step) }
    result
  }

  private def expand16(hw: Bits, pc1: Bool, step: UInt): ThumbOp = {
    val out = new Ops(step)

    // Common fields: low registers at bits 2:0, 5:3, 8:6 and 10:8.
    val r20 = reg(hw(2 downto 0))
    val r53 = reg(hw(5 downto 3))
    val r86 = reg(hw(8 downto 6))
    val r108 = reg(hw(10 downto 8))
    val imm3 = hw(8 downto 6).asUInt
    val imm5 = hw(10 downto 6).asUInt
    val imm7 = hw(6 downto 0).asUInt
    val imm8 = hw(7 downto 0).asUInt
    // Offset from the instruction's address to Align(PC + 4, 4) + imm8 * 4,
    // for LDR (literal) and ADR.
    val literal = (imm8 << 2).resize(12) + (pc1 ? U(2, 12 bits) | U(4, 12 bits))

    switch(hw(15 downto 11)) {
      // --- Shift (immediate), add, subtract, move, compare ---------------------
      is(B"00000") {        // LSLS rd, rm, #imm5 (imm5 = 0: MOVS rd, rm, C unchanged)
        out := (imm5 === 0) ? flagged(addi(r20, r53, imm(U(0))), NZ) | flagged(slli(r20, r53, imm5), SHL)
      }
      // LSRS, ASRS by imm5; imm5 = 0 shifts by 32: C = rm[31] (SHR with shamt 0
      // reads bit (0 - 1) mod 32), then the result (0, or as by 31) with N, Z.
      is(B"00001") {        // LSRS rd, rm, #imm5
        when(imm5 === 0) { out.seq(flagged(srli(T1, r53, U(0)), SHR), flagged(addi(r20, X0, imm(U(0))), NZ)) }
          .otherwise { out := flagged(srli(r20, r53, imm5), SHR) }
      }
      is(B"00010") {        // ASRS rd, rm, #imm5
        when(imm5 === 0) { out.seq(flagged(srli(T1, r53, U(0)), SHR), flagged(srai(r20, r53, U(31)), NZ)) }
          .otherwise { out := flagged(srai(r20, r53, imm5), SHR) }
      }
      is(B"00011") {
        switch(hw(10 downto 9)) {
          is(B"00") { out := flagged(add(r20, r53, r86), ADD) }          // ADDS rd, rn, rm
          is(B"01") { out := flagged(sub(r20, r53, r86), SUB) }          // SUBS rd, rn, rm
          is(B"10") { out := flagged(addi(r20, r53, imm(imm3)), ADD) }   // ADDS rd, rn, #imm3
          is(B"11") { out := flagged(addi(r20, r53, imm(imm3)), SUB) }   // SUBS: SUB makes addi subtract
        }
      }
      is(B"00100") { out := flagged(addi(r108, X0, imm(imm8)), NZ) }     // MOVS rd, #imm8
      is(B"00101") { out := flagged(addi(X0, r108, imm(imm8)), SUB) }    // CMP rn, #imm8
      is(B"00110") { out := flagged(addi(r108, r108, imm(imm8)), ADD) }  // ADDS rdn, #imm8
      is(B"00111") { out := flagged(addi(r108, r108, imm(imm8)), SUB) }  // SUBS rdn, #imm8

      is(B"01000") {
        when(!hw(10)) {
          // --- Data processing (register): 010000 oooo mmm ddd ----------------
          // C = T2 | (amount != 0) << 1 with kind CW: C alone for an amount of 0.
          val cIfNonzero = Seq(sltu(T3, X0, T1), slli(T3, T3, U(1)), flagged(or(T2, T2, T3), CW))
          switch(hw(9 downto 6)) {
            is(B"0000") { out := flagged(and(r20, r20, r53), NZ) }   // ANDS
            is(B"0001") { out := flagged(xor(r20, r20, r53), NZ) }   // EORS
            // Shifts by a register: the amount is rm[7:0]; 32 and more shift
            // everything out (LSL, LSR) or behave as 31 (ASR). C is computed
            // in software (Q3): a candidate in T2, then cIfNonzero. The
            // result's last op sets N and Z.
            is(B"0010") {                                      // LSLS rdn, rm
              out.seq(Seq(andi(T1, r53, B"x0FF"),
                          sub(T2, X0, T1), srl(T2, r20, T2), sltiu(T3, T1, imm(U(33))), and(T2, T2, T3)) ++
                      cIfNonzero ++
                      Seq(sll(T4, r20, T1), sltiu(T3, T1, imm(U(32))), sub(T3, X0, T3),
                          flagged(and(r20, T4, T3), NZ)): _*)
            }
            is(B"0011") {                                      // LSRS rdn, rm
              out.seq(Seq(andi(T1, r53, B"x0FF"),
                          addi(T2, T1, B"xFFF"), srl(T2, r20, T2), sltiu(T3, T1, imm(U(33))), and(T2, T2, T3)) ++
                      cIfNonzero ++
                      Seq(srl(T4, r20, T1), sltiu(T3, T1, imm(U(32))), sub(T3, X0, T3),
                          flagged(and(r20, T4, T3), NZ)): _*)
            }
            is(B"0100") {                                      // ASRS rdn, rm
              out.seq(Seq(andi(T1, r53, B"x0FF"),
                          addi(T2, T1, B"xFFF"), sltiu(T3, T2, imm(U(32))), addi(T3, T3, B"xFFF"),
                          or(T2, T2, T3), srl(T2, r20, T2), andi(T2, T2, B"x001")) ++
                      cIfNonzero ++
                      Seq(sltiu(T3, T1, imm(U(32))), addi(T3, T3, B"xFFF"), or(T3, T1, T3),
                          flagged(sra(r20, r20, T3), NZ)): _*)
            }
            // ADCS, SBCS: read C, still illegal (Phase 4.3).
            is(B"0111") {                                      // RORS rdn, rm: C is the result's bit 31
              out.seq(Seq(andi(T1, r53, B"x0FF"),
                          andi(T3, T1, B"x01F"), srl(T4, r20, T3), sub(T3, X0, T3), sll(T3, r20, T3),
                          flagged(or(r20, T4, T3), NZ), srli(T2, r20, U(31))) ++
                      cIfNonzero: _*)
            }
            is(B"1000") { out := flagged(and(X0, r20, r53), NZ) }    // TST rn, rm
            is(B"1001") { out := flagged(sub(r20, X0, r53), SUB) }   // RSBS rd, rn, #0
            is(B"1010") { out := flagged(sub(X0, r20, r53), SUB) }   // CMP rn, rm
            is(B"1011") { out := flagged(add(X0, r20, r53), ADD) }   // CMN rn, rm
            is(B"1100") { out := flagged(or(r20, r20, r53), NZ) }    // ORRS
            // MULS rdm, rn, rdm: the product only exists in writeback, the
            // flags unit works in execute, so N, Z come from a second op.
            is(B"1101") { out.seq(mul(r20, r53, r20), flagged(addi(r20, r20, imm(U(0))), NZ)) }
            is(B"1110") { out.seq(xori(T1, r53, B"xFFF"), flagged(and(r20, r20, T1), NZ)) }   // BICS
            is(B"1111") { out := flagged(xori(r20, r53, B"xFFF"), NZ) }   // MVNS
          }
        } otherwise {
          // --- Special data processing, branch exchange: 010001 oo ... --------
          val rdn = hw(7) ## hw(2 downto 0)     // D:ddd
          val rm = hw(6 downto 3)
          val pc = B"1111"
          switch(hw(9 downto 8)) {
            is(B"00") {                          // ADD rdn, rm
              when(rdn =/= pc && rm =/= pc) { out := add(reg(rdn), reg(rdn), reg(rm)) }
              // The PC reads as PC + 4; written, it's a jump to the sum.
              when(rdn =/= pc && rm === pc) {
                out.seq(auipc(T1), addi(T1, T1, imm(U(4))), add(reg(rdn), reg(rdn), T1))
              }
              when(rdn === pc && rm =/= pc) {
                out.seq(auipc(T1), add(T1, T1, reg(rm)), jalr(X0, T1, imm(U(4))))
              }
              when(rdn === pc && rm === pc) {
                out.seq(auipc(T2), addi(T2, T2, imm(U(4))), auipc(T1), add(T1, T1, T2), jalr(X0, T1, imm(U(4))))
              }
            }
            is(B"01") {                          // CMP rn, rm (high registers): the PC reads as PC + 4
              val rn = hw(7) ## hw(2 downto 0)
              val readN = Seq(auipc(T2), addi(T2, T2, imm(U(4))))
              val readM = Seq(auipc(T3), addi(T3, T3, imm(U(4))))
              when(rn =/= pc && rm =/= pc) { out := flagged(sub(X0, reg(rn), reg(rm)), SUB) }
              when(rn === pc && rm =/= pc) { out.seq(readN :+ flagged(sub(X0, T2, reg(rm)), SUB): _*) }
              when(rn =/= pc && rm === pc) { out.seq(readM :+ flagged(sub(X0, reg(rn), T3), SUB): _*) }
              when(rn === pc && rm === pc) { out.seq(readN ++ readM :+ flagged(sub(X0, T2, T3), SUB): _*) }
            }
            is(B"10") {                          // MOV rd, rm
              when(rdn === pc) {
                when(rm =/= pc) { out := jalr(X0, reg(rm)) }          // MOV pc, rm: a jump
                  .otherwise { out.seq(auipc(T1), addi(T1, T1, imm(U(4))), jalr(X0, T1)) }
              } elsewhen (rm =/= pc) {
                out := addi(reg(rdn), reg(rm), imm(U(0)))
              } otherwise {                                           // MOV rd, pc: PC + 4
                out.seq(auipc(reg(rdn)), addi(reg(rdn), reg(rdn), imm(U(4))))
              }
            }
            is(B"11") {                          // BX rm, BLX rm (bits 2:0 must be 0)
              when(hw(2 downto 0) === 0) {
                when(rm =/= pc) { out := jalr(hw(7) ? RA | X0, reg(rm)) }
                  .otherwise { out.seq(auipc(T1), addi(T1, T1, imm(U(4))), jalr(hw(7) ? RA | X0, T1)) }
              }
            }
          }
        }
      }
      is(B"01001") { out.seq(auipc(T1), lw(r108, T1, imm(literal))) }   // LDR rt, [pc, #imm8*4]

      // --- Loads and stores, register offset: 0101 ooo mmm nnn ttt -------------
      is(B"01010", B"01011") {
        val address = add(T1, r53, r86)
        val zero = imm(U(0))
        switch(hw(11 downto 9)) {
          is(B"000") { out.seq(address, sw(r20, T1, zero)) }   // STR
          is(B"001") { out.seq(address, sh(r20, T1, zero)) }   // STRH
          is(B"010") { out.seq(address, sb(r20, T1, zero)) }   // STRB
          is(B"011") { out.seq(address, lb(r20, T1, zero)) }   // LDRSB
          is(B"100") { out.seq(address, lw(r20, T1, zero)) }   // LDR
          is(B"101") { out.seq(address, lhu(r20, T1, zero)) }  // LDRH
          is(B"110") { out.seq(address, lbu(r20, T1, zero)) }  // LDRB
          is(B"111") { out.seq(address, lh(r20, T1, zero)) }   // LDRSH
        }
      }

      // --- Loads and stores, immediate offset: ooooo iiiii nnn ttt -----------
      is(B"01100") { out := sw(r20, r53, imm(imm5 << 2)) }     // STR
      is(B"01101") { out := lw(r20, r53, imm(imm5 << 2)) }     // LDR
      is(B"01110") { out := sb(r20, r53, imm(imm5)) }          // STRB
      is(B"01111") { out := lbu(r20, r53, imm(imm5)) }         // LDRB
      is(B"10000") { out := sh(r20, r53, imm(imm5 << 1)) }     // STRH
      is(B"10001") { out := lhu(r20, r53, imm(imm5 << 1)) }    // LDRH
      is(B"10010") { out := sw(r108, SP, imm(imm8 << 2)) }     // STR rt, [sp, #imm8*4]
      is(B"10011") { out := lw(r108, SP, imm(imm8 << 2)) }     // LDR rt, [sp, #imm8*4]

      // --- Address generation and stack adjustment ----------------------------
      is(B"10100") { out.seq(auipc(r108), addi(r108, r108, imm(literal))) }   // ADR rd, #imm8*4
      is(B"10101") { out := addi(r108, SP, imm(imm8 << 2)) }   // ADD rd, sp, #imm8*4

      is(B"10110") {
        when(hw(10 downto 8) === B"000") {                     // ADD/SUB sp, sp, #imm7*4
          out := addi(SP, SP, hw(7) ? negImm(imm7 << 2) | imm(imm7 << 2))
        }
        switch(hw(10 downto 6)) {                              // the extends
          is(B"01000") { out.seq(slli(r20, r53, U(16)), srai(r20, r20, U(16))) }   // SXTH
          is(B"01001") { out.seq(slli(r20, r53, U(24)), srai(r20, r20, U(24))) }   // SXTB
          is(B"01010") { out.seq(slli(r20, r53, U(16)), srli(r20, r20, U(16))) }   // UXTH
          is(B"01011") { out := andi(r20, r53, B"x0FF") }                           // UXTB
        }
        when(hw(10 downto 9) === B"10") {                      // PUSH {list, lr?}
          // Store the registers below SP, lowest first, then move SP: n + 1 ops.
          val list = hw(8 downto 0)                            // bit 8: LR
          val n = count(list)
          val index = nth(list, step)
          val store = sw((index === 8) ? RA | reg(index.asBits), SP,
                         ((step.resize(12) - n.resize(12)) |<< 2).asBits)   // (k - n) * 4
          when(n === 0) { out := NOP }                         // UNPREDICTABLE
            .otherwise { out.at((step === n) ? addi(SP, SP, negImm(n.resize(10) << 2)) | store, step === n) }
        }
        when(hw === B"xB672") { out := CSRRCI_MSTATUS_MIE }    // CPSID i
        when(hw === B"xB662") { out := CSRRSI_MSTATUS_MIE }    // CPSIE i
      }
      is(B"10111") {
        when(hw(10 downto 9) === B"10") {                      // POP {list, pc?}
          // Load the registers from SP up, lowest first, then move SP. With PC:
          // its word into T1, SP, then the jump, last.
          val list = imm8.asBits
          val withPc = hw(8)
          val m = count(list)                                  // registers other than the PC
          val n = m + withPc.asUInt.resize(4)
          val load = lw(reg(nth(list, step).asBits), SP, words(step))
          val tail = cloneOf(load)
          tail := addi(SP, SP, words(n))
          when(withPc) {
            when(step === m) { tail := lw(T1, SP, words(m)) }
            when(step === m + 2) { tail := jalr(X0, T1) }
          }
          when(n === 0) { out := NOP }                         // UNPREDICTABLE
            .otherwise {
              out.at((step < m) ? load | tail, step === (withPc ? (m + 2) | m))
            }
        }
        when(hw(10 downto 8) === B"110") { out := EBREAK }     // BKPT
        when(hw(10 downto 8) === B"111" && hw(3 downto 0) === 0) {
          switch(hw(7 downto 4)) {
            is(B"0000", B"0001", B"0010", B"0100") { out := NOP }   // NOP, YIELD, WFE (Q5), SEV
            is(B"0011") { out := WFI }
          }
        }
        when(hw(10 downto 8) === B"010") {                     // byte reversal: rd, rm
          switch(hw(7 downto 6)) {
            is(B"00") {                                        // REV
              out.seq(srli(T1, r53, U(24)), slli(T2, r53, U(24)), or(T1, T1, T2),
                      lui(T3, B"x00010"), addi(T3, T3, B"xF00"),            // T3 = 0x0000FF00
                      srli(T2, r53, U(8)), and(T2, T2, T3), or(T1, T1, T2),
                      and(T2, r53, T3), slli(T2, T2, U(8)), or(r20, T1, T2))
            }
            is(B"01") {                                        // REV16
              out.seq(lui(T3, B"x00FF0"), addi(T3, T3, B"x0FF"),            // T3 = 0x00FF00FF
                      srli(T1, r53, U(8)), and(T1, T1, T3), and(T2, r53, T3),
                      slli(T2, T2, U(8)), or(r20, T1, T2))
            }
            is(B"11") {                                        // REVSH
              out.seq(slli(T1, r53, U(24)), srai(T1, T1, U(16)), srli(T2, r53, U(8)),
                      andi(T2, T2, B"x0FF"), or(r20, T1, T2))
            }
          }
        }
      }

      // --- Load and store multiple: ooooo nnn rrrrrrrr ------------------------
      is(B"11000") {                                           // STM rn!, {list}
        // Store from rn up, lowest first, then write rn back: n + 1 ops.
        val list = imm8.asBits
        val n = count(list)
        val store = sw(reg(nth(list, step).asBits), r108, words(step))
        when(n === 0) { out := NOP }                           // UNPREDICTABLE
          .otherwise { out.at((step === n) ? addi(r108, r108, words(n)) | store, step === n) }
      }
      is(B"11001") {                                           // LDM rn!, {list} / LDM rn, {list}
        // Load from rn up, each register from its own slot. With rn in the
        // list there's no write-back, and rn is loaded last, so a fault
        // part-way through leaves it intact for the restart.
        val list = imm8.asBits
        val base = hw(10 downto 8).asUInt
        val n = count(list)
        val inList = list(base)
        val others = list & ~(B(1, 8 bits) |<< base)
        val index = UInt(4 bits)
        index := nth(others, step)
        when(inList && step === n - 1) { index := base.resize(4) }
        val load = lw(reg(index.asBits), r108, words(rank(list, index)))
        when(n === 0) { out := NOP }                           // UNPREDICTABLE
          .elsewhen(inList) { out.at(load, step === n - 1) }
          .otherwise { out.at((step === n) ? addi(r108, r108, words(n)) | load, step === n) }
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
    out.result
  }

  private def expand32(hw1: Bits, hw2: Bits, step: UInt): ThumbOp = {
    val out = new Ops(step)

    // BL: 11110 s iiiiiiiiii, 11 j 1 k iiiiiiiiiii. Beyond jal's +-1 MiB: two ops.
    when(hw1(15 downto 11) === B"11110" && hw2(15 downto 14) === B"11" && hw2(12)) {
      val s = hw1(10)
      val i1 = !(hw2(13) ^ s)
      val i2 = !(hw2(11) ^ s)
      val offset = (s ## i1 ## i2 ## hw1(9 downto 0) ## hw2(10 downto 0) ## B"0").asSInt
      val off = offset.resize(26) + 4
      val top = off(25 downto 20).asBits
      when(top === 0 || top.andR) {
        out := jal(RA, off(20 downto 0).asBits)
      } otherwise {                                // auipc + jalr: +-16 MiB
        val hi = (off + 0x800)(25 downto 12)       // (off + 0x800) >> 12, signed
        out.seq(auipc(T1, hi.resize(20).asBits), jalr(RA, T1, off(11 downto 0).asBits))
      }
    }
    // DSB, DMB, ISB: 1111001110111111, 1000111101oo oooo (any option).
    when(hw1 === B"xF3BF") {
      switch(hw2(15 downto 4)) {
        is(B"x8F4", B"x8F5") { out := FENCE }
        is(B"x8F6") { out := FENCE_I }
      }
    }
    // MSR, MRS: PRIMASK inline, through mstatus.MIE (PRIMASK = 1 masks, so
    // MIE = NOT PRIMASK). The APSR is illegal without a flags unit; the other
    // special registers, and SP or PC as the operand, trap to the handler.
    val mstatus = 0x300
    when(hw1(15 downto 4) === B"xF38" && hw2(15 downto 8) === B"x88") {     // MSR spec_reg, rn
      val n = hw1(3 downto 0)
      when(hw2(7 downto 0) === 16 && n =/= 13 && n =/= 15) {
        out.seq(andi(T1, reg(n), B"x001"), xori(T1, T1, B"x001"), slli(T1, T1, U(3)),
                CSRRCI_MSTATUS_MIE, csrrs(X0, mstatus, T1))
      }
    }
    when(hw1 === B"xF3EF" && hw2(15 downto 12) === B"1000") {               // MRS rd, spec_reg
      val d = hw2(11 downto 8)
      when(hw2(7 downto 0) === 16 && d =/= 13 && d =/= 15) {
        out.seq(csrrs(T1, mstatus, X0), srli(T1, T1, U(3)), andi(T1, T1, B"x001"), xori(reg(d), T1, B"x001"))
      }
    }
    out.result
  }
}

/** The expander alone, for the exhaustive check against the model
  * (sim/expander_tb.sv, tests/test_expander_rtl.py). The core uses
  * Thumb.expand directly, in the fetcher. */
class ThumbExpander extends Component {
  val io = new Bundle {
    val hw1 = in Bits(16 bits)
    val hw2 = in Bits(16 bits)
    val pc1 = in Bool()
    val step = in UInt(4 bits)
    val op = out Bits(40 bits)    // side-band ## op, as the model's ops
    val last = out Bool()
  }
  val result = Thumb.expand(io.hw1, io.hw2, io.pc1, io.step)
  io.op := result.side ## result.op
  io.last := result.last
}
