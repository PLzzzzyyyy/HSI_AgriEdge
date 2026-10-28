'use strict';
// Only an explicit click reads the board. Restore/tick never opens UART or UDP.
const ConnectionPanel=(()=>{
  let compatible=false,busy=false,source=null,legacyOwner=false;
  const state=message=>{$('#board-connect-state').textContent=message;};
  const clearReceipt=()=>{$('#board-connect-details').textContent='';};
  function controls(){
    $('#board-connect').disabled=!compatible||busy||legacyOwner||!!source?.active||!!(source?.authorized&&source?.connection_transport==='ethernet');
    $('#board-boot-method').disabled=busy||!!source?.active;
  }
  function apply(st){
    compatible=st?.board_records_protocol===1;
    legacyOwner=!!st?.uart?.active;source=st?.board_gate||st?.source||source;
    controls();
    if(!compatible){clearReceipt();state('当前后台未加载以太网接入版本；等待明确的服务切换窗口。刷新静态页面不能代替部署。');return;}
    if(busy)return;
    if(legacyOwner){clearReceipt();state('旧采集仍占用连接；请先按交接步骤释放，不接管已有操作。');return;}
    if(source?.connection_transport==='ethernet'&&source?.authorized){
      state(source.active?'原以太网连接仍在；任务和模型操作沿用同一连接。':'板卡已就绪，可以显式开始任务；不会自动推理。');
      $('#board-connect-details').textContent=`boot=${source.boot_id} · 以太网板端记录：${source.startup_evidence||'本次已核验'}`;
    }
  }
  function updateSource(value){source=value;controls();}
  $('#board-connect').onclick=async()=>{
    if($('#board-connect').disabled)return;
    const method=$('#board-boot-method').value;
    if(!['jtag','sd'].includes(method)){state('请先如实选择本次 JTAG 或 SD 启动方式；不默认声称独立冷启动。');return;}
    if(!confirm(`确认已由你${method==='jtag'?'通过 JTAG 下载并运行':'从 SD 启动'}新版，当前没有运行任务？这里只查询身份和实际板端记录，不下载、复位、发 START 或接管旧任务。`))return;
    busy=true;clearReceipt();controls();state('正在核对实际板端启动记录和空闲身份……');
    try{
      const response=await fetch('/api/board/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmed:true,boot_method:method})});
      const result=await response.json();if(!response.ok)throw Error(result.detail||response.statusText);
      const found=result.discovery,phase=found?.startup;
      if(!found||typeof result.ready!=='boolean'||result.uart_opened!==false||result.source?.source!=='board')throw Error('接入回执格式不符');
      $('#board-connect-details').textContent=JSON.stringify(found,null,2);
      if(result.ready){
        if(!result.source.authorized||result.source.connection_transport!=='ethernet'||result.source.boot_id!==found.boot_id||phase?.state!=='ready')throw Error('缺少完整启动核验，不放行任务');
        source=result.source;await BoardPanel.source(source);
        state(`板卡 ${found.boot_id} 已就绪，可以显式开始任务；独立冷启动仍需人工验收。`);
      }else{
        if(result.source.authorized)throw Error('未就绪回执不能授权任务');
        source=result.source;await BoardPanel.source(source);
        if(phase?.state==='error')state(`板端启动失败：${phase.error||'请查看原始启动回执'}；不放行任务。`);
        else{
          const label={starting:'初始化中',scanning_models:'正在扫描 SD 模型',initializing_display:'正在初始化显示'}[phase?.state]||'尚未就绪';
          const progress=phase?.scan_progress;
          state(`${label}${progress?`，已读 ${progress.bytes} 字节 / 已登记 ${progress.registered} 项`:''}；可再次点击刷新启动状态，不启动任务。`);
        }
      }
    }catch(e){clearReceipt();state(`接入失败：${e.message}；不启动任务或切换到 PC。无响应不等于 SD 仍在加载。`);}
    finally{busy=false;controls();}
  };
  function offline(){compatible=false;clearReceipt();controls();state('地面站服务已断开；恢复页面不会自动接管板卡。');}
  return {apply,source:updateSource,offline};
})();
