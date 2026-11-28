const $=id=>document.getElementById(id);
function savedKey(){try{return localStorage.getItem('iracing-key')||'';}catch{return '';}}
function rememberKey(value){try{localStorage.setItem('iracing-key',value);}catch{}}
const normalizeKey=value=>value.replace(/[\s\u200B-\u200D\uFEFF]/g,'').toLowerCase();
let key=normalizeKey(location.hash.startsWith('#key=')?decodeURIComponent(location.hash.slice(5)):savedKey());
if(location.hash)history.replaceState(null,'',location.pathname);
if(key)rememberKey(key);
let current=null,selected=null,busy=false,networkFailed=false,authRejected=false,pendingStatus=null;
let latestJobs=[],savingTask=false,watchedJobId=null;
let displayedStatusError=null,executionPaused=false;
try{watchedJobId=localStorage.getItem('iracing-last-job');}catch{}
const statuses={waiting:'等待执行',blocked:'等待条件满足',submitting:'正在提交',uncertain:'结果待核实',succeeded:'报名已确认',checked:'检查通过 · 未报名',cancelled:'预约已取消',expired:'已错过目标场次',reviewed:'已人工核实并结束跟踪'};
const fmt=iso=>new Intl.DateTimeFormat('zh-CN',{timeZone:'America/Toronto',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(iso));
const signupTime=s=>s.estimatedRegistrationOpenUtc||new Date(Date.parse(s.startUtc)-30*60000).toISOString();
const sessionTimes=s=>'预计报名 '+fmt(signupTime(s))+' → 开赛 '+fmt(s.startUtc)+'（多伦多）';
function weeklyTimes(time){
  const [h,m]=time.split(':').map(Number),total=h*60+m-30,minutes=(total+1440)%1440;
  return '预计报名 '+String(Math.floor(minutes/60)).padStart(2,'0')+':'+String(minutes%60).padStart(2,'0')+(total<0?'（前一天）':'')+' → 开赛 '+time+'（多伦多）';
}
function message(text,ok=false){$('message').hidden=false;$('message').textContent=text;$('message').className='message'+(ok?' success':'');}
async function api(path,data,authKey=key){
  const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),path==='/api/status'?12000:path==='/api/team-options/members'?300000:90000);
  try{
    let r;try{r=await fetch(path,{method:data===undefined?'GET':'POST',signal:abort.signal,headers:{Authorization:'Bearer '+authKey,...(data===undefined?{}:{'Content-Type':'application/json'})},body:data===undefined?undefined:JSON.stringify(data)});}catch(e){throw Error(e.name==='AbortError'?'连接超时：先查看任务是否正在提交或待核实，不要重复报名。检查主电脑助手与网络，远程访问还需检查两端 Tailscale。':'无法连接电脑：本机请确认报名助手仍运行；手机或其他电脑请确认两端 Tailscale 已连接，并打开主电脑生成的私人 HTTPS 地址。');}
    let b;try{b=await r.json();}catch{throw Error('服务返回了异常页面，请刷新页面后重试。');}
    if(!r.ok){const e=Error(r.status===401?'访问密钥不匹配，请从电脑控制台重新完整复制密钥。':(b.error||'请求失败')+(b.help?'\n处理方法：\n'+b.help.steps.map((s,i)=>(i+1)+'. '+s).join('\n'):'刚才的操作没有完成，请检查连接。'));e.status=r.status;throw e;}return b;
  }finally{clearTimeout(timer);}
}
function element(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function renderTaskFeedback(){
  const mode=document.querySelector('input[name=mode]:checked')?.value||'verify';
  $('lock-option').hidden=mode!=='live';
  const job=selected?latestJobs.find(j=>j.key===selected&&j.mode===mode):latestJobs.find(j=>j.id===watchedJobId);
  const box=$('task-feedback'),button=$('create');
  button.textContent=mode==='live'?'保存并执行真实报名':'保存检查任务';button.disabled=!selected||busy||networkFailed||authRejected;
  box.hidden=!job&&!savingTask;
  if(savingTask){button.disabled=true;button.textContent='正在保存…';box.textContent='正在保存任务，请稍候…';box.className='task-feedback';return;}
  if(!job)return;
  box.textContent=sessionTimes(job)+' · '+(statuses[job.status]||job.status)+'。'+(job.requireLocked?'仅限锁屏提交。':'')+job.note;
  box.className='task-feedback'+(['succeeded','checked'].includes(job.status)?' success':'');
  if(job.status==='uncertain'&&job.verification)box.textContent+=' 最近核实：'+job.verification.message;
  if(selected){button.disabled=true;button.textContent=({waiting:'预约已保存',blocked:'等待报名条件满足',submitting:'正在报名…',uncertain:'结果核实中',succeeded:'报名已确认',checked:'检查已通过',cancelled:'预约已取消',expired:'场次已过期',reviewed:'跟踪已结束'})[job.status]||'任务已保存';}
}
function renderSnapshot(s){
  current=s;if(!s)return;
  $('track').textContent=s.track.replace(/^(.*) \1$/,'$1')+' · '+s.car;
  $('last-read').textContent=new Intl.DateTimeFormat('zh-CN',{timeZone:'America/Toronto',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date(s.observedAt));
  const box=$('sessions');box.replaceChildren();
  if(!s.sessions.some(x=>x.key===selected&&Date.parse(x.startUtc)>Date.now()+180000))selected=null;
  for(const session of s.sessions){const b=element('button',undefined,'session'+(session.key===selected?' active':''));b.disabled=Date.parse(session.startUtc)<=Date.now()+180000;b.append(element('span','预计报名 '+fmt(signupTime(session))),element('strong','开赛 '+fmt(session.startUtc)),element('span',b.disabled?'已过助手报名缓冲期':session.isNext?(s.registrationOpen?'下一场 · 上次读取已开放报名':'下一场 · 等待开放报名'):'后续场次'));b.onclick=()=>{selected=session.key;renderSnapshot(current);};box.append(b);}
  $('create').disabled=!selected||busy;
  const session=s.sessions.find(x=>x.key===selected);$('selected').textContent=session?sessionTimes(session):'请选择一个实际场次。';
  renderTaskFeedback();
}
function render(data){
  latestJobs=data.jobs;
  executionPaused=!!data.execution?.paused;
  $('execution-status').textContent=executionPaused?(data.execution.draining?'正在暂停：等待当前操作结束，请勿重启客户端':'已暂停：不会执行预约；恢复前请确认客户端正常'):'预约执行已开启';
  $('execution-toggle').textContent=executionPaused?'恢复预约执行':'暂停预约执行';
  $('execution-toggle').disabled=!!data.execution?.draining;
  $('recovery-status').textContent=data.execution?.recoveryHint||(data.execution?.recovering?'正在自动恢复客户端页面，暂不提交报名':'自动恢复待命：保存预约后，在临近执行时检测卡顿。');
  $('connect').disabled=!!data.execution?.draining;
  $('login').hidden=true;$('console').hidden=false;
  $('connection').textContent=data.connected?'电脑已连接':'电脑未连接';
  $('native-status').textContent=data.connected?(data.bridgeBusy?'原生连接运行中 · 正在读取或处理客户端':'原生连接运行中'):'需要启动连接程序';
  $('lock-status').textContent={locked:'已锁屏',unlocked:'已解锁',unobserved:'尚未观察锁屏切换',unknown:'未知'}[data.lockState]||data.lockState;
  if(data.readiness){const r=data.readiness;$('readiness').textContent=[r.phoneNetworkVerified?'手机外网已通过验收':'手机外网待验收',r.lockedReadingVerified?'锁屏读取已通过验收':'锁屏读取待验收',r.lockedRegistrationVerified?'锁屏报名已通过验收':'锁屏报名待确认'].join(' · ');}
  if(data.snapshot)renderSnapshot(data.snapshot);
  else renderTaskFeedback();
  if(data.lastError){displayedStatusError=data.lastError;message(data.lastError);}
  else if(displayedStatusError){if($('message').textContent===displayedStatusError)$('message').hidden=true;displayedStatusError=null;}
  const jobs=$('jobs');jobs.replaceChildren();
  const individual=data.jobs.filter(j=>j.kind!=='team_appointment');
  window.renderTeamAppointments?.(data.jobs.filter(j=>j.kind==='team_appointment'));
  if(!individual.length)jobs.append(element('p','还没有个人赛预约。','empty'));
  for(const j of individual){const row=element('div',undefined,'job'),info=element('div');info.append(element('h4',fmt(j.startUtc)+' · Mazda MX-5'),element('p',sessionTimes(j),'hint'),element('p',(j.mode==='verify'?'仅检查':'真实报名')+' · '+(j.requireLocked?'仅限锁屏提交 · ':'')+j.note));if(j.verification)info.append(element('p','最近核实（'+fmt(j.verification.checkedAt)+'）：'+j.verification.message,'hint'));if(j.recovery)info.append(element('p','自动恢复 '+j.recovery.attempts+'/2（'+fmt(j.recovery.at)+'）：'+j.recovery.message,'hint'));const right=element('div');right.append(element('div',statuses[j.status]||j.status,'status'));if(['waiting','blocked'].includes(j.status)){const b=element('button','取消预约','ghost');b.onclick=()=>act(()=>api('/api/cancel',{id:j.id}),'预约已取消');right.append(b);}if(j.status==='uncertain'){const b=element('button','我已核实客户端，结束跟踪','ghost');b.onclick=()=>act(()=>api('/api/resolve',{id:j.id,confirmed:true}),'已结束跟踪，不代表报名成功；未执行退赛');right.append(b);}row.append(info,right);jobs.append(row);}
  const rules=$('rules');rules.replaceChildren();for(const r of data.rules.filter(x=>x.enabled)){const row=element('div',undefined,'rule');row.append(element('span',`每周${'日一二三四五六'[r.weekday]} ${weeklyTimes(r.time)} · ${r.mode==='live'?'真实报名':'只检查'}`));const b=element('button','停用','ghost');b.onclick=()=>act(()=>api('/api/rules/disable',{id:r.id}),'每周安排已停用；已生成的预约请在任务记录中单独取消');row.append(b);rules.append(row);}
}
async function load(){
  if(!key){$('login').hidden=false;$('connection').textContent='等待连接';return false;}
  if(pendingStatus?.key===key)return pendingStatus.promise;
  const requestedKey=key,entry={key,promise:null};pendingStatus=entry;
  entry.promise=(async()=>{try{
    const data=await api('/api/status',undefined,requestedKey);if(key!==requestedKey)return false;
    if(networkFailed){networkFailed=false;message('电脑连接已恢复',true);}authRejected=false;render(data);return true;
  }catch(e){
    if(key!==requestedKey)return false;
    authRejected=e.status===401;networkFailed=!authRejected;
    $('connection').textContent=authRejected?'密钥不匹配':'连接已中断';
    if(authRejected){$('login').hidden=false;$('console').hidden=true;}
    $('native-status').textContent='尚未连接';$('create').disabled=true;message(e.message);return false;
  }finally{if(pendingStatus===entry)pendingStatus=null;}})();return entry.promise;
}
async function act(fn,success){if(busy)return;busy=true;$('create').disabled=true;try{await fn();message(success,true);await load();}catch(e){message(e.message);}finally{busy=false;renderTaskFeedback();}}
$('login-form').onsubmit=async e=>{
  e.preventDefault();const entered=normalizeKey($('access-key').value);
  if(!/^[a-f0-9]{64}$/.test(entered)){$('connection').textContent='密钥格式不正确';message('请复制完整的 64 位访问密钥；它不是 iRacing 或 Tailscale 密码。');return;}
  key=entered;authRejected=false;rememberKey(key);const button=$('login-submit');button.disabled=true;button.textContent='正在连接…';message('正在连接电脑…');
  try{if(await load())message('已连接电脑',true);}finally{button.disabled=false;button.textContent='连接';}
};
$('execution-toggle').onclick=()=>act(()=>api(executionPaused?'/api/execution/resume':'/api/execution/pause',{}),'执行状态已更新，请查看运行状态');
$('recovery-test').onclick=()=>act(()=>api('/api/recovery/test',{}),'页面恢复试运行完成；没有报名，请手动恢复预约执行');
$('connect').onclick=()=>act(()=>api('/api/connect',{}),'已读取 Mazda 实际场次');
$('refresh').onclick=()=>act(()=>api('/api/refresh',{}),'场次已刷新');
$('create').onclick=async()=>{
  if(busy)return;savingTask=true;renderTaskFeedback();
  await act(async()=>{const job=await api('/api/jobs',{key:selected,mode:document.querySelector('input[name=mode]:checked').value});watchedJobId=job.id;try{localStorage.setItem('iracing-last-job',job.id);}catch{}latestJobs=[job,...latestJobs.filter(j=>j.id!==job.id)];savingTask=false;renderTaskFeedback();$('task-feedback').scrollIntoView({behavior:'smooth',block:'nearest'});},'任务已保存，执行状态会自动更新');
  savingTask=false;renderTaskFeedback();
};
for(const radio of document.querySelectorAll('input[name=mode]'))radio.onchange=renderTaskFeedback;
function weeklyPreview(){$('weekly-preview').textContent=weeklyTimes($('weekly-time').value||'20:00');}
$('weekly-time').oninput=weeklyPreview;weeklyPreview();
$('weekly-form').onsubmit=e=>{e.preventDefault();void act(()=>api('/api/rules',{weekday:Number($('weekday').value),time:$('weekly-time').value,mode:$('weekly-mode').value}),'每周安排已保存');};
$('show-key').onclick=()=>{const e=$('key-display');e.hidden=!e.hidden;e.textContent=e.hidden?'':key;};
void load();setInterval(()=>{if(!document.hidden&&!busy&&key&&!authRejected)void load();},2000);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&key&&!authRejected)void load();});

function showPhone(s){$('phone-status').textContent=s.note;const link=$('phone-url');link.hidden=!s.url;if(s.url){link.href=s.url;link.textContent=s.url;}}
$('phone-check').onclick=()=>act(async()=>showPhone(await api('/api/phone')),'手机配置检查已完成');
$('phone-enable').onclick=()=>act(async()=>showPhone(await api('/api/phone/enable',{})),'私人手机入口已配置；请使用 iPhone 蜂窝网络验证');
