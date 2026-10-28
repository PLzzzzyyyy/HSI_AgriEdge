'use strict';
// Connection requires a user click; restoration/status never opens UART or UDP.
const UartPanel=(()=>{
  let settingsLoaded=false,compatible=false;
  function apply(u){
    if(!u)return;
    compatible=u.service_app==='gcs_r1_abi4';
    if(!settingsLoaded){
      settingsLoaded=true;
      if(u.settings){
        const s=u.settings,select=$('#uart-port');
        select.append(new Option(s.port+' · 上次确认',s.port));select.value=s.port;
        $('#uart-baud').value=String(s.baudrate);
        $('#uart-settings-label').textContent=`沿用上次确认：${s.port} / ${s.baudrate}；无需重新选口。`;
      }else{
        $('#uart-settings-label').textContent='首次连接：请在连接设置中选择原UART0串口及波特率，以后自动记住。';
        $('#uart-settings').open=true;
      }
    }
    $('#uart-start').disabled=!!u.active||!compatible;
    $('#sd-connect').disabled=!!u.active||!compatible;
    $('#uart-stop').disabled=!u.active;
    $('#uart-port').disabled=!!u.active;$('#uart-baud').disabled=!!u.active;
    $('#uart-refresh').disabled=!!u.active;
    const state={disconnected:'未连接',waiting_prompt:'旧版身份流程不可用于新版。',waiting_record:'已只读连接，等待你启动新版；身份由SD持久记录产生，不发送串口输入。',waiting_ready:'已观察SD启动身份，等待READY；不输入身份码。',ready:'板卡已就绪，可以开始任务；日志正在自动保存。',error:'连接失败，请查看连接详情；不会自动重试。'}[u.state]||u.state;
    $('#uart-state').textContent=u.active?state:(u.port_released===false?'串口释放未确认，请查看连接详情。':u.error?'连接未完成，请查看连接详情；串口已释放。':'未连接；已有日志已保存。');
    $('#uart-diagnostics').textContent=`${u.boot_id?'boot='+u.boot_id+' · ':''}接收${u.rx_bytes}B / 发送${u.tx_bytes}B${u.error?' · '+u.error:''}${u.reason?' · '+u.reason:''}${u.evidence?' · 日志：'+u.evidence:''}`;
    $('#uart-tail').textContent=u.tail||'';
    if(!compatible){$('#uart-state').textContent='当前后台未加载新版候选；仅保留旧记录查看。请等待明确的部署窗口，不连接或复用旧启动。';$('#sd-connect-state').textContent='新版接入尚未部署，不能用静态页面刷新代替服务切换。';}
  }
  async function post(path,data){
    const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data||{})});
    const v=await r.json();if(!r.ok)throw Error(v.detail||r.statusText);return v;
  }
  $('#uart-refresh').onclick=async()=>{
    try {
      const r=await fetch('/api/uart/ports');if(!r.ok)throw Error('无法枚举串口');
      const ports=await r.json(),select=$('#uart-port');select.replaceChildren(new Option('请选择原UART0串口',''));
      for(const p of ports)select.append(new Option(`${p.port} · ${p.description}`,p.port));
    } catch(e){toast(e.message);}
  };
  $('#uart-start').onclick=async()=>{
    if(!compatible)return;
    if(!$('#uart-port').value){$('#uart-settings').open=true;return toast('首次连接请先选择原UART0串口；不会猜测其他端口。');}
    $('#uart-state').textContent='正在检查程序并连接板卡，请稍候；不会自动Build、下载或复位。';
    $('#uart-start').disabled=true;
    try{apply(await post('/api/uart/start',{port:$('#uart-port').value,baudrate:+$('#uart-baud').value,confirmed:true,connect_board:true}));}
    catch(e){$('#uart-state').textContent=e.message;$('#uart-start').disabled=false;}
  };
  $('#uart-stop').onclick=async()=>{try{apply(await post('/api/uart/stop'));}catch(e){toast(e.message);}};
  $('#sd-connect').onclick=async()=>{
    if(!compatible)return;
    if(!confirm('确认已由你从SD独立启动新版、当前没有运行任务？这里只查询INFO，不开串口、不发START，也不接管旧任务。'))return;
    $('#sd-connect').disabled=true;$('#sd-connect-state').textContent='正在查询新空闲启动身份……';
    try{
      const result=await post('/api/board/sd_connect',{confirmed:true});await BoardPanel.source(result.source);
      $('#sd-connect-state').textContent=`SD启动 ${result.discovery.boot_id} 已发现；请显式开始任务。未采集UART时内部计时仍未测。`;
    }catch(e){$('#sd-connect-state').textContent=`接入失败：${e.message}；不启动任务或切换到PC推理。`;}
    finally{$('#sd-connect').disabled=false;}
  };
  return {apply};
})();
