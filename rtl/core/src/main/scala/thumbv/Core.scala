package thumbv

import spinal.core._
import vexriscv.plugin._
import vexriscv.{VexRiscv, VexRiscvConfig, plugin}

/** The stock VexRiscv configuration Thumb-V starts from (Phase 1.1).
  *
  * RV32IMC, machine mode only, no MMU, no caches, simple instruction and data
  * buses. Chosen to match the software model (thumbv.machine) and to keep the
  * fetch path easy to patch later:
  *  - C: the Thumb expander goes where the RVC decompressor is, and Thumb
  *    shares RVC's 2-byte fetch granularity.
  *  - Traps on illegal instructions, misaligned accesses and ecall/ebreak,
  *    like the model: the expander emits an illegal instruction for UDF and
  *    unhandled MRS/MSR, and the trap handler emulates them.
  *  - mstatus.MIE is PRIMASK (CPSID/CPSIE), so mstatus, mtvec, mepc, mcause
  *    and mtval are all accessible.
  *  - An RVFI retire trace port (FormalPlugin), which the simulation
  *    testbench logs to lockstep the core against the model. Synthesis
  *    prunes it when it isn't connected.
  */
object Core {
  def plugins(resetVector: BigInt, mtvec: BigInt) = List(
    new ThumbIBusSimplePlugin(
      resetVector = resetVector,
      cmdForkOnSecondStage = false,
      cmdForkPersistence = false,
      prediction = NONE,
      catchAccessFault = true,
      compressedGen = true
    ),
    new DBusSimplePlugin(
      catchAddressMisaligned = true,
      catchAccessFault = true
    ),
    new CsrPlugin(CsrPluginConfig(
      catchIllegalAccess = true,
      mvendorid = null,
      marchid = null,
      mimpid = null,
      mhartid = 0,
      misaExtensionsInit = (1 << 8) | (1 << 12) | (1 << 2),   // I, M, C
      misaAccess = CsrAccess.READ_ONLY,
      mtvecAccess = CsrAccess.READ_WRITE,
      mtvecInit = mtvec,
      mepcAccess = CsrAccess.READ_WRITE,
      mscratchGen = true,
      mcauseAccess = CsrAccess.READ_WRITE,
      mbadaddrAccess = CsrAccess.READ_WRITE,
      mcycleAccess = CsrAccess.READ_ONLY,
      minstretAccess = CsrAccess.READ_ONLY,
      ucycleAccess = CsrAccess.NONE,
      ecallGen = true,
      ebreakGen = true,
      wfiGenAsWait = true
    )),
    new DecoderSimplePlugin(
      catchIllegalInstruction = true
    ),
    new RegFilePlugin(
      regFileReadyKind = plugin.SYNC,   // maps to M9K block RAM
      zeroBoot = false
    ),
    new IntAluPlugin,
    new SrcPlugin(
      separatedAddSub = false,
      executeInsertion = true
    ),
    new FullBarrelShifterPlugin,
    new MulPlugin,                      // Cyclone 10 LP has 18x18 multipliers
    new DivPlugin,                      // iterative, one bit per cycle
    new HazardSimplePlugin(
      bypassExecute = true,
      bypassMemory = true,
      bypassWriteBack = true,
      bypassWriteBackBuffer = true,
      pessimisticUseSrc = false,
      pessimisticWriteRegFile = false,
      pessimisticAddressMatch = false
    ),
    new BranchPlugin(
      earlyBranch = false,
      catchAddressMisaligned = true,
      fenceiGenAsAJump = true           // no instruction cache: fence.i (ISB) just refetches
    ),
    new ThumbRegionPlugin,             // Thumb region CSRs 0x7C0-0x7C3 (D7)
    new FormalPlugin
  )

  // The reset vector is where tests/link/rv32.ld puts _start; mtvec is a
  // placeholder until there is a trap handler (programs may set their own).
  def apply(resetVector: BigInt = 0x00020000L, mtvec: BigInt = 0x00000020L) =
    new VexRiscv(VexRiscvConfig(plugins = plugins(resetVector, mtvec)))
}

/** sbt "runMain thumbv.GenCore <output directory>": the core (VexRiscv.v) and,
  * for the exhaustive check against the model, the expander alone
  * (ThumbExpander.v). */
object GenCore extends App {
  val out = if (args.nonEmpty) args(0) else "."
  SpinalConfig(targetDirectory = out).generateVerilog(Core())
  SpinalConfig(targetDirectory = out).generateVerilog(new ThumbExpander)
}
