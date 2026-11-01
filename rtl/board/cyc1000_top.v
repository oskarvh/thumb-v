// Thumb-V on the Trenz CYC1000 (Cyclone 10 LP 10CL025YU256C8G).
//
// The SoC runs directly from the 12 MHz oscillator. Its RAMs are smaller than
// in simulation (32 KiB code, 16 KiB data) and alias through their regions,
// so the same programs run as long as their parts don't collide; the program
// is built into the RAMs' initial contents (CODE_INIT, DATA_INIT).
//
// Reset: for 1.4 s after configuration, and while the user button is held.
// The delay is for the host: loading the FPGA resets the FT2232H, whose serial
// port then takes a moment to come back, and the program's first output would
// be lost.

module cyc1000_top #(
    parameter CODE_INIT = "",
    parameter DATA_INIT = ""
) (
    input  wire       CLK12M,
    input  wire       USER_BTN,   // active low
    output wire       UART_TX,    // to the FT2232H's channel B (BDBUS1)
    input  wire       UART_RX,    // from the FT2232H (BDBUS0), unused for now
    output wire [7:0] LED         // active high
);
    // Reset for 2^24 cycles after configuration, then the button, synchronised.
    reg [23:0] por = 24'd0;
    reg [1:0]  btn = 2'b00;
    reg        reset = 1'b1;

    always @(posedge CLK12M) begin
        if (!(&por))
            por <= por + 24'd1;
        btn   <= {btn[0], USER_BTN};
        reset <= !(&por) || !btn[1];
    end

    thumbv_soc #(
        .CODE_WORDS        (8192),
        .DATA_WORDS        (4096),
        .UART_CLKS_PER_BIT (104),        // 12 MHz / 104 = 115384 baud, 0.2% fast
        .CODE_INIT         (CODE_INIT),
        .DATA_INIT         (DATA_INIT)
    ) soc (
        .clk     (CLK12M),
        .reset   (reset),
        .uart_tx (UART_TX),
        .leds    (LED)
    );
endmodule
