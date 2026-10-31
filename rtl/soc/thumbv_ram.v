// Dual-port RAM with synchronous reads: port A reads, port B reads and
// writes with byte enables. Written so that Quartus infers M9K blocks.

module thumbv_ram #(
    parameter WORDS = 1024
) (
    input  wire                     clk,
    input  wire [$clog2(WORDS)-1:0] a_addr,
    output reg  [31:0]              a_rdata,
    input  wire [$clog2(WORDS)-1:0] b_addr,
    input  wire [3:0]               b_we,
    input  wire [31:0]              b_wdata,
    output reg  [31:0]              b_rdata
);
    reg [31:0] mem [0:WORDS-1];

    always @(posedge clk)
        a_rdata <= mem[a_addr];

    integer i;
    always @(posedge clk) begin
        for (i = 0; i < 4; i = i + 1)
            if (b_we[i])
                mem[b_addr][8*i +: 8] <= b_wdata[8*i +: 8];
        b_rdata <= mem[b_addr];
    end
endmodule
