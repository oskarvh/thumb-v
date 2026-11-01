package thumbv

import spinal.core._
import vexriscv._
import vexriscv.plugin._

/** The Thumb region CSRs (decision D7): instructions fetched from a region
  * decode as Thumb.
  *
  *   0x7C0 base0   0x7C1 limit0   0x7C2 base1   0x7C3 limit1
  *
  * Region i is [base_i, limit_i), empty when base >= limit. Custom machine-mode
  * read/write CSRs, word-aligned: the low two bits read as zero, so both
  * halves of a fetched word are always in the same mode. All reset to zero.
  * Instructions already fetched were decoded in the old mode, so software
  * follows a write with fence.i. The model (thumbv.machine, region_csrs) is
  * the reference.
  */
class ThumbRegionPlugin(val regions: Int = 2, val csrBase: Int = 0x7C0) extends Plugin[VexRiscv] {
  var bases, limits: Seq[UInt] = null

  override def setup(pipeline: VexRiscv): Unit = {
    // Created in setup, so that the fetcher can use them whatever the build order.
    bases = for (i <- 0 until regions) yield Reg(UInt(30 bits)).init(0).setName(s"ThumbRegion_base$i")
    limits = for (i <- 0 until regions) yield Reg(UInt(30 bits)).init(0).setName(s"ThumbRegion_limit$i")
  }

  override def build(pipeline: VexRiscv): Unit = {
    val csr = pipeline.service(classOf[CsrInterface])
    for (i <- 0 until regions) {
      csr.rw(csrBase + 2 * i, 2, bases(i))
      csr.rw(csrBase + 2 * i + 1, 2, limits(i))
    }
  }

  /** True when `pc` is in a Thumb region. */
  def inThumb(pc: UInt): Bool = {
    val word = pc(31 downto 2)
    (0 until regions).map(i => bases(i) <= word && word < limits(i)).reduce(_ || _)
  }
}
