// UART transmitter: 8 data bits, no parity, 1 stop bit.

module thumbv_uart_tx #(
    parameter CLKS_PER_BIT = 104
) (
    input  wire       clk,
    input  wire       reset,
    input  wire       valid,   // start sending `data` (ignored while busy)
    input  wire [7:0] data,
    output wire       busy,
    output wire       tx
);
    reg [9:0]  shift;          // stop bit, data (LSB first), start bit
    reg [3:0]  bits_left;
    /* verilator lint_off WIDTHTRUNC */
    localparam [$clog2(CLKS_PER_BIT)-1:0] LAST = CLKS_PER_BIT - 1;
    /* verilator lint_on WIDTHTRUNC */
    reg [$clog2(CLKS_PER_BIT)-1:0] count;

    assign busy = bits_left != 0;
    assign tx   = busy ? shift[0] : 1'b1;

    always @(posedge clk) begin
        if (reset) begin
            bits_left <= 0;
        end else if (!busy) begin
            if (valid) begin
                shift     <= {1'b1, data, 1'b0};
                bits_left <= 10;
                count     <= 0;
            end
        end else if (count == LAST) begin
            shift     <= shift >> 1;
            bits_left <= bits_left - 1;
            count     <= 0;
        end else begin
            count <= count + 1;
        end
    end
endmodule
