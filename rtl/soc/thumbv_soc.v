// Thumb-V SoC: the core, on-chip RAM, a UART transmitter and LEDs.
//
// Memory map (matches the software model's layout, see model/thumbv/build.py):
//   0x0000_0000  code region, 256 KiB: the code RAM, CODE_WORDS words, for
//                instructions and read-only data, also readable and writable
//                as data (Thumb literal pools)
//   0x1000_0000  UART data   (write: send a byte)
//   0x1000_0004  UART status (bit 0: busy)
//   0x1000_0008  LEDs        (bits 7:0, read/write)
//   0x2000_0000  data region, 64 KiB: the data RAM, DATA_WORDS words
// A RAM smaller than its region repeats (aliases) through it, so the board's
// small RAMs run the same programs as long as their parts don't collide.
// Anything else gives an access fault: instruction fetches outside the code
// region, and loads from unmapped addresses (stores there are dropped).

module thumbv_soc #(
    parameter CODE_WORDS        = 65536,  // 256 KiB
    parameter DATA_WORDS        = 16384,  // 64 KiB
    parameter UART_CLKS_PER_BIT = 104,    // 12 MHz / 115200 baud
    parameter CODE_INIT         = "",     // $readmemh images, see thumbv_ram
    parameter DATA_INIT         = ""
) (
    input  wire       clk,
    input  wire       reset,              // synchronous, active high
    input  wire       irq_timer,          // the core's machine timer interrupt
    output wire       uart_tx,
    output reg  [7:0] leds
);
    localparam CODE_BITS = $clog2(CODE_WORDS);
    localparam DATA_BITS = $clog2(DATA_WORDS);

    // --- Core -------------------------------------------------------------------

    wire        ibus_cmd_valid;
    wire [31:0] ibus_cmd_pc;
    reg         ibus_rsp_valid;
    reg         ibus_rsp_error;
    wire [31:0] ibus_rsp_inst;

    wire        dbus_cmd_valid;
    wire        dbus_cmd_wr;
    wire [3:0]  dbus_cmd_mask;
    wire [31:0] dbus_cmd_address;
    wire [31:0] dbus_cmd_data;
    wire [1:0]  dbus_cmd_size;
    reg         dbus_rsp_ready;
    reg         dbus_rsp_error;
    reg  [31:0] dbus_rsp_data;

    VexRiscv cpu (
        .clk                      (clk),
        .reset                    (reset),
        .iBus_cmd_valid           (ibus_cmd_valid),
        .iBus_cmd_ready           (1'b1),
        .iBus_cmd_payload_pc      (ibus_cmd_pc),
        .iBus_rsp_valid           (ibus_rsp_valid),
        .iBus_rsp_payload_error   (ibus_rsp_error),
        .iBus_rsp_payload_inst    (ibus_rsp_inst),
        .dBus_cmd_valid           (dbus_cmd_valid),
        .dBus_cmd_ready           (1'b1),
        .dBus_cmd_payload_wr      (dbus_cmd_wr),
        .dBus_cmd_payload_mask    (dbus_cmd_mask),
        .dBus_cmd_payload_address (dbus_cmd_address),
        .dBus_cmd_payload_data    (dbus_cmd_data),
        .dBus_cmd_payload_size    (dbus_cmd_size),
        .dBus_rsp_ready           (dbus_rsp_ready),
        .dBus_rsp_error           (dbus_rsp_error),
        .dBus_rsp_data            (dbus_rsp_data),
        .timerInterrupt           (irq_timer),
        .externalInterrupt        (1'b0),
        .softwareInterrupt        (1'b0),
        // The retire trace (RVFI) is read by the simulation testbench only.
        .rvfi_valid (), .rvfi_order (), .rvfi_insn (), .rvfi_trap (), .rvfi_halt (),
        .rvfi_intr (), .rvfi_mode (), .rvfi_ixl (),
        .rvfi_rs1_addr (), .rvfi_rs1_rdata (), .rvfi_rs2_addr (), .rvfi_rs2_rdata (),
        .rvfi_rd_addr (), .rvfi_rd_wdata (), .rvfi_pc_rdata (), .rvfi_pc_wdata (),
        .rvfi_mem_addr (), .rvfi_mem_rmask (), .rvfi_mem_wmask (), .rvfi_mem_rdata (),
        .rvfi_mem_wdata ()
    );

    // --- Address decode ---------------------------------------------------------

    function automatic in_code(input [31:0] a);
        in_code = a[31:18] == 14'd0;                  // 0x0000_0000, 256 KiB
    endfunction

    function automatic in_data(input [31:0] a);
        in_data = a[31:16] == 16'h2000;               // 0x2000_0000, 64 KiB
    endfunction

    function automatic in_io(input [31:0] a);
        in_io = a[31:4] == 28'h1000_000 && a[3:2] != 2'd3;
    endfunction

    wire d_code = in_code(dbus_cmd_address);
    wire d_data = in_data(dbus_cmd_address);
    wire d_io   = in_io(dbus_cmd_address);
    wire d_read = dbus_cmd_valid && !dbus_cmd_wr;

    // --- Code RAM: port A fetches instructions, port B is the data port ---------

    wire [31:0] code_rdata;

    thumbv_ram #(.WORDS(CODE_WORDS), .INIT_FILE(CODE_INIT)) code_ram (
        .clk     (clk),
        .a_addr  (ibus_cmd_pc[CODE_BITS+1:2]),
        .a_rdata (ibus_rsp_inst),
        .b_addr  (dbus_cmd_address[CODE_BITS+1:2]),
        .b_we    (dbus_cmd_valid && dbus_cmd_wr && d_code ? dbus_cmd_mask : 4'b0),
        .b_wdata (dbus_cmd_data),
        .b_rdata (code_rdata)
    );

    always @(posedge clk) begin
        ibus_rsp_valid <= !reset && ibus_cmd_valid;
        ibus_rsp_error <= !in_code(ibus_cmd_pc);
    end

    // --- Data RAM ---------------------------------------------------------------

    wire [31:0] data_rdata;

    thumbv_ram #(.WORDS(DATA_WORDS), .INIT_FILE(DATA_INIT)) data_ram (
        .clk     (clk),
        .a_addr  ({DATA_BITS{1'b0}}),
        .a_rdata (),
        .b_addr  (dbus_cmd_address[DATA_BITS+1:2]),
        .b_we    (dbus_cmd_valid && dbus_cmd_wr && d_data ? dbus_cmd_mask : 4'b0),
        .b_wdata (dbus_cmd_data),
        .b_rdata (data_rdata)
    );

    // --- I/O --------------------------------------------------------------------

    wire uart_busy;
    wire io_write = dbus_cmd_valid && dbus_cmd_wr && d_io;

    thumbv_uart_tx #(.CLKS_PER_BIT(UART_CLKS_PER_BIT)) uart (
        .clk   (clk),
        .reset (reset),
        .valid (io_write && dbus_cmd_address[3:2] == 2'd0 && dbus_cmd_mask[0]),
        .data  (dbus_cmd_data[7:0]),
        .busy  (uart_busy),
        .tx    (uart_tx)
    );

    always @(posedge clk) begin
        if (reset)
            leds <= 8'h00;
        else if (io_write && dbus_cmd_address[3:2] == 2'd2 && dbus_cmd_mask[0])
            leds <= dbus_cmd_data[7:0];
    end

    // --- Data responses: one cycle after the command, for loads only -------------

    reg [1:0]  rsp_sel;   // 0 code, 1 data, 2 I/O, 3 unmapped
    reg [31:0] io_rdata;

    always @(posedge clk) begin
        dbus_rsp_ready <= !reset && d_read;
        rsp_sel        <= d_code ? 2'd0 : d_data ? 2'd1 : d_io ? 2'd2 : 2'd3;
        case (dbus_cmd_address[3:2])
            2'd1:    io_rdata <= {31'b0, uart_busy};
            2'd2:    io_rdata <= {24'b0, leds};
            default: io_rdata <= 32'b0;
        endcase
    end

    always @(*) begin
        dbus_rsp_error = rsp_sel == 2'd3;
        case (rsp_sel)
            2'd0:    dbus_rsp_data = code_rdata;
            2'd1:    dbus_rsp_data = data_rdata;
            2'd2:    dbus_rsp_data = io_rdata;
            default: dbus_rsp_data = 32'b0;
        endcase
    end
endmodule
