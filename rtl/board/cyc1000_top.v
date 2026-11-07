// Thumb-V on the Trenz CYC1000 (Cyclone 10 LP 10CL025YU256C8G).
//
// The SoC runs directly from the 12 MHz oscillator. Its RAMs are smaller than
// in simulation (32 KiB code, 16 KiB data) and alias through their regions,
// so the same programs run as long as their parts don't collide; the program
// is built into the RAMs' initial contents (CODE_INIT, DATA_INIT).
//
// Reset: for 1.4 s after configuration. The delay is for the host: loading the FPGA resets the FT2232H, whose serial
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
    // Reset for 2^24 cycles after configuration.
    reg [23:0] por = 24'd0;
    reg        reset = 1'b1;

    always @(posedge CLK12M) begin
        if (!(&por))
            por <= por + 24'd1;
        reset <= !(&por);
    end

    // The user button, for software (0x1000_0010, interrupt line 1):
    // synchronised, and debounced: it changes once the pin has held its new
    // level for 2^16 cycles (5.5 ms).
    reg [1:0]  btn_sync = 2'b11;
    reg [15:0] btn_count = 16'd0;
    reg        button = 1'b0;            // 1 = held

    always @(posedge CLK12M) begin
        btn_sync <= {btn_sync[0], USER_BTN};
        if (!btn_sync[1] == button)
            btn_count <= 16'd0;
        else if (&btn_count)
            button <= !btn_sync[1];
        else
            btn_count <= btn_count + 16'd1;
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
        .irq       (32'b0),              // the SoC's own button drives line 1
        .button  (button),
        .uart_tx (UART_TX),
        .leds    (LED)
    );
endmodule
