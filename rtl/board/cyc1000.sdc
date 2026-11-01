create_clock -name clk12 -period 83.333 [get_ports CLK12M]
derive_clock_uncertainty

# Asynchronous or slow board I/O: the button is synchronised, the UART and the
# LEDs are far slower than the clock.
set_false_path -from [get_ports {USER_BTN UART_RX}]
set_false_path -to [get_ports {UART_TX LED[*]}]
