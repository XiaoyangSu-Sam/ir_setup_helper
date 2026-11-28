(()=>{
  const el=id=>document.getElementById(id),stamp=v=>new Intl.DateTimeFormat('zh-CN',{timeZone:'America/Toronto',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date(v));
  let page=0,currentHistory=null,report=null;
  const row=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
  const mb=n=>(n/1048576).toFixed(2)+' MB';
  function download(name,data){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  async function action(button,fn){button.disabled=true;try{await fn();}catch(e){message(e.message);}finally{button.disabled=false;}}
  async function history(){
    currentHistory=await api('/api/history?page='+page+'&status='+encodeURIComponent(el('history-status').value));
    const box=el('history-list');box.replaceChildren();el('history-page').textContent='共 '+currentHistory.total+' 条 · 第 '+(page+1)+' 页，每页 25 条';
    el('history-prev').disabled=page===0;el('history-next').disabled=(page+1)*25>=currentHistory.total;
    if(!currentHistory.jobs.length)box.append(row('p','没有符合条件的报名记录。'));
    for(const j of currentHistory.jobs){
      const card=document.createElement('details'),title=row('summary',stamp(j.startUtc)+' · '+(j.series||'Mazda')+' · '+(statuses[j.status]||j.status));card.append(title,row('p',j.track||''),row('p',j.note));
      const detail=row('div','展开后读取处理时间线。');card.append(detail);let loaded=false;
      card.addEventListener('toggle',async()=>{if(!card.open||loaded)return;try{const r=await api('/api/history/detail?id='+encodeURIComponent(j.id));detail.replaceChildren();detail.append(row('p','任务编号：'+j.id+' · '+(j.mode==='live'?'真实报名':'仅检查')));for(const event of r.events)detail.append(row('p',stamp(event.at)+' · '+(statuses[event.status]||event.status)+' · '+event.note));if(!r.job.teamProgress)detail.append(row('p',r.evidence?'有提交/确认记录；以任务最终核实状态为准。':'没有记录到完整的提交凭据。'));const exportButton=row('button','导出这条记录（含赛事资料）');exportButton.onclick=()=>download('registration-'+j.id+'.json',r);detail.append(exportButton);loaded=true;}catch(e){detail.textContent=e.message;}});
      box.append(card);
    }
  }
  el('history-load').onclick=()=>action(el('history-load'),async()=>{page=0;await history();});
  el('history-status').onchange=()=>{page=0;void action(el('history-load'),history);};
  el('history-prev').onclick=()=>{page=Math.max(0,page-1);void action(el('history-load'),history);};
  el('history-next').onclick=()=>{page++;void action(el('history-load'),history);};
  el('history-export').onclick=()=>{if(currentHistory)download('registration-history-page-'+(page+1)+'.json',currentHistory);else message('请先读取历史。');};
  el('diagnostics-run').onclick=()=>action(el('diagnostics-run'),async()=>{
    const box=el('diagnostics-result');box.textContent='正在逐项检查，请稍候；不会提交报名。';
    report=await api('/api/diagnostics',{});box.replaceChildren();
    box.append(row('p','版本 '+report.version+' · '+stamp(report.at)+'（多伦多）。按下面尚未满足的项目操作，再点重新检查。'));
    for(const c of report.checks){const item=document.createElement('div');item.append(row('strong',(c.state==='ok'?'✓ 已通过：':c.state==='error'?'✕ 未满足：':'○ 待你确认：')+c.name),row('p',c.detail));if(c.steps){const list=document.createElement('ol');for(const s of c.steps)list.append(row('li',s));item.append(list);}box.append(item);}
    el('diagnostics-export').disabled=false;
  });
  el('diagnostics-export').onclick=()=>{if(report)download('assistant-diagnostics.json',{version:report.version,at:report.at,checks:report.checks.map(c=>({name:c.name,state:c.state,code:c.code||null})),storage:report.storage,issues:report.issueCodes});};
  async function storage(){const s=await api('/api/storage');el('storage-result').textContent='运行数据 '+mb(s.usage.total)+'；历史数据库 '+mb(s.usage.history)+'，日志 '+mb(s.usage.logs)+'，赛程缓存 '+mb(s.usage.cache)+'，其他 '+mb(s.usage.other)+'。历史和名单不会被清理。';const box=el('issue-list');box.replaceChildren();for(const i of s.issues)box.append(row('p',stamp(i.at)+' · '+i.code+' · '+i.note));if(!s.issues.length)box.append(row('p','尚无已记录的操作故障。'));}
  el('storage-check').onclick=()=>action(el('storage-check'),storage);
  el('storage-clean').onclick=()=>action(el('storage-clean'),async()=>{const r=await api('/api/storage/clean',{});message('清理完成：'+r.files+' 个过期临时文件，释放 '+mb(r.bytes)+'。报名历史、名单和密钥保留。',true);await storage();});
})();
