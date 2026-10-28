// ABI4 hardware measurement only. Number of rising-edge intervals from an
// accepted start to done. Includes PL AXI stalls, not PS polling/cache time.
// Read only with done. Zero and FFFFFFFF are invalid; never wrap to a small time.
module tt_gcs_cycle_counter (
    input wire clk, input wire resetn,
    input wire accepted, input wire done,
    output wire [31:0] cycles
);
    reg active;
    reg [31:0] count;
    assign cycles = !active ? 32'd0 :
        (count >= 32'hfffffffe ? 32'hffffffff : count + 32'd1);
    always @(posedge clk) begin
        if (!resetn) begin active <= 1'b0; count <= 32'd0; end
        else if (accepted) begin active <= 1'b1; count <= 32'd0; end
        else if (active) begin
            if (done) active <= 1'b0;
            else if (count < 32'hfffffffe) count <= count + 32'd1;
        end
    end
endmodule
