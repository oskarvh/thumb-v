// Generates the Thumb-V core from VexRiscv (third_party/VexRiscv, a pinned submodule).
// Run from the repository root with `make core`; see docs/setup.md.

lazy val vexRiscv = RootProject(file("../../third_party/VexRiscv"))

lazy val core = (project in file("."))
  .dependsOn(vexRiscv)
  .settings(
    name := "thumbv-core",
    scalaVersion := "2.12.18",   // must match VexRiscv's
    fork := true,
  )
