// Dual-port RAM with synchronous reads: port A reads, port B reads and
// writes with byte enables. Written in the form Quartus recognises as a
// true dual-port M9K RAM with byte enables (a packed array of byte lanes),
// so it is SystemVerilog despite the .v name.
// INIT_FILE, if set, is a $readmemh image loaded at configuration (the board)
// or time zero (simulation, where the testbench can also load one).

module thumbv_ram #(
    parameter WORDS     = 1024,
    parameter INIT_FILE = ""
) (
    input  wire                     clk,
    input  wire [$clog2(WORDS)-1:0] a_addr,
    output reg  [31:0]              a_rdata,
    input  wire [$clog2(WORDS)-1:0] b_addr,
    input  wire [3:0]               b_we,
    input  wire [31:0]              b_wdata,
    output reg  [31:0]              b_rdata
);
    reg [3:0][7:0] mem [0:WORDS-1];

    initial
        if (INIT_FILE != "")
            $readmemh(INIT_FILE, mem);

    always @(posedge clk)
        a_rdata <= mem[a_addr];

    always @(posedge clk) begin
        if (b_we[0]) mem[b_addr][0] <= b_wdata[7:0];
        if (b_we[1]) mem[b_addr][1] <= b_wdata[15:8];
        if (b_we[2]) mem[b_addr][2] <= b_wdata[23:16];
        if (b_we[3]) mem[b_addr][3] <= b_wdata[31:24];
        b_rdata <= mem[b_addr];
    end
endmodule
