import http from 'node:http';
import {readFile,writeFile,mkdir,rename} from 'node:fs/promises';
import {randomBytes,timingSafeEqual} from 'node:crypto';
import {dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {setTimeout as delay} from 'node:timers/promises';
import {Store} from './store.mjs';
import {Scheduler,makeJob} from './scheduler.mjs';
import {parseSnapshot,assertTarget} from './racing.mjs';
import {requestBridge,bridgeDir} from './bridge-client.mjs';
import {inspectRegistration} from './verification.mjs';
import {recoverPage} from './recovery-bridge.mjs';
import {recoveryHint} from './recovery.mjs';
import {phoneStatus,enablePhone} from './phone.mjs';
import {installTeamPlan,readTeamPlan,saveTeamPlan,inspectTeamWindow} from './team-plan.mjs';
import {makeTeamAppointment} from './team-appointment.mjs';
import {makeTeamAdapter,openTeamSeriesPage} from './team-browser.mjs';
import {offlineCatalog,scanWeekend,validateChoice,parseTeams} from './endurance.mjs';
import {selectedWeekend,fetchSeasonText,parseSeasonText,scheduleSchema} from './season-catalog.mjs';
import {parseRoster,parseMember,validateMembers} from './team-directory.mjs';
import {fetchSpecialEvents,includeSpecialEvents} from './special-events.mjs';
import {readLicenses,readFullLicensedContent,withCalendarEligibility} from './calendar-eligibility.mjs';
import {VERSION,helpFor,storageInfo,cleanStorage,writableCheck} from './maintenance.mjs';

const root=dirname(fileURLToPath(import.meta.url));
const data=join(root,'data');await mkdir(data,{recursive:true});
let token=await readFile(join(data,'access-token.txt'),'utf8').catch(()=>null);
if(!token){token=randomBytes(32).toString('hex');await writeFile(join(data,'access-token.txt'),token,{mode:0o600});}
token=token.trim();
const store=new Store(join(data,'tasks.sqlite'));
installTeamPlan(store.db);
let scanningTeams=false,catalogScan=null;
const readJson=async name=>JSON.parse(await readFile(join(data,name),'utf8').catch(()=>'null'));
async function catalog(date){
  const w=selectedWeekend(date),cache=await readJson('weekend-'+w.saturday+'.json');
  if(cache?.saturday===w.saturday&&cache.schemaVersion===scheduleSchema)return withSpecials(cache);
  const source=await readFile(join(data,'season-schedule.txt'),'utf8').catch(()=>null);
  if(source){
    try{
      const parsed=parseSeasonText(source,w);
      for(const entry of cache?.series||[]){
        if(!parsed.series.some(x=>x.name===entry.name))parsed.series.push(entry);
      }
      return withSpecials({...parsed,observedAt:(await readJson('season-source.json'))?.observedAt||null});
    }catch(error){
      if(cache?.saturday===w.saturday)return withSpecials(cache,'赛季赛程暂未读到新格式，显示历史缓存。');
      throw error;
    }
  }
  if(cache?.saturday===w.saturday)return withSpecials(cache);
  return withSpecials(offlineCatalog(Date.parse(w.saturday+'T12:00Z')));
}
async function withSpecials(c,error=null){
  const calendar=await readJson('special-calendar.json');
  const result=includeSpecialEvents(c,calendar);
  result.specialError=error||(!calendar?'尚未读取官方特殊赛事日历，请点扫描。':null);
  return withCalendarEligibility(result,await readJson('calendar-eligibility.json'));
}

async function scanCalendarEligibility(date){
  guardTeamNavigation();
  scanningTeams=true;
  try{
    const licenses=readLicenses(await requestBridge('navigate',{target:'Profile'},30000));
    await requestBridge('navigate',{target:'My Content'},30000);
    const inventories={};
    for(const tab of ['cars','tracks']){
      let view=await requestBridge('licensed_tab',{tab},30000);
      if(!view.nodes.some(n=>n.type==='ControlType.Table'))view=await requestBridge('licensed_tab',{tab:'list'},30000);
      inventories[tab]=await readFullLicensedContent(requestBridge,view,tab);
    }
    const next=join(data,'calendar-eligibility.next');
    await writeFile(next,JSON.stringify({observedAt:new Date().toISOString(),licenses,...inventories}));
    await rename(next,join(data,'calendar-eligibility.json'));
    return catalog(date);
  }finally{scanningTeams=false;}
}
async function rescan(date){
  const w=selectedWeekend(date);
  // Each source can refresh even when another official endpoint is unavailable.
  const [seasonResult,specialResult]=await Promise.allSettled([fetchSeasonText(),fetchSpecialEvents()]);
  const finish=async value=>{const c=await value,failures=[seasonResult,specialResult].filter(x=>x.status==='rejected');c.scanReport={status:failures.length===2?'failed':failures.length||c.warnings?.length?'partial':'success',completedAt:new Date().toISOString(),count:c.series.length,failures:failures.map(x=>x.reason.message)};if(failures.length)store.issue('week-scan','SCAN_SOURCE_FAILED',c.scanReport.failures.join('；'));return c;};
  let specialError=null;
  if(specialResult.status==='fulfilled')await writeFile(join(data,'special-calendar.json'),JSON.stringify(specialResult.value));
  else specialError='特殊赛事更新失败：'+specialResult.reason.message+'；保留上次资料，不能据此判断没有比赛。';
  try{
    if(seasonResult.status==='rejected')throw seasonResult.reason;
    const text=seasonResult.value,c=parseSeasonText(text,w);c.observedAt=new Date().toISOString();
    await writeFile(join(data,'season-schedule.txt'),text);
    await writeFile(join(data,'season-source.json'),JSON.stringify({observedAt:c.observedAt}));
    try{
      const weekly=await scanWeekend(Date.parse(w.saturday+'T12:00Z'));
      for(const series of weekly.series)if(!c.series.some(x=>x.name===series.name))c.series.push(series);
    }catch{c.note+=' 该周周报未读到；未据此推断没有比赛。';}
    await writeFile(join(data,'weekend-'+w.saturday+'.json'),JSON.stringify(c));return finish(withSpecials(c,specialError));
  }catch(e){if(seasonResult.status==='fulfilled'){seasonResult.status='rejected';seasonResult.reason=e;}const c=await catalog(w.saturday);return finish(withSpecials({...c,note:'赛季赛程更新失败（'+e.message+'）。显示已缓存赛程，需客户端复核。'+c.note},specialError));}
}
function guardTeamNavigation(){
  if(scanningTeams||navigating||scheduler.running||store.active().length||store.rules().some(x=>x.enabled))throw Error('客户端正在执行或有个人赛预约，请等任务结束后扫描/打开车队赛事。');
}
async function scanMembers(b){
  if(!/^[1-9]\d{0,15}$/.test(b.teamId)||typeof b.teamName!=='string')throw Error('请先选择车队和有效 Team ID');
  const known=await readJson('team-directory.json');
  if(!known?.teams.some(t=>t.id===b.teamId&&t.name===b.teamName))throw Error('请先扫描我的车队并选择，再扫描成员');
  guardTeamNavigation();scanningTeams=true;
  const team={id:b.teamId,name:b.teamName};
  try{
    let raw=await requestBridge('snapshot');
    if(raw.url!=='https://members-ng.iracing.com/web/racing/teams/my-teams')await requestBridge('navigate',{target:'Teams'});
    raw=await requestBridge('team_roster',b);
    const names=parseRoster(raw,team),members=[],started=Date.now();
    for(const memberName of names){
      if(Date.now()-started>240000)throw Error('成员较多，本次扫描超时；未覆盖旧名单，请稍后重试');
      const card=await requestBridge('team_member',{teamId:b.teamId,teamName:b.teamName,memberName});
      members.push(parseMember(card,team,memberName));
    }
    const final=await requestBridge('snapshot');
    if(JSON.stringify(parseRoster(final,team))!==JSON.stringify(names)||new Set(members.map(m=>m.id)).size!==members.length)throw Error('扫描期间车队名单发生变化，请重试');
    const directory={teamId:b.teamId,teamName:b.teamName,members,observedAt:final.observedAt};
    await writeFile(join(data,'members-'+b.teamId+'.json'),JSON.stringify(directory));
    await requestBridge('team_close',{teamId:b.teamId,teamName:b.teamName});
    return directory;
  }finally{scanningTeams=false;}
}
async function openTeamSeries(b){
  const plan=readTeamPlan(store.db);
  if(plan.revision!==b.revision||!plan.series)throw Error('请先保存当前选择');
  guardTeamNavigation();scanningTeams=true;
  try{
    const title=plan.series.replace('Nürburgring','Nurburgring');
    const raw=await openTeamSeriesPage(requestBridge,title);
    if(!/\/official\/series-list\/\d+\/go-racing$/.test(raw.url)||!raw.nodes.some(n=>n.name===title))throw Error('目标系列页面尚未确认，请检查客户端');
    const past=plan.startUtc&&Date.parse(plan.startUtc)<=Date.now();
    return {opened:true,message:past?'已打开系列，但准备单中的目标场次已经过期。请重新选择场次；未提交、未预约，也不会改报下一场。':'已打开目标系列。请在电脑核对场次、选择车辆，然后在开放后点 Register，选择车队及车手并确认。此按钮没有提交报名，也没有创建预约。',url:raw.url};
  }finally{scanningTeams=false;}
}
async function scanTeams(){
  if(scanningTeams||scheduler.running||store.active().length||store.rules().some(x=>x.enabled))throw Error('个人赛正在执行或有预约，请稍后扫描；仍可使用上次名单或手填。');
  scanningTeams=true;let restore=false;
  try{
    let r=await requestBridge('snapshot');
    if(r.url!=='https://members-ng.iracing.com/web/racing/teams/my-teams'){
      restore=/\/official\/series-list\/\d+\/go-racing$/.test(r.url)&&r.nodes.some(n=>n.name==='Global Mazda MX-5 Cup by Fanatec');
      r=await requestBridge('navigate',{target:'Teams'});
    }
    const directory={teams:parseTeams(r),observedAt:r.observedAt};
    await writeFile(join(data,'team-directory.json'),JSON.stringify(directory));return directory;
  }finally{
    try{if(restore)await navigate(true);}finally{scanningTeams=false;}
  }
}
let snapshot=null,lastError=null,lastReadLocked=false;
const adapter={
  async recover(job,allowed){
    if(navigating||scanningTeams)throw Error('客户端页面正在被其他操作使用');
    navigating=true;
    try{snapshot=await recoverPage(job,allowed,requestBridge);lastError=null;return snapshot;}finally{navigating=false;}
  },
  async snapshot(){const raw=await requestBridge('snapshot');snapshot=parseSnapshot(raw);lastReadLocked||=snapshot.lockState==='locked';lastError=null;return snapshot;},
  async register(job){
    const s=await this.snapshot();assertTarget(s,job);
    if(scheduler.paused){const e=Error('执行已暂停');e.code='PAUSED_BEFORE_SUBMIT';throw e;}
    const receipt=await requestBridge('register',{startUtc:job.startUtc,track:job.track,url:`https://members-ng.iracing.com/web/racing/official/series-list/${job.season}/go-racing`});
    store.recordInvoke(job.id,receipt);
    return receipt;
  },
  async verify(job){
    // Verification is deliberately fail-closed until a full matching receipt is available.
    let raw;try{raw=await requestBridge('snapshot');}catch(e){
      store.recordVerification(job.id,{checkedAt:new Date().toISOString(),observedAt:null,confirmed:false,code:'connection_error',message:'读取客户端失败：'+e.message});throw e;
    }
    try{snapshot=parseSnapshot(raw);lastReadLocked||=snapshot.lockState==='locked';lastError=null;}catch(e){lastError=e.message;}
    const report=inspectRegistration(raw,job);store.recordVerification(job.id,report);
    if(report.confirmed)store.recordConfirmation(job.id,raw);return report.confirmed;
  }
};
const scheduler=new Scheduler(store,adapter,Date.now,makeTeamAdapter(requestBridge));
let reading=null,navigating=false;
async function refresh(){
  if(reading)return reading;
  reading=adapter.snapshot().catch(e=>{lastError=e.message;throw e;}).finally(()=>{reading=null;});return reading;
}
async function navigate(skipInitialRead=false){
  if(navigating)throw Error('正在打开客户端页面，请稍后');
  navigating=true;
  try{return await navigateClient(skipInitialRead);}finally{navigating=false;}
}
async function navigateClient(skipInitialRead=false){
  if(!skipInitialRead){try{return await refresh();}catch{}}
  await requestBridge('launch_iracing');
  await requestBridge('navigate',{target:'Official'});
  await requestBridge('search_mazda');
  for(let i=0;i<4;i++){
    try{await requestBridge('open_mazda');return await refresh();}
    catch(e){if(i===3)throw e;await delay(1000);}
  }
}
function executionState(){return {paused:scheduler.paused,draining:scheduler.paused&&scheduler.running,autoRecovery:true,recovering:scheduler.recovery.running,recoveryHint:recoveryHint(store,{paused:scheduler.paused,running:scheduler.recovery.running})};}
async function diagnostics(){
  const checks=[{name:'助手后台',state:'ok',detail:'本机服务已连接 · '+VERSION},{name:'数据目录可写',state:await writableCheck(data)?'ok':'error',detail:'若失败：将完整文件夹解压到个人可写目录，不要在 ZIP 中运行。'}];
  if(scheduler.running||scanningTeams||navigating||store.active().length)checks.push({name:'iRacing 客户端',state:'manual',detail:'有进行中的任务或操作，暂不读取客户端。等任务结束后再次检查。'});
  else try{
    const native=await requestBridge('diagnose');
    checks.push({name:'iRacing 安装位置',state:native.clientFound?'ok':'error',detail:native.clientFound?'已找到客户端。':'在电脑助手窗口点击“选择 iRacing 客户端”，选择 ui\\iRacingUI.exe。'});
    checks.push({name:'iRacing 正在运行',state:native.clientRunning?'ok':'error',detail:native.clientRunning?'客户端进程已启动。':'先正常启动 iRacing 并登录；也可点“打开 Mazda 并读取场次”。'});
    if(native.clientRunning){try{const raw=await requestBridge('snapshot');const logged=/^https:\/\/members-ng\.iracing\.com\/web\/racing\//.test(raw.url||'');checks.push({name:'客户端页面',state:logged?'ok':'manual',detail:logged?'已读取登录后的赛事页面；具体场次资格仍需执行前核对。':'请在电脑客户端完成登录，等待加载，再次检查。'});}catch(e){checks.push({name:'客户端页面',state:'error',detail:e.message,...helpFor(e.message)});}}
  }catch(e){checks.push({name:'原生连接',state:'error',detail:e.message,...helpFor(e.message)});}
  try{const phone=await phoneStatus();checks.push({name:'远程手机 / 其他电脑',state:phone.ready?'ok':'manual',detail:phone.note,...(!phone.ready?helpFor('Tailscale'):{}),url:phone.url});}catch(e){checks.push({name:'远程手机 / 其他电脑',state:'manual',detail:e.message,...helpFor(e.message)});}
  checks.push({name:'电脑不休眠、网络稳定',state:'manual',detail:'请在 Windows 电源设置确认任务期间不休眠；保持联网并保持助手运行。锁屏可以，注销或关机会停止助手。'});
  checks.push({name:'功能范围',state:'manual',detail:'支持 Mazda 个人赛和耐力赛车队预约。车队提交与本人加入各自核对结果。'});
  return {version:VERSION,at:new Date().toISOString(),checks,storage:await storageInfo(data),issueCodes:store.issues().map(({at,scope,code})=>({at,scope,code}))};
}
async function maintenance(){
  if(scheduler.running||scanningTeams||navigating||store.active().length)throw Error('有进行中的任务，等任务结束后再清理临时文件。');
  const result=await cleanStorage(data);store.db.exec('PRAGMA wal_checkpoint(PASSIVE)');return result;
}
function authorized(req){
  const supplied=String(req.headers.authorization||'').replace(/^Bearer /,'');
  const a=Buffer.from(supplied),b=Buffer.from(token);return a.length===b.length&&timingSafeEqual(a,b);
}
async function body(req){
  if(!String(req.headers['content-type']).startsWith('application/json'))throw Error('请求必须为 JSON');
  let text='';for await(const chunk of req){text+=chunk;if(Buffer.byteLength(text)>8192)throw Error('请求过大');}
  return JSON.parse(text||'{}');
}
function send(res,status,value){res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(value));}
const server=http.createServer(async(req,res)=>{
  res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Referrer-Policy','no-referrer');
  res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'");
  const host=String(req.headers.host||'');
  if(!/^(127\.0\.0\.1|localhost):19390$/.test(host)&&!/^[a-z0-9.-]+\.ts\.net(?::443)?$/.test(host))return send(res,403,{error:'Host not allowed'});
  if(req.headers.origin&&req.headers.origin!==`http://${host}`&&req.headers.origin!==`https://${host}`)return send(res,403,{error:'Origin not allowed'});
  const requestUrl=new URL(req.url,'http://localhost'),path=requestUrl.pathname;
  try{
    const files={'/':'index.html','/app.js':'app.js','/team.js':'team.js','/support.js':'support.js','/style.css':'style.css'};
    if(req.method==='GET'&&files[path]){
      const content=await readFile(join(root,'web',files[path]));
      res.writeHead(200,{'Content-Type':path.endsWith('.js')?'text/javascript; charset=utf-8':path.endsWith('.css')?'text/css; charset=utf-8':'text/html; charset=utf-8','Cache-Control':'no-store'});return res.end(content);
    }
    if(path==='/healthz'&&req.method==='GET')return send(res,200,{ok:true});
    if(!authorized(req))return send(res,401,{error:'请输入这台电脑控制台上的访问密钥'});
    if(path==='/api/history'&&req.method==='GET')return send(res,200,store.history({page:Number(requestUrl.searchParams.get('page')||0),status:requestUrl.searchParams.get('status')||'all'}));
    if(path==='/api/history/detail'&&req.method==='GET')return send(res,200,store.historyDetail(requestUrl.searchParams.get('id')));
    if(path==='/api/storage'&&req.method==='GET')return send(res,200,{usage:await storageInfo(data),issues:store.issues(),version:VERSION});
    if(path==='/api/team-options'&&req.method==='GET')return send(res,200,{catalog:await catalog(requestUrl.searchParams.get('weekend')||undefined),directory:await readJson('team-directory.json')});
    if(path==='/api/team-options/members'&&req.method==='GET'){const id=requestUrl.searchParams.get('teamId');if(!/^[1-9]\d{0,15}$/.test(id||''))throw Error('Team ID 无效');return send(res,200,await readJson('members-'+id+'.json'));}
    if((scanningTeams||navigating)&&['/api/team-options/members','/api/team-plan/open','/api/team-options/teams','/api/execution/resume'].includes(path))throw Error('客户端正在被其他操作使用，请稍后');
    if(scanningTeams&&['/api/connect','/api/jobs','/api/rules','/api/team-plan/check','/api/team-appointments','/api/refresh'].includes(path))throw Error('正在读取 iRacing 资料，稍后即可继续操作');
    if(navigating&&['/api/connect','/api/jobs','/api/rules','/api/team-plan/check','/api/refresh','/api/team-options/teams','/api/execution/resume'].includes(path))throw Error('正在打开客户端页面，请等待完成后再执行');
    if(path==='/api/team-plan'&&req.method==='GET')return send(res,200,readTeamPlan(store.db));
    if(path==='/api/team-validation'&&req.method==='GET')return send(res,200,JSON.parse(await readFile(join(root,'practice-validation.json'),'utf8').catch(()=>'{"checks":[],"method":"本机尚未记录车队实测"}')));
    if(path==='/api/status'&&req.method==='GET'){
      const heartbeat=JSON.parse(await readFile(join(bridgeDir,'heartbeat.json'),'utf8').catch(()=> '{}'));
      const acceptance=JSON.parse(await readFile(join(data,'acceptance.json'),'utf8').catch(()=> '{}'));
      return send(res,200,{snapshot,execution:executionState(),lastError:lastError||scheduler.lastError,connected:Date.now()-Date.parse(heartbeat.at)<45000,bridgeBusy:!!heartbeat.operation&&heartbeat.operation!=='idle',bridgeOperationStartedAt:heartbeat.operationStartedAt||null,lockState:heartbeat.lockState||'unknown',lockedReadingObserved:lastReadLocked,jobs:[...new Map([...store.active(),...store.list(30)].map(j=>[j.id,j])).values()],rules:store.rules(),events:store.events(),readiness:{liveRegistrationVerified:store.list().some(j=>j.status==='succeeded'&&j.mode==='live'),lockedReadingVerified:lastReadLocked||acceptance.lockedReading?.status==='user_confirmed',lockedRegistrationVerified:store.hasLockedReceipt()||acceptance.lockedRegistration?.status==='user_confirmed',phoneNetworkVerified:acceptance.phoneNetwork?.status==='user_confirmed'}});
    }
    if(path==='/api/phone'&&req.method==='GET')return send(res,200,await phoneStatus());
    if(req.method!=='POST')return send(res,404,{error:'Not found'});
    const b=await body(req);
    if(path==='/api/diagnostics')return send(res,200,await diagnostics());
    if(path==='/api/storage/clean')return send(res,200,await maintenance());
    if(path==='/api/team-options/weekend'){
      const key=selectedWeekend(b.weekend).saturday;
      if(catalogScan&&catalogScan.key!==key)throw Error('正在扫描另一个周末，请稍后重试');
      if(!catalogScan)catalogScan={key,promise:rescan(key).finally(()=>{catalogScan=null;})};
      return send(res,200,await catalogScan.promise);
    }
    if(path==='/api/team-options/teams')return send(res,200,await scanTeams());
    if(path==='/api/team-options/eligibility')return send(res,200,await scanCalendarEligibility(b.weekend));
    if(path==='/api/team-options/members')return send(res,200,await scanMembers(b));
    if(path==='/api/team-plan/open')return send(res,200,await openTeamSeries(b));
    if(path==='/api/team-appointments'){
      if(b.confirmed!==true)throw Error('请明确确认创建真实车队报名预约。');
      const plan=readTeamPlan(store.db);
      if(plan.revision<=0||b.revision!==plan.revision)throw Error('请先保存或重新读取赛事准备单。');
      const available=await catalog(plan.weekend);
      const directory=/^[1-9]\d{0,15}$/.test(plan.teamId)?await readJson('members-'+plan.teamId+'.json'):null;
      if(readTeamPlan(store.db).revision!==plan.revision)throw Error('准备单已更新，请重新核对。');
      const teams=await readJson('team-directory.json');
      if(readTeamPlan(store.db).revision!==plan.revision)throw Error('准备单已更新，请重新核对。');
      const known=teams?.teams?.filter(t=>t.name===plan.teamName);
      if(known?.length!==1||known[0].id!==plan.teamId)throw Error('请重新扫描我的车队，核对车队名称和 Team ID。');
      const job=store.addTeam(makeTeamAppointment(plan,available.series.find(e=>e.name===plan.series),directory));
      send(res,200,job);
      void scheduler.tick();
      return;
    }
    if(path==='/api/team-appointments/withdraw'){
      if(b.confirmed!==true)throw Error('请先确认退出目标场次的整队报名。');
      if(scanningTeams||navigating)throw Error('iRacing 客户端正在被其他操作使用，请稍候。');
      return send(res,200,await scheduler.withdrawTeam(b.id));
    }
    if(path==='/api/team-plan'){validateChoice(b,await catalog(b.weekend||b.localStart?.slice(0,10)));validateMembers(b,/^[1-9]\d{0,15}$/.test(b.teamId||'')?await readJson('members-'+b.teamId+'.json'):null);return send(res,200,saveTeamPlan(store.db,b));}
    if(path==='/api/team-plan/check'){
      const plan=readTeamPlan(store.db);
      if(!plan.series||plan.revision!==b.revision)throw Error('请先保存或重新读取赛事准备单');
      if(scheduler.running||store.active().length||store.rules().some(x=>x.enabled))throw Error('个人赛有任务或启用中的每周安排。请等任务结束并停用每周安排后再读取车队窗口。');
      return send(res,200,inspectTeamWindow(plan,await requestBridge('snapshot')));
    }
    if(path==='/api/phone/enable'){
      if(!/^(127\.0\.0\.1|localhost):19390$/.test(host))throw Error('请在电脑本机控制台开启手机连接');
      return send(res,200,await enablePhone());
    }
    if(path==='/api/refresh')return send(res,200,await refresh());
    if(path==='/api/recovery/test'){
      if(!scheduler.paused||scheduler.running||store.active().length||store.rules().some(r=>r.enabled))throw Error('试运行前请暂停执行，且不能有未完成任务或启用的每周安排');
      const s=await refresh(),session=s.sessions[0];
      if(Date.parse(session.startUtc)-Date.now()<=300000)throw Error('下一场距开赛不足 5 分钟，稍后再试运行');
      const job=makeJob(s,session,'verify');
      return send(res,200,await adapter.recover(job,()=>scheduler.paused&&!scheduler.running&&!store.active().length&&!store.rules().some(r=>r.enabled)));
    }
    if(path==='/api/execution/pause'){scheduler.pause();return send(res,200,executionState());}
    if(path==='/api/execution/resume'){scheduler.resume();send(res,200,executionState());void scheduler.tick();return;}
    if(path==='/api/connect'){
      if(scheduler.running||(!scheduler.paused&&(store.active().length||store.rules().some(r=>r.enabled))))throw Error('请先暂停预约执行，等待当前操作结束后再打开客户端页面');
      return send(res,200,await navigate());
    }
    if(path==='/api/jobs'){
      if(b.kind!==undefined&&b.kind!=='individual')throw Error('车队准备单请在耐力赛面板保存');
      if(!['live','verify'].includes(b.mode))throw Error('请选择检查或真实报名');
      const s=await refresh(),session=s.sessions.find(x=>x.key===b.key);
      if(!session)throw Error('场次已变化，请刷新后重选');
      if(Date.parse(session.startUtc)-Date.now()<=180000)throw Error('距离开赛不足 3 分钟，不能新建报名');
      const job=store.add(makeJob(s,session,b.mode));
      send(res,200,job);void scheduler.tick();return;
    }
    if(path==='/api/cancel')return send(res,200,store.cancel(b.id));
    if(path==='/api/resolve'){if(b.confirmed!==true)throw Error('请先自行核实 iRacing 客户端');return send(res,200,store.resolve(b.id));}
    if(path==='/api/rules')return send(res,200,{id:store.addRule(b)});
    if(path==='/api/rules/disable'){store.disableRule(b.id);return send(res,200,{ok:true});}
    return send(res,404,{error:'Not found'});
  }catch(e){const help=helpFor(e.message);if(path.startsWith('/api/'))store.issue(path,help.code,e.message);return send(res,400,{error:e.message,help});}
});
server.on('error',e=>{console.error('Server could not start:',e.message);process.exitCode=1;store.close();});
server.listen(19390,'127.0.0.1',()=>console.log('Local console ready on port 19390; authentication required.'));
const timer=setInterval(()=>void scheduler.tick(),10000);timer.unref();
const cleanupTimer=setInterval(()=>void maintenance().catch(()=>{}),3600000);cleanupTimer.unref();
for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>{clearInterval(timer);server.close(()=>{store.close();process.exit(0);});});
