// Thumb-V's copy of VexRiscv's simple instruction bus plugin (decision D5).
//
// Copied from VexRiscv baf7dc82 (third_party/VexRiscv), src/main/scala/vexriscv/plugin/IBusSimplePlugin.scala:
// only the plugin class, renamed ThumbIBusSimplePlugin and built on
// ThumbFetcherImpl. The bus definitions (IBusSimpleBus and friends) are used
// from upstream. Every Thumb-V change is marked THUMBV.

package thumbv

import vexriscv._
import vexriscv.plugin._
import spinal.core._
import spinal.lib._
import vexriscv.Riscv.{FENCE, FENCE_I}

class ThumbIBusSimplePlugin(    resetVector : BigInt,
                       val cmdForkOnSecondStage : Boolean,
                       val cmdForkPersistence : Boolean,
                       val catchAccessFault : Boolean = false,
                           prediction : BranchPrediction = NONE,
                           historyRamSizeLog2 : Int = 10,
                           keepPcPlus4 : Boolean = false,
                           compressedGen : Boolean = false,
                       val busLatencyMin : Int = 1,
                       val pendingMax : Int = 7,
                           injectorStage : Boolean = true,
                       val rspHoldValue : Boolean = false,
                       val singleInstructionPipeline : Boolean = false,
                       val memoryTranslatorPortConfig : Any = null,
                           relaxPredictorAddress : Boolean = true,
                           predictionBuffer : Boolean = true,
                           bigEndian : Boolean = false,
                           vecRspBuffer : Boolean = false
                      ) extends ThumbFetcherImpl(
    resetVector = resetVector,
    keepPcPlus4 = keepPcPlus4,
    decodePcGen = compressedGen,
    compressedGen = compressedGen,
    cmdToRspStageCount = busLatencyMin + (if(cmdForkOnSecondStage) 1 else 0),
    allowPcRegReusedForSecondStage = !(cmdForkOnSecondStage && cmdForkPersistence),
    injectorReadyCutGen = false,
    prediction = prediction,
    historyRamSizeLog2 = historyRamSizeLog2,
    injectorStage = injectorStage,
    relaxPredictorAddress = relaxPredictorAddress,
    fetchRedoGen = memoryTranslatorPortConfig != null,
  predictionBuffer = predictionBuffer){

  var iBus : IBusSimpleBus = null
  var decodeExceptionPort : Flow[ExceptionCause] = null
  val catchSomething = memoryTranslatorPortConfig != null || catchAccessFault
  var mmuBus : MemoryTranslatorBus = null

//  if(rspHoldValue) assert(busLatencyMin <= 1)
  assert(!rspHoldValue, "rspHoldValue not supported yet")
  assert(!singleInstructionPipeline)

  override def setup(pipeline: VexRiscv): Unit = {
    super.setup(pipeline)
    // THUMBV: IBusSimpleBus takes the upstream plugin type, used only by its bus
    // adapters (toAxi4ReadOnly, ...), which the SoC doesn't use.
    iBus = master(IBusSimpleBus(null)).setName("iBus")

    val decoderService = pipeline.service(classOf[DecoderService])
    decoderService.add(FENCE_I, Nil)

    if(catchSomething) {
      decodeExceptionPort = pipeline.service(classOf[ExceptionService]).newExceptionPort(pipeline.decode,1)
    }

    if(memoryTranslatorPortConfig != null) {
      mmuBus = pipeline.service(classOf[MemoryTranslator]).newTranslationPort(MemoryTranslatorPort.PRIORITY_INSTRUCTION, memoryTranslatorPortConfig)
    }
  }

  override def build(pipeline: VexRiscv): Unit = {
    import pipeline._
    import pipeline.config._

    pipeline plug new FetchArea(pipeline) {
      var cmd = Stream(IBusSimpleCmd())
      val cmdWithS2mPipe = cmdForkPersistence && (!cmdForkOnSecondStage || mmuBus != null)
      iBus.cmd << (if(cmdWithS2mPipe) cmd.s2mPipe() else cmd)

      //Avoid sending to many iBus cmd
      val pending = new Area{
        val inc, dec = Bool()
        val value = Reg(UInt(log2Up(pendingMax + 1) bits)) init (0)
        val next = value + U(inc) - U(dec)
        value := next
      }

      val secondStagePersistence = cmdForkPersistence && cmdForkOnSecondStage && !cmdWithS2mPipe
      def cmdForkStage = if(!secondStagePersistence) iBusRsp.stages(if(cmdForkOnSecondStage) 1 else 0) else iBusRsp.stages(1)

      val cmdFork = if(!secondStagePersistence) new Area {
        //This implementation keep the cmd on the bus until it's executed or the the pipeline is flushed
        def stage = cmdForkStage
        val canEmit = stage.output.ready && pending.value =/= pendingMax
        stage.halt setWhen(stage.input.valid && (!canEmit || !cmd.ready))
        cmd.valid := stage.input.valid && canEmit
        pending.inc := cmd.fire
      } else new Area{
        //This implementation keep the cmd on the bus until it's executed, even if the pipeline is flushed
        def stage = cmdForkStage
        val pendingFull = pending.value === pendingMax
        val enterTheMarket = Bool()
        val cmdKeep = RegInit(False) setWhen(enterTheMarket) clearWhen(cmd.ready)
        val cmdFired = RegInit(False) setWhen(cmd.fire) clearWhen(stage.input.ready)
        enterTheMarket := stage.input.valid && !pendingFull && !cmdFired && !cmdKeep
//        stage.halt setWhen(cmd.isStall || (pendingFull && !cmdFired)) //(cmd.isStall)
        stage.halt setWhen(pendingFull && !cmdFired && !cmdKeep)
        stage.halt setWhen(!cmd.ready && !cmdFired)
        cmd.valid := enterTheMarket || cmdKeep
        pending.inc := enterTheMarket
      }

      val mmu = (mmuBus != null) generate new Area {
        mmuBus.cmd.last.isValid := cmdForkStage.input.valid
        mmuBus.cmd.last.virtualAddress := cmdForkStage.input.payload
        mmuBus.cmd.last.bypassTranslation := False
        mmuBus.end := cmdForkStage.output.fire || externalFlush

        cmd.pc := mmuBus.rsp.physicalAddress(31 downto 2) @@ U"00"

        //do not emit memory request if MMU had issues
        when(cmdForkStage.input.valid) {
          when(mmuBus.rsp.refilling) {
            cmdForkStage.halt := True
            cmd.valid := False
          }
          when(mmuBus.rsp.exception) {
            cmdForkStage.halt := False
            cmd.valid := False
          }
        }

        val joinCtx = stageXToIBusRsp(cmdForkStage, mmuBus.rsp)
      }

      val mmuLess = (mmuBus == null) generate new Area{
        cmd.pc := cmdForkStage.input.payload(31 downto 2) @@ U"00"
      }

      val rspJoin = new Area {
        import iBusRsp._
        //Manage flush for iBus transactions in flight
        val rspBuffer = new Area {
          val output = Stream(IBusSimpleRsp())
          val c = new StreamFifoLowLatency(IBusSimpleRsp(), busLatencyMin + (if(cmdForkOnSecondStage && cmdForkPersistence) 1 else 0), useVec = vecRspBuffer)
          val discardCounter = Reg(UInt(log2Up(pendingMax + 1) bits)) init (0)
          discardCounter := discardCounter - (c.io.pop.valid && discardCounter =/= 0).asUInt
          when(iBusRsp.flush) {
            discardCounter := (if(cmdForkOnSecondStage) pending.next else pending.value - U(pending.dec))
          }

          c.io.push << iBus.rsp.toStream
//          if(compressedGen) c.io.flush setWhen(decompressor.consumeCurrent)
//          if(!compressedGen && isDrivingDecode(IBUS_RSP)) c.io.flush setWhen(decode.arbitration.flushNext && iBusRsp.output.ready)
          val flush = discardCounter =/= 0 || iBusRsp.flush
          output.valid := c.io.pop.valid && discardCounter === 0
          output.payload := c.io.pop.payload
          c.io.pop.ready := output.ready || flush

          pending.dec := c.io.pop.fire // iBus.rsp.valid && flush || c.io.pop.valid && output.ready instead to avoid unecessary dependancies ?
        }

        val fetchRsp = FetchRsp()
        fetchRsp.isRvc := False
        fetchRsp.thumb := False                        // THUMBV: set by the decompressor
        fetchRsp.raw := rspBuffer.output.payload.inst  // THUMBV
        fetchRsp.pc := stages.last.output.payload
        fetchRsp.rsp := rspBuffer.output.payload
        fetchRsp.rsp.error.clearWhen(!rspBuffer.output.valid) //Avoid interference with instruction injection from the debug plugin
        if(bigEndian){
          // instructions are stored in little endian byteorder
          fetchRsp.rsp.inst.allowOverride
          fetchRsp.rsp.inst := EndiannessSwap(rspBuffer.output.payload.inst)
        }

        val join = Stream(FetchRsp())
        val exceptionDetected = False
        join.valid := stages.last.output.valid && rspBuffer.output.valid
        join.payload := fetchRsp
        stages.last.output.ready := stages.last.output.valid ? join.fire | join.ready
        rspBuffer.output.ready := join.fire
        output << join.haltWhen(exceptionDetected)

        if(memoryTranslatorPortConfig != null){
          when(stages.last.input.valid && mmu.joinCtx.refilling) {
            iBusRsp.redoFetch := True
          }
        }


        if(catchSomething){
          decodeExceptionPort.code.assignDontCare()
          decodeExceptionPort.badAddr := join.pc(31 downto 2) @@ U"00"

          if(catchAccessFault) when(join.valid && join.rsp.error){
            decodeExceptionPort.code  := 1
            exceptionDetected := True
          }
          if(memoryTranslatorPortConfig != null) {
            val privilegeService = pipeline.serviceElse(classOf[PrivilegeService], PrivilegeServiceDefault())
            when(stages.last.input.valid && !mmu.joinCtx.refilling && (mmu.joinCtx.exception || !mmu.joinCtx.allowExecute)){
              decodeExceptionPort.code  := 12
              exceptionDetected := True
            }
          }
          decodeExceptionPort.valid  :=  exceptionDetected && iBusRsp.readyForError
        }
      }
    }
  }
}
