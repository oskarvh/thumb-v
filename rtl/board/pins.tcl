# CYC1000 pin assignments (Trenz TEI0003 schematic and the Arrow CYC1000 user guide).
set_location_assignment PIN_M2 -to CLK12M
set_location_assignment PIN_N6 -to USER_BTN
set_location_assignment PIN_T7 -to UART_TX
set_location_assignment PIN_R7 -to UART_RX
set_location_assignment PIN_M6 -to LED[0]
set_location_assignment PIN_T4 -to LED[1]
set_location_assignment PIN_T3 -to LED[2]
set_location_assignment PIN_R3 -to LED[3]
set_location_assignment PIN_T2 -to LED[4]
set_location_assignment PIN_R4 -to LED[5]
set_location_assignment PIN_N5 -to LED[6]
set_location_assignment PIN_N3 -to LED[7]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to *
# The button switches to ground and has no pull-up on the board.
set_instance_assignment -name WEAK_PULL_UP_RESISTOR ON -to USER_BTN
