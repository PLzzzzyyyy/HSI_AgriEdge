// Included in a generated top containing exact DUT port declarations and BFMs.
longint cycles=0,start_cycle=0,done_cycle=0;
integer call_id=0,fd,i;
integer layers_saved=0;
reg active=0;
reg [31:0] value;
longint progress_count=0,last_progress=0,cq_put=0,cq_get=0,cr_put=0,cr_get=0;
always #2.5 ap_clk=~ap_clk;
always @(posedge ap_clk) if(ap_rst_n) begin
  cycles<=cycles+1;
  if(dut.engine_task_U0_cq_write&&dut.cq_full_n) cq_put<=cq_put+1;
  if(dut.core_service_U0_request_read&&dut.cq_empty_n) cq_get<=cq_get+1;
  if(dut.core_service_U0_response_write&&dut.cr_full_n) cr_put<=cr_put+1;
  if(dut.engine_task_U0_cr_read&&dut.cr_empty_n) cr_get<=cr_get+1;
  // Save only observed layer data, after its last write response drains.
  // These checkpoints do not drive the DUT and are NOT full-call PASS.
  if(call_id==1 && layers_saved<12 && outmem.w_count>=(layers_saved+1)*7938 &&
     !outmem.writing && !outmem.bvalid && outmem.bdelay==0 && outmem.aw_count==outmem.b_count) begin
    $writememh($sformatf("layer_%02d.hex",layers_saved),outmem.mem,
              512+layers_saved*7938,512+(layers_saved+1)*7938-1);
    $display("LAYER_SNAPSHOT layer=%0d cycle=%0d out_beats=%0d NOT_FULL_CALL_PASS",layers_saved,cycles,outmem.w_count);
    layers_saved<=layers_saved+1;
  end
  if(call_id==0 && dut.engine_task_U0_cq_write && dut.cq_full_n && cq_put>=22992) begin
    $display("LOAD_CONTROL_WRITE cycle=%0d index=%0d kind=%0d",cycles,cq_put,dut.engine_task_U0_cq_din[4:0]);
    if((cq_put==22992 && dut.engine_task_U0_cq_din[4:0]!==0) ||
       (cq_put==22993 && dut.engine_task_U0_cq_din[4:0]!==5)) $fatal(1,"LOAD_CONTROL_ORDER_FAIL");
  end
  if(call_id==0 && dut.engine_task_U0_cr_read && dut.cr_empty_n) begin
    $display("LOAD_ACK_READ cycle=%0d cq_put=%0d cq_get=%0d",cycles,cq_put,cq_get);
    if(cq_get<22993) $fatal(1,"ACK_BEFORE_LOAD_ACCEPTED");
  end
  if(progress_count!=wmem.r_count+inmem.r_count+outmem.w_count+cq_put+cq_get+cr_put+cr_get) begin
    last_progress<=cycles;
    progress_count<=wmem.r_count+inmem.r_count+outmem.w_count+cq_put+cq_get+cr_put+cr_get;
  end
  // Bound a stalled LOAD, not the compute-only intervals of a layer.
  if(call_id==0 && active && cycles-last_progress>=50000) begin
    $display("LOAD_NO_PROGRESS cycle=%0d last_progress=%0d weight_reads=%0d cq_put=%0d cq_get=%0d cr_put=%0d cr_get=%0d",cycles,last_progress,wmem.r_count,cq_put,cq_get,cr_put,cr_get);
    $display("LOAD_AXI arvalid=%b arready=%b rvalid=%b rready=%b rlast=%b reading=%b rn=%0d ra=%h araddr=%h arlen=%0d",m_axi_wmem_ARVALID,m_axi_wmem_ARREADY,m_axi_wmem_RVALID,m_axi_wmem_RREADY,m_axi_wmem_RLAST,wmem.reading,wmem.rn,wmem.ra,m_axi_wmem_ARADDR,m_axi_wmem_ARLEN);
    $display("LOAD_CORE cq_empty_n=%b cq_full_n=%b cq_write=%b cq_read=%b cq_kind=%h cr_empty_n=%b cr_full_n=%b cr_write=%b cr_read=%b core_start=%b core_idle=%b core_done=%b core_state=%h",dut.cq_empty_n,dut.cq_full_n,dut.engine_task_U0_cq_write,dut.core_service_U0_request_read,dut.cq_dout[7:0],dut.cr_empty_n,dut.cr_full_n,dut.core_service_U0_response_write,dut.engine_task_U0_cr_read,dut.core_service_U0_ap_start,dut.core_service_U0_ap_idle,dut.core_service_U0_ap_done,dut.core_service_U0.ap_CS_fsm);
    `include "s2_load_observation.svh"
    $fatal(1,"LOAD_NO_PROGRESS_WATCHDOG_NOT_N1_COMPLETION");
  end
  // Separate, conservative diagnostic bound for n1. A cutoff is never a
  // completion/latency or sufficient evidence on its own of the root cause.
  if(call_id==1 && active && cycles-last_progress>=1000000) begin
    $display("N1_NO_PROGRESS cycle=%0d last_progress=%0d cq_put=%0d cq_get=%0d cr_put=%0d cr_get=%0d engine=%h worker=%h",cycles,last_progress,cq_put,cq_get,cr_put,cr_get,dut.engine_task_U0.ap_CS_fsm,dut.core_service_U0.ap_CS_fsm);
    $fatal(1,"N1_NO_PROGRESS_OBSERVATION_NOT_COMPLETION");
  end
  if(dut.ap_start&&!active) begin
    active<=1;start_cycle<=cycles;
    $display("CALL_START id=%0d cycle=%0d",call_id,cycles);
  end
  if(dut.ap_done&&active) begin
    active<=0;done_cycle<=cycles;
    $display("CALL_DONE id=%0d cycle=%0d cycles=%0d return=%0d fifo_empty=%0b%0b%0b%0b",call_id,cycles,cycles-start_cycle,dut.ap_return,!dut.rq_empty_n,!dut.rs_empty_n,!dut.cq_empty_n,!dut.cr_empty_n);
    if(dut.ap_return!=0 || dut.rq_empty_n || dut.rs_empty_n || dut.cq_empty_n || dut.cr_empty_n) $fatal(1,"RETURN_OR_FIFO_DRAIN_FAIL");
  end
  if(cycles%100000==0) $display("HEARTBEAT cycle=%0d call=%0d weight_reads=%0d input_reads=%0d out_beats=%0d",cycles,call_id,wmem.r_count,inmem.r_count,outmem.w_count);
  if(cycles>=100000000) $fatal(1,"DIAG_CYCLE_WATCHDOG");
end
task write_reg(input [7:0] addr,input [31:0] data);
  @(negedge ap_clk);s_axi_control_AWADDR=addr;s_axi_control_AWVALID=1;
  do @(posedge ap_clk);while(!s_axi_control_AWREADY);
  @(negedge ap_clk);s_axi_control_AWVALID=0;s_axi_control_WDATA=data;s_axi_control_WSTRB=15;s_axi_control_WVALID=1;
  do @(posedge ap_clk);while(!s_axi_control_WREADY);
  @(negedge ap_clk);s_axi_control_WVALID=0;s_axi_control_BREADY=1;
  do @(posedge ap_clk);while(!s_axi_control_BVALID);
  if(s_axi_control_BRESP!==0) $fatal(1,"CONTROL_BRESP");
  @(negedge ap_clk);s_axi_control_BREADY=0;
endtask
task read_reg(input [7:0] addr,output [31:0] data);
  @(negedge ap_clk);s_axi_control_ARADDR=addr;s_axi_control_ARVALID=1;
  do @(posedge ap_clk);while(!s_axi_control_ARREADY);
  @(negedge ap_clk);s_axi_control_ARVALID=0;s_axi_control_RREADY=1;
  do @(posedge ap_clk);while(!s_axi_control_RVALID);
  data=s_axi_control_RDATA;
  if(s_axi_control_RRESP!==0) $fatal(1,"CONTROL_RRESP");
  @(negedge ap_clk);s_axi_control_RREADY=0;
endtask
task invoke;
  write_reg(0,1);
  wait(dut.ap_done);@(negedge ap_clk);
  repeat(200) @(posedge ap_clk);
  if(!dut.ap_idle) $fatal(1,"NOT_IDLE_AFTER_DRAIN");
  wmem.report();inmem.report();outmem.report();
  read_reg(0,value); // clear sticky done before next transaction
  read_reg(8'h10,value);if(value!==0) $fatal(1,"CONTROL_RETURN_FAIL");
  $display("DRAIN_PASS id=%0d cycle=%0d",call_id,cycles);
endtask
initial begin
  repeat(20) @(negedge ap_clk);ap_rst_n=1;
  write_reg('h18,0);write_reg('h1c,0);write_reg('h24,0);write_reg('h28,0);
  write_reg('h30,0);write_reg('h34,0);write_reg('h3c,'h100);write_reg('h40,0);
  write_reg('h48,'h1000);write_reg('h4c,0);
  write_reg('h54,0);write_reg('h5c,1);write_reg('h64,0);write_reg('h6c,0);
  write_reg('h74,0);write_reg('h7c,20000000);
  invoke();
  if(outmem.w_count!=0) $fatal(1,"LOAD_WROTE_OUTPUT");
  $display("LOAD_HANDSHAKE_COUNTS cq_put=%0d cq_get=%0d cr_put=%0d cr_get=%0d",cq_put,cq_get,cr_put,cr_get);
  // W8: 48*(3 exponents + 98 W12 + 54*7 W3), LOAD, STOP.
  // No preloaded responses: exactly one real LOAD ACK must retire.
  if(cq_put!=22994 || cq_get!=22994 || cr_put!=1 || cr_get!=1) $fatal(1,"LOAD_HANDSHAKE_COUNTS_FAIL");
  call_id=1;write_reg('h54,1);write_reg('h5c,2);write_reg('h6c,11);
  invoke();
  fd=$fopen("meta.txt","w");
  for(i=0;i<12;i=i+1) begin
    read_reg('hc0+i*4,value);$fdisplay(fd,"%0d %0d",i,value);
    case(i)
      0:if(value!==32'h04080400) $fatal(1,"META_FORMAT");
      2:if(value!==1) $fatal(1,"META_RETIRE");
      3:if(value!==48) $fatal(1,"META_PROJECTION");
      4:if(value!==36) $fatal(1,"META_COPY");
      9:if(value!==12) $fatal(1,"META_LAYERS");
    endcase
  end
  $fclose(fd);
  $writememh("output.hex",outmem.mem);
  $display("S2_RTL_N1_EXECUTION_COMPLETE_NOT_NUMERIC_PASS");
  $finish;
end
