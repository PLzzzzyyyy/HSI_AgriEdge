`timescale 1ns/1ps
module tb_gcs_cycle_counter;
    reg clk=0,resetn=0,accepted=0,done=0;
    wire [31:0] cycles;
    tt_gcs_cycle_counter dut(clk,resetn,accepted,done,cycles);
    always #2.5 clk=~clk;
    task tick;begin @(posedge clk);#1;end endtask
    initial begin
        tick;resetn=1;tick;
        if(cycles!==0)$fatal(1,"idle is invalid");
        accepted=1;tick;accepted=0;
        repeat(9)tick;
        done=1;
        if(cycles!==10)$fatal(1,"start to done ten cycles");
        tick;done=0;
        if(cycles!==0)$fatal(1,"stale output not a new measurement");
        accepted=1;tick;accepted=0;
        if(cycles!==1)$fatal(1,"new call starts fresh");
        force dut.count=32'hfffffffe;
        #1;if(cycles!==32'hffffffff)$fatal(1,"saturation sentinel");
        release dut.count;resetn=0;tick;
        if(cycles!==0)$fatal(1,"reset clears pending measurement");
        $display("CYCLE_COUNTER_PASS exact boundaries restart saturation reset; RTL simulation only");
        $finish;
    end
endmodule
