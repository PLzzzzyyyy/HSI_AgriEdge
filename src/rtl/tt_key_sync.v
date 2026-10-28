// KEY6 (AF12, active low) crosses into PL0 before entering PS GPIO EMIO0.
// Mechanical debounce and gesture recognition live in the PS software.
module tt_key_sync(input wire clk, input wire key_n, output wire stable_n);
    (* ASYNC_REG = "TRUE" *) reg meta = 1'b1;
    (* ASYNC_REG = "TRUE" *) reg sync = 1'b1;
    always @(posedge clk) begin meta <= key_n; sync <= meta; end
    assign stable_n = sync;
endmodule
