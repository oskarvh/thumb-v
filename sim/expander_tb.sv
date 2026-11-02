// Runs instructions through the expander alone (build/rtl/ThumbExpander.v),
// for the exhaustive check against the model (tests/test_expander_rtl.py).
//
// Plusargs:
//   +in=<file>    one per line: "hw1 hw2 pc1 step" in hex: the instruction
//                 (hw2 is ignored for 16-bit ones), bit 1 of its address and
//                 the op number in its expansion
//   +out=<file>   "op last" for each: the RV32 op, and 1 if it is the last

module expander_tb;
    logic [15:0] hw1, hw2;
    logic        pc1;
    logic [3:0]  step;
    wire  [31:0] op;
    wire         last;

    ThumbExpander dut (.io_hw1(hw1), .io_hw2(hw2), .io_pc1(pc1), .io_step(step), .io_op(op), .io_last(last));

    string in_file, out_file;
    int fin, fout, n;
    int a, b, c, d;

    initial begin
        if (!$value$plusargs("in=%s", in_file) || !$value$plusargs("out=%s", out_file))
            $fatal(1, "usage: +in=<file> +out=<file>");
        fin = $fopen(in_file, "r");
        fout = $fopen(out_file, "w");
        // Read into variables, then assign: Verilator doesn't treat $fscanf's
        // writes as events, so the expander wouldn't re-evaluate.
        while ($fscanf(fin, "%h %h %h %h\n", a, b, c, d) == 4) begin
            hw1 = a[15:0];
            hw2 = b[15:0];
            pc1 = c[0];
            step = d[3:0];
            #1 $fdisplay(fout, "%h %h", op, last);
            n++;
        end
        $fclose(fout);
        $display("expanded %0d instructions", n);
        $finish;
    end
endmodule
