// The interrupt controller (D9, Phase 5.2): the ARMv6-M NVIC and SysTick
// programming model at the System Control Space, plus Thumb-V's CLAIM and
// COMPLETE registers for software interrupt entry.
//
// model/thumbv/nvic.py is the reference: it documents the registers and
// the cycle model, and tests/test_nvic_rtl.py checks this module against it
// cycle by cycle. In short:
//   - exceptions are numbered as on Cortex-M: PendSV 14, SysTick 15,
//     interrupt n 16 + n; priorities 0 (highest) to 3, ties to the lowest
//     number;
//   - a read of CLAIM returns the highest-priority pending exception that
//     can preempt the current priority, clears its pending bit and pushes it
//     on the active stack (at most 4 deep); a write to COMPLETE pops it;
//   - `irq` (the core's machine external interrupt) is high while some
//     pending exception could be claimed;
//   - interrupt lines are level-sensitive: high, they pend their interrupt
//     unless it is active.
//
// Bus: one access per cycle; a read's data is registered (valid the cycle
// after), like the SoC's RAMs. Word accesses only.

module thumbv_nvic (
    input  wire        clk,
    input  wire        reset,
    input  wire        bus_valid,
    input  wire        bus_wr,
    input  wire [31:0] bus_addr,
    input  wire [31:0] bus_wdata,
    output reg  [31:0] bus_rdata,
    input  wire [31:0] lines,
    output wire        irq
);
    localparam [31:0] SYST_CSR = 32'hE000_E010, SYST_RVR = 32'hE000_E014,
                      SYST_CVR = 32'hE000_E018, SYST_CALIB = 32'hE000_E01C,
                      ISER = 32'hE000_E100, ICER = 32'hE000_E180,
                      ISPR = 32'hE000_E200, ICPR = 32'hE000_E280, IPR = 32'hE000_E400,
                      CPUID = 32'hE000_ED00, ICSR = 32'hE000_ED04,
                      SHPR2 = 32'hE000_ED1C, SHPR3 = 32'hE000_ED20,
                      CLAIM = 32'h1000_1000, COMPLETE = 32'h1000_1004;

    reg  [31:0] enabled, pending;
    reg  [63:0] prio;                       // interrupt n: bits 2n+1:2n
    reg         pendsv, pendst;
    reg  [1:0]  prio_svcall, prio_pendsv, prio_systick;
    reg         syst_enable, syst_tickint, countflag;
    reg  [23:0] rvr, cvr;
    reg  [5:0]  act_exc [0:3];              // the active stack, entry depth-1 the most recent
    reg  [1:0]  act_prio [0:3];
    reg  [2:0]  depth;

    // --- Priority resolution ------------------------------------------------------

    // Sources in exception-number order: bit k is exception 14 + k.
    wire [33:0] src_valid = {pending & enabled, pendst, pendsv};
    wire [67:0] src_prio  = {prio, prio_systick, prio_pendsv};

    // The highest-priority valid source with priority < below: its exception
    // number, or 0. One priority encoder per level; the lowest level wins.
    function automatic [5:0] best_of(input [33:0] valid, input [67:0] p, input [2:0] below);
        integer level, k;
        reg [5:0] at_level;
        begin
            best_of = 6'd0;
            for (level = 3; level >= 0; level = level - 1) begin
                at_level = 6'd0;
                for (k = 33; k >= 0; k = k - 1)
                    if (valid[k] && p[2*k +: 2] == level[1:0])
                        at_level = 6'd14 + k[5:0];
                if (at_level != 6'd0 && level < below)
                    best_of = at_level;
            end
        end
    endfunction

    function automatic [1:0] prio_of(input [5:0] exc);
        prio_of = exc == 6'd14 ? prio_pendsv : exc == 6'd15 ? prio_systick : prio[2*(exc - 6'd16) +: 2];
    endfunction

    wire [1:0] top       = depth[1:0] - 2'd1;     // the most recent active entry, if depth != 0
    wire [2:0] current   = depth == 3'd0 ? 3'd4 : {1'b0, act_prio[top]};
    wire [5:0] claimable = best_of(src_valid, src_prio, current);
    wire [5:0] vectpending = best_of(src_valid, src_prio, 3'd4);
    assign irq = claimable != 6'd0;

    // --- Reads ------------------------------------------------------------------

    wire rd = bus_valid && !bus_wr;
    wire wr = bus_valid && bus_wr;

    reg [31:0] read_value;
    integer j;
    always @(*) begin
        read_value = 32'd0;
        case (bus_addr)
            CLAIM:      read_value = {26'd0, claimable};
            SYST_CSR:   read_value = {15'd0, countflag, 13'd0, 1'b1, syst_tickint, syst_enable};
            SYST_RVR:   read_value = {8'd0, rvr};
            SYST_CVR:   read_value = {8'd0, cvr};
            SYST_CALIB: read_value = 32'hC000_0000;
            ISER, ICER: read_value = enabled;
            ISPR, ICPR: read_value = pending;
            CPUID:      read_value = 32'h410C_C200;
            ICSR:       read_value = {3'd0, pendsv, 1'b0, pendst, 3'd0, pending != 32'd0, 1'b0,
                                      3'd0, vectpending, 3'd0,
                                      3'd0, depth == 3'd0 ? 6'd0 : act_exc[top]};
            SHPR2:      read_value = {prio_svcall, 30'd0};
            SHPR3:      read_value = {prio_systick, 6'd0, prio_pendsv, 22'd0};
            default:
                if (bus_addr[31:5] == IPR[31:5])        // IPR0-7
                    for (j = 0; j < 4; j = j + 1)
                        read_value[8*j + 6 +: 2] = prio[2*(4*bus_addr[4:2] + j) +: 2];
        endcase
    end

    always @(posedge clk)
        if (rd)
            bus_rdata <= read_value;

    // --- State: the same order as Nvic.step() ------------------------------------

    wire claim = rd && bus_addr == CLAIM && claimable != 6'd0;
    wire [5:0] claim_irq = claimable - 6'd16;       // its interrupt number, if >= 16

    reg [23:0] n_cvr;
    reg        n_countflag, n_pendst, n_pendsv;
    reg [31:0] n_pending, n_enabled, active_irqs;
    reg [2:0]  n_depth;
    reg [5:0]  act_irq;
    integer    i;

    always @(*) begin
        // SysTick
        n_countflag = countflag;
        n_pendst = pendst;
        if (rd && bus_addr == SYST_CSR)
            n_countflag = 1'b0;
        if (wr && bus_addr == SYST_CVR) begin
            n_cvr = 24'd0;
            n_countflag = 1'b0;
        end else if (syst_enable) begin
            if (cvr == 24'd0)
                n_cvr = rvr;
            else begin
                n_cvr = cvr - 24'd1;
                if (cvr == 24'd1) begin
                    n_countflag = 1'b1;
                    if (syst_tickint)
                        n_pendst = 1'b1;
                end
            end
        end else
            n_cvr = cvr;

        // Claim, complete, pending and enables
        n_pending = pending;
        n_pendsv = pendsv;
        n_enabled = enabled;
        n_depth = depth;
        if (claim) begin
            n_depth = depth + 3'd1;
            if (claimable == 6'd14)
                n_pendsv = 1'b0;
            else if (claimable == 6'd15)
                n_pendst = 1'b0;
            else
                n_pending[claim_irq[4:0]] = 1'b0;
        end
        if (wr && bus_addr == COMPLETE && depth != 3'd0)
            n_depth = depth - 3'd1;
        if (wr && bus_addr == ISER) n_enabled = enabled | bus_wdata;
        if (wr && bus_addr == ICER) n_enabled = enabled & ~bus_wdata;
        if (wr && bus_addr == ISPR) n_pending = n_pending | bus_wdata;
        if (wr && bus_addr == ICPR) n_pending = n_pending & ~bus_wdata;
        if (wr && bus_addr == ICSR) begin
            if (bus_wdata[28]) n_pendsv = 1'b1;
            if (bus_wdata[27]) n_pendsv = 1'b0;
            if (bus_wdata[26]) n_pendst = 1'b1;
            if (bus_wdata[25]) n_pendst = 1'b0;
        end

        // Lines pend their interrupt while high, unless it is active.
        active_irqs = 32'd0;
        for (i = 0; i < 4; i = i + 1) begin
            act_irq = act_exc[i] - 6'd16;
            if (i < n_depth && i < depth && act_exc[i] >= 6'd16)
                active_irqs[act_irq[4:0]] = 1'b1;
        end
        if (claim && claimable >= 6'd16)
            active_irqs[claim_irq[4:0]] = 1'b1;
        n_pending = n_pending | (lines & ~active_irqs);
    end

    always @(posedge clk) begin
        if (reset) begin
            enabled <= 32'd0;
            pending <= 32'd0;
            prio <= 64'd0;
            pendsv <= 1'b0;
            pendst <= 1'b0;
            prio_svcall <= 2'd0;
            prio_pendsv <= 2'd0;
            prio_systick <= 2'd0;
            syst_enable <= 1'b0;
            syst_tickint <= 1'b0;
            countflag <= 1'b0;
            rvr <= 24'd0;
            cvr <= 24'd0;
            depth <= 3'd0;
        end else begin
            cvr <= n_cvr;
            countflag <= n_countflag;
            pendst <= n_pendst;
            pendsv <= n_pendsv;
            pending <= n_pending;
            enabled <= n_enabled;
            depth <= n_depth;
            if (claim) begin
                act_exc[depth[1:0]] <= claimable;
                act_prio[depth[1:0]] <= prio_of(claimable);
            end
            if (wr) begin
                if (bus_addr == SYST_CSR) begin
                    syst_enable <= bus_wdata[0];
                    syst_tickint <= bus_wdata[1];
                end
                if (bus_addr == SYST_RVR) rvr <= bus_wdata[23:0];
                if (bus_addr[31:5] == IPR[31:5])
                    for (i = 0; i < 4; i = i + 1)
                        prio[2*(4*bus_addr[4:2] + i) +: 2] <= bus_wdata[8*i + 6 +: 2];
                if (bus_addr == SHPR2) prio_svcall <= bus_wdata[31:30];
                if (bus_addr == SHPR3) begin
                    prio_systick <= bus_wdata[31:30];
                    prio_pendsv <= bus_wdata[23:22];
                end
            end
        end
    end
endmodule
