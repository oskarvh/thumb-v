package thumbv

import spinal.core._
import vexriscv._
import vexriscv.plugin._

object ThumbFlagsPlugin {
  /** The flags side-band of each op, from the sequencer: condition (7:4),
    * kind (3:0, thumbv.Flags). Zero for RISC-V instructions. */
  object SIDE extends Stageable(Bits(8 bits))
  /** NZCV after the instruction, for the retire trace only. */
  object NZCV_AFTER extends Stageable(Bits(4 bits))
}

/** The hardware flags unit, strategy C (decision D1, docs/plan.md Phase 4).
  *
  * NZCV is a 4-bit register (N = 3, Z = 2, C = 1, V = 0), also CSR 0x7C4 in
  * bits 31:28 as in the APSR. Ops from the expander carry a flags kind; in
  * execute the unit computes the new flags:
  *  - from the adder's operand and result sign bits (ADD, SUB, ADC, SBC; the
  *    adder itself, with its carry-in, is in ThumbSrcPlugin);
  *  - from the shifter's operand for immediate shifts (SHL, SHR);
  *  - for N and Z of any shift op, from SHIFT_RIGHT, since the shifted
  *    result only reaches REGFILE_WRITE_DATA in memory;
  *  - from REGFILE_WRITE_DATA otherwise (NZ, CW).
  * It writes them when execute fires. Every flag read (the carry-in, CSR
  * reads, conditional branches: kind BRANCH overrides BRANCH_DO) is in
  * execute too, so a reader always sees
  * the writes of every older instruction, with no stall.
  *
  * The model (thumbv.machine, Machine._execute_flagged) is the reference.
  */
class ThumbFlagsPlugin(val csrAddress: Int = 0x7C4) extends Plugin[VexRiscv] {
  import ThumbFlagsPlugin._

  var nzcv: Bits = null
  def c: Bool = nzcv(1)

  override def setup(pipeline: VexRiscv): Unit = {
    // Created in setup, so that ThumbSrcPlugin can read C whatever the build order.
    nzcv = Reg(Bits(4 bits)).init(0).setName("ThumbFlags_nzcv")
  }

  override def build(pipeline: VexRiscv): Unit = {
    import pipeline._
    import pipeline.config._

    pipeline.service(classOf[CsrInterface]).rw(csrAddress, 28, nzcv)
    val shifter = pipeline.service(classOf[FullBarrelShifterPlugin])
    val branch = pipeline.service(classOf[BranchPlugin])

    execute plug new Area {
      import execute._
      val kind = input(SIDE)(3 downto 0)
      val src1 = input(SRC1)
      val src2 = input(SRC2)
      val result = output(REGFILE_WRITE_DATA)

      // The adder: rs1 + b + carry-in, where b is src2 or NOT src2.
      val subtract = kind === Flags.SUB || kind === Flags.SBC
      val a31 = src1.msb
      val b31 = src2.msb ^ subtract
      val r31 = input(SRC_ADD_SUB).msb
      val carry = (a31 && b31) || ((a31 || b31) && !r31)
      val overflow = a31 === b31 && r31 =/= a31

      // Immediate shifts: C is the last bit shifted out.
      val shamt = src2(4 downto 0).asUInt
      val left = kind === Flags.SHL
      val shiftCarry = src1((left ? (U(0, 5 bits) - shamt) | (shamt - 1)))
      // Any shift op's result (kind SHL, SHR, or NZ as on ASRS by a
      // register): the shifter writes it into REGFILE_WRITE_DATA only in
      // memory, so take it from SHIFT_RIGHT here.
      val shiftCtrl = input(shifter.SHIFT_CTRL)
      val isShift = shiftCtrl =/= shifter.ShiftCtrlEnum.DISABLE
      val shifted = (shiftCtrl === shifter.ShiftCtrlEnum.SLL) ? input(shifter.SHIFT_RIGHT).reversed | input(shifter.SHIFT_RIGHT)

      val shift = left || kind === Flags.SHR
      val arith = kind === Flags.ADD || kind === Flags.SUB || kind === Flags.ADC || kind === Flags.SBC
      val nzSource = isShift ? shifted | result
      val n = nzSource.msb
      val z = nzSource === 0

      val next = cloneOf(nzcv)
      next := nzcv
      when(kind === Flags.NZ || shift || arith) { next(3) := n; next(2) := z }
      when(arith) { next(1) := carry; next(0) := overflow }
      when(shift) { next(1) := shiftCarry }
      when(kind === Flags.CW && result(1)) { next(1) := result(0) }
      // Only for flag-writing kinds: a CSR write of NZCV has kind 0.
      when(arbitration.isFiring && (kind === Flags.NZ || shift || arith || kind === Flags.CW)) { nzcv := next }

      // B<cond>: an always-taken beq x0, x0 whose BRANCH_DO (decided here,
      // applied by BranchPlugin in memory) is the ARM condition on NZCV.
      val (fn, fz, fc, fv) = (nzcv(3), nzcv(2), nzcv(1), nzcv(0))
      val cond = input(SIDE)(7 downto 4)
      val holds = cond(3 downto 1).mux(
        0 -> fz,                    // EQ, NE
        1 -> fc,                    // CS, CC
        2 -> fn,                    // MI, PL
        3 -> fv,                    // VS, VC
        4 -> (fc && !fz),           // HI, LS
        5 -> (fn === fv),           // GE, LT
        6 -> (!fz && fn === fv),    // GT, LE
        7 -> True                   // AL: never emitted
      ) ^ cond(0)
      when(kind === Flags.BRANCH) { output(branch.BRANCH_DO) := holds }
    }

    // For the retire trace: in memory, the register holds the flags after
    // the instruction there (it left execute, the next hasn't yet).
    memory.insert(NZCV_AFTER) := nzcv
    val trace = out(Bits(4 bits)).setName("thumbNzcv")
    trace := writeBack.input(NZCV_AFTER)
  }
}
