// Simulation testbench for the Thumb-V SoC (Verilator --binary --timing).
// CODE_WORDS and DATA_WORDS set the RAM sizes (-G): the defaults fill the
// regions, smaller ones simulate the board's RAMs.
//
// Plusargs:
//   +code=<file>    $readmemh image for the code RAM (word addresses)
//   +data=<file>    $readmemh image for the data RAM
//   +trace=<file>   write one line per retired instruction (RVFI), see below
//   +cycles=<n>     give up after n cycles (default 10,000,000)
//   +wave=<file>    dump every signal to an FST waveform (GTKWave, Surfer)
//
// The UART line is decoded here and printed to stdout. The run ends when the
// core retires `j .` (0x0000006f), the loop the startup code spins in at
// `done`; the testbench waits for the UART to finish sending, then prints
// "EXIT <a0> <cycles> <instructions>" (cycles and instructions up to `done`).
//
// Trace lines, all hex: pc insn rd rd_wdata mem_addr mem_rmask mem_wmask
// mem_rdata mem_wdata trap

`timescale 1ns / 1ps

module tb #(
    parameter CODE_WORDS = 65536,
    parameter DATA_WORDS = 16384
);
    localparam CLKS_PER_BIT = 4;   // fast UART for simulation

    logic clk = 0;
    logic reset = 1;
    wire  uart_tx;
    wire [7:0] leds;

    always #5 clk = ~clk;

    thumbv_soc #(.CODE_WORDS(CODE_WORDS), .DATA_WORDS(DATA_WORDS),
                 .UART_CLKS_PER_BIT(CLKS_PER_BIT)) dut (
        .clk(clk), .reset(reset), .uart_tx(uart_tx), .leds(leds));

    string code_file, data_file, trace_file, wave_file;
    longint max_cycles = 10_000_000;
    longint cycles = 0;
    longint retired = 0;
    int trace_fd = 0;
    logic [31:0] a0 = 0;
    logic done = 0;

    initial begin
        if ($value$plusargs("code=%s", code_file))
            $readmemh(code_file, dut.code_ram.mem);
        if ($value$plusargs("data=%s", data_file))
            $readmemh(data_file, dut.data_ram.mem);
        if ($value$plusargs("trace=%s", trace_file))
            trace_fd = $fopen(trace_file, "w");
        if ($value$plusargs("wave=%s", wave_file)) begin
            $dumpfile(wave_file);
            $dumpvars(0, tb);
        end
        void'($value$plusargs("cycles=%d", max_cycles));
        repeat (4) @(posedge clk);
        reset = 0;
    end

    // --- Retire trace and stop condition ---------------------------------------

    always @(posedge clk) begin
        if (!done)
            cycles <= cycles + 1;
        if (dut.cpu.rvfi_valid && !done) begin
            retired <= retired + 1;
            if (dut.cpu.rvfi_rd_addr == 10)
                a0 <= dut.cpu.rvfi_rd_wdata;
            if (trace_fd != 0)
                $fdisplay(trace_fd, "%h %h %h %h %h %h %h %h %h %h",
                          dut.cpu.rvfi_pc_rdata, dut.cpu.rvfi_insn,
                          dut.cpu.rvfi_rd_addr, dut.cpu.rvfi_rd_wdata,
                          dut.cpu.rvfi_mem_addr, dut.cpu.rvfi_mem_rmask,
                          dut.cpu.rvfi_mem_wmask, dut.cpu.rvfi_mem_rdata,
                          dut.cpu.rvfi_mem_wdata, dut.cpu.rvfi_trap);
            if (dut.cpu.rvfi_insn == 32'h0000006f)
                done <= 1;
        end
        if (cycles >= max_cycles)
            finish("TIMEOUT");
    end

    // Let the UART finish the last byte, and the receiver below print it.
    initial begin
        wait (done);
        wait (!dut.uart_busy);
        repeat (2 * CLKS_PER_BIT) @(posedge clk);
        finish("EXIT");
    end

    task automatic finish(input string why);
        $display("\n%s %h %0d %0d", why, a0, cycles, retired);
        if (trace_fd != 0)
            $fclose(trace_fd);
        $finish;
    endtask

    // --- UART receiver: sample each bit in its middle ----------------------------

    initial begin
        logic [7:0] byte_;
        forever begin
            @(negedge uart_tx);
            repeat (CLKS_PER_BIT / 2) @(posedge clk);
            for (int i = 0; i < 8; i++) begin
                repeat (CLKS_PER_BIT) @(posedge clk);
                byte_[i] = uart_tx;
            end
            repeat (CLKS_PER_BIT) @(posedge clk);   // stop bit
            $write("%c", byte_);
            $fflush();
        end
    end
endmodule
