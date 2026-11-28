const wantsTeam=kind=>kind!=='join_team';
const wantsDriver=kind=>kind!=='team_registration';
const ready=status=>status==='waiting'||status==='blocked';
const stepNames={car:'选车',team:'选择车队',roster:'申报车手',verify:'Verify Team',submit:'整队报名'};

export function teamCheckFrom(job){
  const published=Date.parse(job.registrationOpenUtc);
  const start=Date.parse(job.startUtc);
  return job.registrationKind==='confirmed'&&published<start?published:start-60*60000;
}

export function makeTeamAppointment(plan,event,directory,now=Date.now()){
  if(!['team_then_join','team_registration','join_team'].includes(plan.kind)||plan.missing?.length||
     !plan.teamName||!/^\d+$/.test(plan.teamId||''))throw Error('请先保存完整准备单。');
  const slot=event?.slotDetails?.find(s=>s.startUtc===plan.startUtc);
  if(event?.name!==plan.series||event.teamRace!==true||!event.track||!slot||
     !event.cars?.includes(plan.car)||Date.parse(slot.startUtc)<=now)
    throw Error('请选择尚未开赛、场次和车辆均有官方资料的车队赛。');
  if(directory?.teamId!==plan.teamId||directory.teamName!==plan.teamName)
    throw Error('请扫描所选车队成员，核对队名和 Customer ID。');
  const roster=wantsTeam(plan.kind)?plan.roster:[];
  if(wantsTeam(plan.kind)&&(plan.declaration==='unknown'||
     (event.declaration==='required'&&plan.declaration!=='required')||
     (plan.declaration==='required'&&roster.length<(event.minDrivers||1))||
     (event.maxDrivers&&roster.length>event.maxDrivers)))
    throw Error('申报规则或车手人数不符合本场赛事要求。');
  const member=id=>{
    const matches=directory.members.filter(m=>m.id===id&&m.name?.trim());
    if(matches.length!==1||directory.members.filter(m=>m.name===matches[0].name).length!==1)
      throw Error('车手身份无法唯一核对，请重新扫描车队成员。');
    return matches[0].name;
  };
  const driverNames=roster.map(member);
  const ownDriverName=wantsDriver(plan.kind)?member(plan.ownDriverId):'';
  if(plan.kind==='team_then_join'&&plan.declaration==='required'&&!roster.includes(plan.ownDriverId))
    throw Error('请把本人列入申报名单。');
  return {...slot,kind:'team_appointment',mode:'live',bookingMode:plan.kind,revision:plan.revision,
    key:`team:${plan.series}:${plan.startUtc}:${plan.teamId}:${wantsTeam(plan.kind)?'team':'driver'}`,series:plan.series,track:event.track,car:plan.car,
    teamId:plan.teamId,teamName:plan.teamName,roster,driverNames,ownDriverId:plan.ownDriverId,ownDriverName,
    declaration:plan.kind==='join_team'?event.declaration:plan.declaration,createdAt:new Date(now).toISOString(),
    teamProgress:{team:wantsTeam(plan.kind)?'waiting':'not_requested',driver:wantsDriver(plan.kind)?'waiting':'not_requested'}};
}

export async function runTeamAppointment(store,adapter,job,now=Date.now,paused=()=>false){
  const progress={...job.teamProgress};
  const steps={...job.teamSteps};
  const phase=['team','driver'].find(key=>['waiting','unconfirmed'].includes(progress[key]));
  if(!phase||paused())return;
  const start=Date.parse(job.startUtc);
  const state=(status,note)=>store.updateTeam(job.id,status,note,progress,steps);
  let currentStep;
  const report=(key,result)=>{
    const live=store.get(job.id);
    if(phase!=='team'||!stepNames[key]||!ready(live?.status)||paused())return;
    currentStep=key;
    steps[key]=result;
    state(live.status,stepNames[key]+(result==='checking'?' · 正在核对':' · 已确认'));
  };
  const description=phase==='team'?'整队报名':'本人加入';
  const confirm=()=>{
    progress[phase]='confirmed';
    if(phase==='team')steps.submit='confirmed';
    if(phase==='team'&&progress.driver==='waiting')state('waiting','整队报名已确认；等待核对并加入本人。');
    else state('succeeded',job.bookingMode==='team_then_join'?'整队报名和本人加入均已确认。':description+'已确认。');
  };
  if(job.status==='uncertain'){
    try{if(await adapter.verify(job,phase))confirm();}catch{/* Pending evidence stays pending. */}
    return;
  }
  if(!ready(job.status)||now()<teamCheckFrom(job))return;
  if(now()>=start){state('expired','已到目标场次开赛时间，剩余步骤未提交。');return;}
  if(job.status==='waiting')state('waiting',description+'正在核对 iRacing 报名窗口。');
  let prepared;
  try{prepared=await adapter.prepare(job,phase,()=>!paused()&&ready(store.get(job.id)?.status)&&now()<start,report);}
  catch(error){
    if(error.code==='TEAM_WINDOW_WAIT'){
      if(ready(store.get(job.id)?.status))state('waiting',error.message);
      return 'window_pending';
    }
    if(currentStep&&steps[currentStep]==='checking')steps[currentStep]='blocked';
    if(ready(store.get(job.id)?.status))state('blocked',description+'等待核对：'+error.message);
    return;
  }
  if(!ready(store.get(job.id)?.status)||paused())return;
  if(prepared.confirmed){confirm();return;}
  if(now()>=start){state('expired','已到目标场次开赛时间，剩余步骤未提交。');return;}
  progress[phase]='unconfirmed';
  if(phase==='team')steps.submit='checking';
  state('submitting','正在提交'+description+'。');
  try{
    const result=await adapter.submit(job,phase,prepared);
    if(result?.invoked===false){
      progress[phase]='waiting';
      if(phase==='team')steps.submit='blocked';
      state('blocked',result.reason||description+'执行前条件已变化。');
      return;
    }
    if(await adapter.verify(job,phase)){confirm();return;}
    if(phase==='team')steps.submit='unconfirmed';
    state('uncertain',description+'已提交，正在等待 iRacing 确认。若客户端出现新的确认步骤，请查看 iRacing；助手只核实结果。');
  }catch(error){
    if(phase==='team')steps.submit='unconfirmed';
    state('uncertain',description+'结果待核实：'+error.message);
  }
}
