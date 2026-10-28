`timescale 1ns/1ps
// Generated HLS AXI-lite register block + real counter. The bounded engine
// completion stimulus is synthetic; this is NOT another complete-engine cosim.
module tb_gcs_cycle_axi;
  reg clk=0,resetn=0;
  always #5 clk=~clk;
  reg [7:0] awaddr=0,araddr=0;
  reg awvalid=0,wvalid=0,arvalid=0,rready=0;
  reg [31:0] wdata=0;
  wire awready,wready,bvalid,arready,rvalid,start;
  wire [31:0] rdata,cycles;
  reg busy=0;
  integer planned=1,remaining=0,edge_no=0,started=0,completed=0;
  wire accepted=!busy && start;
  wire done=busy && remaining==0;
  tt_gcs_cycle_counter counter(clk,resetn,accepted,done,cycles);
  tt_engine_CTRL_s_axi ctrl(.ACLK(clk),.ARESET(!resetn),.ACLK_EN(1'b1),
    .AWADDR(awaddr),.AWVALID(awvalid),.AWREADY(awready),.WDATA(wdata),.WSTRB(4'hf),
    .WVALID(wvalid),.WREADY(wready),.BVALID(bvalid),.BREADY(1'b1),
    .ARADDR(araddr),.ARVALID(arvalid),.ARREADY(arready),.RDATA(rdata),.RVALID(rvalid),.RREADY(rready),
    .ap_start(start),.ap_done(done),.ap_ready(done),.ap_idle(!busy),.ap_return(32'h120c0400),
    .cycles(cycles),.cycles_ap_vld(done));
  always @(posedge clk) begin
    edge_no=edge_no+1;
    if(!resetn)begin busy<=0;remaining<=0;end
    else if(accepted)begin busy<=1;remaining<=planned-1;started=edge_no;end
    else if(busy)begin
      if(done)begin
        if(cycles!==32'hffffffff && cycles!==edge_no-started)$fatal(1,"independent edge scoreboard");
        busy<=0;completed=completed+1;
      end else remaining<=remaining-1;
    end
  end
  task write_start;
    begin
      @(negedge clk);awaddr=0;awvalid=1;wdata=1;
      @(posedge clk);while(!awready)@(posedge clk);
      @(negedge clk);awvalid=0;wvalid=1;
      @(posedge clk);while(!wready)@(posedge clk);
      @(negedge clk);wvalid=0;
    end
  endtask
  task read_reg(input [7:0] addr,output [31:0] value);
    begin
      @(negedge clk);araddr=addr;arvalid=1;rready=0;
      @(posedge clk);while(!arready)@(posedge clk);
      @(negedge clk);arvalid=0;
      while(!rvalid)@(negedge clk);
      value=rdata;repeat(3)begin @(negedge clk);if(!rvalid||rdata!==value)$fatal(1,"AXI backpressure changed data");end
      rready=1;@(negedge clk);rready=0;
    end
  endtask
  reg [31:0] value;
  integer expected;
  task transaction(input integer n);
    begin
      planned=n;expected=completed+1;write_start;
      wait(completed==expected);repeat(3)@(negedge clk);
      read_reg(8'h00,value);if(!value[1])$fatal(1,"done not latched");
      read_reg(8'h98,value);if(value!==n)$fatal(1,"cycles register off by one/stale");
      read_reg(8'h9c,value);if(value!==1)$fatal(1,"cycles valid absent");
      read_reg(8'h9c,value);if(value!==0)$fatal(1,"valid not clear-on-read");
      read_reg(8'h98,value);if(value!==n)$fatal(1,"read cleared counter value");
    end
  endtask
  initial begin
    repeat(3)@(negedge clk);resetn=1;repeat(3)@(negedge clk);
    read_reg(8'h98,value);if(value!==0)$fatal(1,"reset cycles");
    transaction(1);transaction(2);transaction(37);
    planned=1000;write_start;repeat(7)@(negedge clk);resetn=0;repeat(3)@(negedge clk);resetn=1;
    read_reg(8'h98,value);if(value!==0)$fatal(1,"mid-call reset retained stale value");
    read_reg(8'h9c,value);if(value!==0)$fatal(1,"mid-call reset retained valid");
    transaction(5);
    planned=8;expected=completed+1;write_start;wait(busy);@(negedge clk);
    force counter.count=32'hfffffffe;wait(completed==expected);@(negedge clk);release counter.count;
    read_reg(8'h98,value);if(value!==32'hffffffff)$fatal(1,"saturation did not reach AXI register");
    transaction(3);
    $display("CYCLE_AXI_PASS start/done independent-edge counts, AXI capture/read/stall, repeated calls, reset, saturation; synthetic completion NOT board");
    $finish;
  end
  initial begin #100000;$fatal(1,"bounded test timed out");end
endmodule
