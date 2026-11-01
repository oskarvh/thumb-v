// Generates the Thumb-V core from VexRiscv (third_party/VexRiscv, a pinned submodule).
// Run from the repository root with `make core`; see docs/setup.md.

lazy val vexRiscv = RootProject(file("../../third_party/VexRiscv"))

lazy val core = (project in file("."))
  .dependsOn(vexRiscv)
  .settings(
    name := "thumbv-core",
    scalaVersion := "2.12.18",   // must match VexRiscv's
    fork := true,
    // SpinalHDL's compiler plugin, needed by any Scala code that builds hardware
    // (component scoping and naming); VexRiscv's own build uses it too.
    addCompilerPlugin("com.github.spinalhdl" %% "spinalhdl-idsl-plugin" % "1.13.0"),
  )
