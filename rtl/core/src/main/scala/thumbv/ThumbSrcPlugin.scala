// Thumb-V: a copy of VexRiscv's SrcPlugin (third_party/VexRiscv/src/main/
// scala/vexriscv/plugin/SrcPlugin.scala), with Thumb-V's changes marked
// THUMBV. The stock adder's carry-in is a constant, and the flags unit needs
// it to be C for ADCS/SBCS (Phase 4, docs/plan.md). Nothing in VexRiscv looks
// SrcPlugin up by class, so the copy replaces it in Core.plugins.
package thumbv

import vexriscv._
import vexriscv.plugin._
import spinal.core._
import spinal.lib.KeepAttribute


class ThumbSrcPlugin(separatedAddSub : Boolean = false, executeInsertion : Boolean = false, decodeAddSub : Boolean = false) extends Plugin[VexRiscv]{
  object SRC2_FORCE_ZERO extends Stageable(Bool)


  override def setup(pipeline: VexRiscv): Unit = {
    import pipeline.config._

    val decoderService = pipeline.service(classOf[DecoderService])
    decoderService.addDefault(SRC_ADD_ZERO, False) //TODO avoid this default to simplify decoding ?
  }

  override def build(pipeline: VexRiscv): Unit = {
    import pipeline._
    import pipeline.config._

    decode.insert(SRC2_FORCE_ZERO) := decode.input(SRC_ADD_ZERO) && !decode.input(SRC_USE_SUB_LESS)

    val insertionStage = if(executeInsertion) execute else decode
    insertionStage plug new Area{
      import insertionStage._

      val imm = Riscv.IMM(input(INSTRUCTION))
      insert(SRC1) := input(SRC1_CTRL).mux(
        Src1CtrlEnum.RS   -> output(RS1),
        Src1CtrlEnum.PC_INCREMENT -> (if(pipeline.config.withRvc) Mux(input(IS_RVC), B(2), B(4)) else B(4)).resized,
        Src1CtrlEnum.IMU  -> imm.u.resized,
        Src1CtrlEnum.URS1 -> input(INSTRUCTION)(Riscv.rs1Range).resized
      )
      insert(SRC2) := input(SRC2_CTRL).mux(
        Src2CtrlEnum.RS -> output(RS2),
        Src2CtrlEnum.IMI -> imm.i_sext.resized,
        Src2CtrlEnum.IMS -> imm.s_sext.resized,
        Src2CtrlEnum.PC -> output(PC).asBits
      )
    }

    val addSubStage = if(decodeAddSub) decode else execute
    if(separatedAddSub) {
      addSubStage plug new Area {
        import addSubStage._

        // ADD, SUB
        val add = (U(input(SRC1)) + U(input(SRC2))).asBits.addAttribute("keep")
        val sub = (U(input(SRC1)) - U(input(SRC2))).asBits.addAttribute("keep")
        when(input(SRC_ADD_ZERO)){ add := input(SRC1) }

        // SLT, SLTU
        val less = Mux(input(SRC1).msb === input(SRC2).msb, sub.msb,
          Mux(input(SRC_LESS_UNSIGNED), input(SRC2).msb, input(SRC1).msb))

        insert(SRC_ADD_SUB) := input(SRC_USE_SUB_LESS) ? sub | add
        insert(SRC_ADD) := add
        insert(SRC_SUB) := sub
        insert(SRC_LESS) := less
      }
    }else{
      addSubStage plug new Area {
        import addSubStage._

        // ADD, SUB
        // THUMBV: the flags kinds SUB and SBC make add/addi subtract, and ADC
        // and SBC take C as the carry-in (ThumbFlagsPlugin). Was:
        //   SRC1 + (SRC_USE_SUB_LESS ? ~SRC2 : SRC2) + (SRC_USE_SUB_LESS ? 1 : 0)
        val kind = input(ThumbFlagsPlugin.SIDE)(3 downto 0)
        val forceSub = kind === Flags.SUB || kind === Flags.SBC
        val withCarry = kind === Flags.ADC || kind === Flags.SBC
        val sub = input(SRC_USE_SUB_LESS) || forceSub
        val carryIn = withCarry ? pipeline.service(classOf[ThumbFlagsPlugin]).c | sub
        val addSub = (input(SRC1).asUInt + Mux(sub, ~input(SRC2), input(SRC2)).asUInt + carryIn.asUInt.resize(32)).asBits
        when(input(SRC2_FORCE_ZERO)){ addSub := input(SRC1) }


        // SLT, SLTU
        val less = Mux(input(SRC1).msb === input(SRC2).msb, addSub.msb,
          Mux(input(SRC_LESS_UNSIGNED), input(SRC2).msb, input(SRC1).msb))

        insert(SRC_ADD_SUB) := addSub
        insert(SRC_ADD) := addSub
        insert(SRC_SUB) := addSub
        insert(SRC_LESS) := less
      }
    }
  }
}
