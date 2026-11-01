# Build Thumb-V for the CYC1000 with a program in its RAMs:
#   cd build/board && quartus_sh -t ../../rtl/board/build.tcl
# The program is code.mem and data.mem in the current directory
# (python -m thumbv.board writes them). Outputs thumbv.sof and thumbv.svf, the
# JTAG sequence openFPGALoader loads (it reports success on an .rbf without
# configuring the 10CL025).

load_package flow

set here [file dirname [file normalize [info script]]]
set repo [file normalize $here/../..]
set out  [pwd]

project_new thumbv -overwrite
set_global_assignment -name FAMILY "Cyclone 10 LP"
set_global_assignment -name DEVICE 10CL025YU256C8G
set_global_assignment -name TOP_LEVEL_ENTITY cyc1000_top
set_global_assignment -name VERILOG_INPUT_VERSION SYSTEMVERILOG_2005
set_global_assignment -name VERILOG_FILE $repo/build/rtl/VexRiscv.v
foreach f [lsort [glob $repo/rtl/soc/*.v]] {
    set_global_assignment -name VERILOG_FILE $f
}
set_global_assignment -name VERILOG_FILE $here/cyc1000_top.v
set_global_assignment -name SDC_FILE $here/cyc1000.sdc
set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"
source $here/pins.tcl
set_parameter -name CODE_INIT $out/code.mem
set_parameter -name DATA_INIT $out/data.mem

execute_flow -compile
project_close

exec [file dirname [info nameofexecutable]]/quartus_cpf -c -q 6MHz -g 3.3 -n p thumbv.sof thumbv.svf
