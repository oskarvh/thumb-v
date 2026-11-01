// Runs instructions through the expander alone (build/rtl/ThumbExpander.v),
// for the exhaustive check against the model (tests/test_expander_rtl.py).
//
// Plusargs:
//   +in=<file>    one instruction per line: "hw1 hw2" in hex (hw2 is
//                 ignored for 16-bit instructions)
//   +out=<file>   the RV32 op for each, one per line, in hex

module expander_tb;
    logic [15:0] hw1, hw2;
    wire  [31:0] op;

    ThumbExpander dut (.io_hw1(hw1), .io_hw2(hw2), .io_op(op));

    string in_file, out_file;
    int fin, fout, n;
    int a, b;

    initial begin
        if (!$value$plusargs("in=%s", in_file) || !$value$plusargs("out=%s", out_file))
            $fatal(1, "usage: +in=<file> +out=<file>");
        fin = $fopen(in_file, "r");
        fout = $fopen(out_file, "w");
        // Read into variables, then assign: Verilator doesn't treat $fscanf's
        // writes as events, so the expander wouldn't re-evaluate.
        while ($fscanf(fin, "%h %h\n", a, b) == 2) begin
            hw1 = a[15:0];
            hw2 = b[15:0];
            #1 $fdisplay(fout, "%h", op);
            n++;
        end
        $fclose(fout);
        $display("expanded %0d instructions", n);
        $finish;
    end
endmodule
