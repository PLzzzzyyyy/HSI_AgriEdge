// Diagnostic AXI4 memory: one outstanding burst, deterministic REAL stalls.
// No claim to model DDR throughput. DUT RTL is not modified.
`timescale 1ns/1ps
module s2_axi_memory #(parameter WORDS=1024, parameter FILE="", parameter READ_ONLY=0)(
 input wire clk,rst_n,
 input wire [63:0] araddr,awaddr,wdata,
 input wire [7:0] arlen,awlen,wstrb,
 input wire [2:0] arsize,awsize,
 input wire [1:0] arburst,awburst,
 input wire arid,awid,arvalid,awvalid,wvalid,wlast,rready,bready,
 output wire arready,awready,wready,
 output reg [63:0] rdata,
 output reg rvalid,rlast,rid,bvalid,bid,
 output wire [1:0] rresp,bresp
);
 localparam [63:0] GUARD=64'h5a719dce4362be08;
 reg [63:0] mem[0:WORDS-1];
 reg reading=0,writing=0;
 reg [63:0] ra=0,wa=0;
 integer rn=0,wn=0,rs=0,ws=0,bdelay=0;
 longint cycles=0,ar_count=0,r_count=0,aw_count=0,w_count=0,b_count=0;
 longint ar_stall=0,aw_stall=0,w_stall=0,r_stall=0,b_stall=0,last_write=0,last_response=0;
 integer j,k;
 reg prev_ar=0,prev_aw=0,prev_w=0;
 reg [77:0] ar_payload,aw_payload;
 reg [72:0] w_payload;
 initial begin
   rdata=0;rvalid=0;rlast=0;rid=0;bvalid=0;bid=0;
   for(j=0;j<WORDS;j=j+1) mem[j]=GUARD;
   if(FILE!="") $readmemh(FILE,mem);
 end
 assign arready=rst_n && !reading && !rvalid && (cycles%7==0);
 assign awready=rst_n && !writing && !bvalid && bdelay==0 && (cycles%11==0);
 assign wready=rst_n && writing && (cycles%5==0);
 assign rresp=0;
 assign bresp=0;
 always @(posedge clk) if(rst_n) begin
   cycles<=cycles+1;
   if(prev_ar && (!arvalid || {araddr,arlen,arsize,arburst,arid}!==ar_payload)) $fatal(1,"AXI_AR_UNSTABLE");
   if(prev_aw && (!awvalid || {awaddr,awlen,awsize,awburst,awid}!==aw_payload)) $fatal(1,"AXI_AW_UNSTABLE");
   if(prev_w && (!wvalid || {wdata,wstrb,wlast}!==w_payload)) $fatal(1,"AXI_W_UNSTABLE");
   prev_ar<=arvalid&&!arready;ar_payload<={araddr,arlen,arsize,arburst,arid};
   prev_aw<=awvalid&&!awready;aw_payload<={awaddr,awlen,awsize,awburst,awid};
   prev_w<=wvalid&&!wready;w_payload<={wdata,wstrb,wlast};
   if(arvalid&&!arready) ar_stall<=ar_stall+1;
   if(awvalid&&!awready) aw_stall<=aw_stall+1;
   if(wvalid&&!wready) w_stall<=w_stall+1;
   if(rvalid&&!rready) r_stall<=r_stall+1;
   if(bvalid&&!bready) b_stall<=b_stall+1;
   if(arvalid&&arready) begin
     if(arburst!=1 || arsize!=3 || araddr%8!=0 || (araddr+(arlen+1)*8)>WORDS*8) $fatal(1,"AXI_BAD_READ_RANGE");
     ar_count<=ar_count+1;reading<=1;ra<=araddr;rn<=arlen+1;rs<=1<<arsize;rid<=arid;
   end
   if(reading&&!rvalid && cycles%3==0) begin
     rdata<=mem[ra>>3];rvalid<=1;rlast<=rn==1;
   end
   if(rvalid&&rready) begin
     r_count<=r_count+1;rvalid<=0;ra<=ra+rs;rn<=rn-1;
     if(rn==1) reading<=0;
   end
   if(awvalid&&awready) begin
     if(READ_ONLY || awburst!=1 || awsize>3 || (awaddr+(awlen+1)*(1<<awsize))>WORDS*8) $fatal(1,"AXI_BAD_WRITE_RANGE");
     aw_count<=aw_count+1;writing<=1;wa<=awaddr;wn<=awlen+1;ws<=1<<awsize;bid<=awid;
   end
   if(wvalid&&wready) begin
     if(wlast!==(wn==1)) $fatal(1,"AXI_WLAST_MISMATCH");
     for(k=0;k<8;k=k+1) if(wstrb[k]) mem[wa>>3][8*k+:8]<=wdata[8*k+:8];
     w_count<=w_count+1;last_write<=cycles;wa<=wa+ws;wn<=wn-1;
     if(wn==1) begin writing<=0;bdelay<=7;end
   end
   if(bdelay>0) begin bdelay<=bdelay-1;if(bdelay==1) bvalid<=1;end
   if(bvalid&&bready) begin b_count<=b_count+1;bvalid<=0;last_response<=cycles;end
 end
 task report;
   $display("AXI_STATS %m ar=%0d r=%0d aw=%0d w=%0d b=%0d ar_stall=%0d aw_stall=%0d w_stall=%0d r_stall=%0d b_stall=%0d last_write=%0d last_response=%0d",ar_count,r_count,aw_count,w_count,b_count,ar_stall,aw_stall,w_stall,r_stall,b_stall,last_write,last_response);
   if(reading||writing||rvalid||bvalid||bdelay!=0||aw_count!=b_count) $fatal(1,"AXI_NOT_DRAINED");
 endtask
endmodule
