// Runs the interrupt controller alone (rtl/soc/thumbv_nvic.v), cycle by
// cycle, for the check against the model (tests/test_nvic_rtl.py,
// model/thumbv/nvic.py).
//
// Plusargs:
//   +in=<file>    one cycle per line, in hex: "op addr data lines", op 0 for
//                 no access, 1 for a read, 2 for a write
//   +out=<file>   one line per cycle, after its clock edge: "rdata irq"
//                 (rdata is the read's value, if the cycle had one)

module nvic_tb;
    logic        clk = 0, reset = 1;
    logic        valid = 0, wr = 0;
    logic [31:0] addr = 0, wdata = 0, lines = 0;
    wire  [31:0] rdata;
    wire         irq;

    thumbv_nvic dut (.clk(clk), .reset(reset), .bus_valid(valid), .bus_wr(wr), .bus_addr(addr),
                     .bus_wdata(wdata), .bus_rdata(rdata), .lines(lines), .irq(irq));

    string in_file, out_file;
    int fin, fout, n;
    int op, a, d, l;

    initial begin
        if (!$value$plusargs("in=%s", in_file) || !$value$plusargs("out=%s", out_file))
            $fatal(1, "usage: +in=<file> +out=<file>");
        fin = $fopen(in_file, "r");
        fout = $fopen(out_file, "w");
        #1 clk = 1;
        #1 clk = 0;
        reset = 0;
        // Read into variables, then assign: Verilator doesn't treat $fscanf's
        // writes as events.
        while ($fscanf(fin, "%h %h %h %h\n", op, a, d, l) == 4) begin
            valid = op != 0;
            wr = op == 2;
            addr = a;
            wdata = d;
            lines = l;
            #1 clk = 1;
            #1 clk = 0;
            $fdisplay(fout, "%h %h", rdata, irq);
            n++;
        end
        $fclose(fout);
        $display("ran %0d cycles", n);
        $finish;
    end
endmodule
