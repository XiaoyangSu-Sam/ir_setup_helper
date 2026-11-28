import {setTimeout as delay} from 'node:timers/promises';

const official='https://members-ng.iracing.com';
const raceUrl=/^https:\/\/members-ng\.iracing\.com\/web\/racing\/official\/series-list\/\d+\/go-racing$/;
const profileUrl=official+'/web/racing/profile';
const toronto='America/Toronto';
const timeFormat=new Intl.DateTimeFormat('en-US',{timeZone:toronto,hour:'numeric',minute:'2-digit',hour12:true});
const clockFormat=new Intl.DateTimeFormat('en-US',{timeZone:toronto,hour:'numeric',minute:'2-digit',second:'2-digit',hour12:true});
const clean=value=>String(value||'').replace(/\ufffc/g,'').replace(/\s+/g,' ').trim();
const label=node=>clean(node?.text)||clean(node?.name);
const type=(node,kind)=>node?.type==='ControlType.'+kind;
const norm=value=>clean(value).normalize('NFD').replace(/\p{Diacritic}/gu,'').replace(/[^\p{L}\p{N}]/gu,'').toLowerCase();
const equals=(node,value)=>label(node)===value||clean(node?.name)===value||clean(node?.value)===value;
const includes=(nodes,value)=>nodes.some(n=>equals(n,value));
const one=nodes=>nodes.length===1?nodes[0]:null;
const action=node=>node?.enabled&&(node.invoke||node.patterns?.some(p=>/ExpandCollapsePattern|SelectionItemPattern/.test(p)));
const button=(nodes,name)=>one(nodes.filter(n=>type(n,'Button')&&action(n)&&equals(n,name)));
const heading=(nodes,name)=>one(nodes.filter(n=>type(n,'Text')&&equals(n,name)));
const localTime=(clock,ms)=>clean(clock.format(ms));

function descended(nodes,root){
  const parents=new Set([root.index]);
  return nodes.filter(n=>{
    if(!parents.has(n.parent))return false;
    parents.add(n.index);
    return true;
  });
}

function ancestors(nodes,node){
  const parents=[];
  for(let cursor=node;cursor&&cursor.parent>=0&&parents.length<12;){
    const index=cursor.parent;
    cursor=nodes[index]?.index===index?nodes[index]:nodes.find(n=>n.index===index);
    if(cursor&&!type(cursor,'Document'))parents.push(cursor);
  }
  return parents;
}

function sec(clock){
  const m=/^(\d{1,2}):(\d{2})(?::(\d{2}))? ([AP]M)$/.exec(clock);
  return m?(+m[1]%12+(m[4]==='PM'?12:0))*3600+ +m[2]*60+ +(m[3]||0):NaN;
}

function validateSnapshot(raw,now){
  if(!raw?.ok||!Array.isArray(raw.nodes)||!Number.isFinite(Date.parse(raw.observedAt))||
    Math.abs(now-Date.parse(raw.observedAt))>15000)throw Error('客户端快照已过期。');
  if(/disconnected|connection lost|failed to connect/i.test(raw.text||''))throw Error('iRacing 客户端连接异常。');
}

export function raceContext(raw,job,now=Date.now(),requireOpen=true){
  validateSnapshot(raw,now);
  const {nodes}=raw;
  const title=one(nodes.filter(n=>type(n,'Text')&&norm(n.name)===norm(job.series)));
  if(!raceUrl.test(raw.url)||!title)throw Error('客户端未打开唯一的目标系列。');
  const next=one(nodes.filter(n=>type(n,'Text')&&/^Next Race @ /i.test(clean(n.name))));
  const team=nodes.find(n=>type(n,'Text')&&n.index>title.index&&n.index<(next?.index??0)&&/^Team\s*\(\d+\s*[-–]\s*\d+\)$/i.test(label(n)));
  if(!next||!team||norm(clean(next.name).replace(/^Next Race @ /i,''))!==norm(job.track))
    throw Error('无法核对下一场的赛道布局和车队赛标记。');
  const end=nodes.find(n=>n.index>next.index&&type(n,'Text')&&equals(n,'Race Duration'));
  const after=nodes.find(n=>n.index>(end?.index??next.index)&&type(n,'Text')&&equals(n,'Available Sessions'));
  const timeRows=nodes.slice(next.index+1,end?.index??next.index).filter(n=>type(n,'Text'));
  const raceLabel=one(timeRows.filter(n=>/^(?:[A-Z][a-z]{2} \d+, \d{4}, )?\d{1,2}:\d{2} [AP]M$/.test(label(n))));
  const start=Date.parse(job.startUtc);
  const absolute=localTime(new Intl.DateTimeFormat('en-US',{timeZone:toronto,month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',hour12:true}),start);
  if(!raceLabel||![localTime(timeFormat,start),absolute].includes(label(raceLabel)))throw Error('客户端下一场开赛时间与准备单不一致。');
  const open=heading(timeRows,'Open Now');
  const timer=timeRows.find(n=>/^\d{1,2}:\d{2}(?::\d{2})?$/.test(label(n)));
  const remaining=timer?label(timer).split(':').reduce((total,part)=>total*60+Number(part),0):NaN;
  const clock=clean(raw.text?.match(/\b\d{1,2}:\d{2}:\d{2}\s[AP]M\b/)?.[0]);
  const diff=Math.abs(sec(clock)-sec(localTime(clockFormat,now)));
  const countdownMatches=open&&Math.abs(remaining-(start-now)/1000)<=35&&Math.min(diff,86400-diff)<=35;
  if(requireOpen&&(!countdownMatches||now>=start))throw Error('报名窗口尚未在客户端开放，或时钟与目标场次不符。');
  if(!requireOpen&&!countdownMatches&&label(raceLabel)!==absolute)
    throw Error('客户端未显示足以确认该场次日期的时间。');
  const register=button(nodes.slice(end?.index??0,after?.index??nodes.length),'Register');
  const anchors=[title,next,team,raceLabel,...(requireOpen?[open]:[])];
  return {raw,nodes,register,anchors};
}

function carChoice(context){
  const nodes=context.nodes;
  const chosen=heading(nodes,'Selected Car');
  const favorite=one(nodes.filter(n=>n.id?.startsWith('favorite_cars-')));
  if(chosen&&favorite){
    const [inner,menu,card]=ancestors(nodes,favorite);
    if(card&&descended(nodes,card).includes(chosen)){
      return {current:one(nodes.filter(n=>n!==chosen&&n.parent===card.index&&type(n,'Text'))),
        menu:one(nodes.filter(n=>n.parent===menu.index&&n.id?.startsWith('menu-button-')&&action(n)))};
    }
  }
  const none=heading(nodes,'No Car Selected...');
  if(!none)return {};
  const menu=one(nodes.filter(n=>n.index>none.index&&n.index<none.index+7&&n.id?.startsWith('menu-button-')&&action(n)));
  return {current:none,menu};
}

function wizard(nodes){
  const title=heading(nodes,'Team Registration');
  if(!title)return null;
  for(const root of ancestors(nodes,title)){
    const scope=descended(nodes,root);
    if(['Team Setup','Registered Teams','Join a Registered Team'].some(name=>includes(scope,name)))return {title,scope};
  }
  throw Error('无法划定 Team Registration 窗口范围。');
}

function dropOption(nodes,value){
  const options=new Map();
  for(const name of nodes.filter(n=>equals(n,value))){
    const chain=[name,...ancestors(nodes,name)];
    if(!chain.some(n=>/^(menu-list-|popover-content-|listbox)/.test(n.id||'')||type(n,'Menu')))continue;
    const control=chain.find(n=>action(n)&&(type(n,'MenuItem')||type(n,'ListItem')||type(n,'Button')));
    if(control)options.set(control.index,{control,name});
  }
  return one([...options.values()]);
}

function rosterProof(w,names){
  const countNode=w.scope.find(n=>/^\d+ Drivers Selected$/i.test(label(n)));
  const count=countNode?label(countNode).match(/^\d+/)[0]:undefined;
  const table=one(w.scope.filter(n=>type(n,'Table')&&includes(descended(w.scope,n),'Display Name')));
  // The roster summary and the table both have to agree before registration.
  if(!table)return {names:[],verified:names.length===0&&!count};
  const rows=descended(w.scope,table);
  const present=names.filter(name=>rows.some(n=>type(n,'Text')&&equals(n,name)));
  if(count!==undefined)return {names:present,verified:Number(count)===names.length&&present.length===names.length,anchor:table,countNode};
  const cells=rows.filter(n=>type(n,'DataItem')&&label(n)&&!equals(n,'Display Name'));
  return {names:present,verified:cells.length===names.length&&names.every(name=>includes(cells,name)),anchor:table};
}

function teamMatch(w,job){
  if(!w)return null;
  const registered=heading(w.scope,'Registered Teams')||heading(w.scope,'Join a Registered Team');
  if(!registered)return null;
  const section=ancestors(w.scope,registered).find(root=>includes(descended(w.scope,root),job.teamName));
  if(!section)return null;
  const scope=descended(w.scope,section);
  const name=heading(scope,job.teamName);
  if(!name)return null;
  for(const row of ancestors(w.scope,name)){
    const group=descended(w.scope,row);
    if(includes(group,'Registered Teams')||includes(group,'Join a Registered Team'))break;
    const markers=group.filter(n=>equals(n,'Register as Driver')||
      equals(n,'Registered as Driver')||equals(n,'You are registered as a driver'));
    if(!markers.length)continue;
    if(!includes(group,job.car))return null;
    const teamIds=group.map(n=>/favorite_teams--(\d+)/.exec(n.id||'')?.[1]).filter(Boolean);
    if(teamIds.some(id=>id!==job.teamId))return null;
    const markerBranches=new Set(markers.map(marker=>[marker,...ancestors(group,marker)].findLast(n=>n.parent===row.index)?.index));
    if(markerBranches.size!==1)return null;
    const join=button(group,'Register as Driver');
    const joined=includes(group,job.ownDriverName)&&job.ownDriverName&&
      (heading(group,'Registered as Driver')||heading(group,'You are registered as a driver'));
    if(join||joined||includes(group,'Register as Driver'))return {name,car:group.find(n=>equals(n,job.car)),join,joined,group};
  }
  return null;
}

export function receipt(raw,job,phase,now=Date.now()){
  try{
    const context=raceContext(raw,job,now,false);
    const registered=teamMatch(wizard(context.nodes),job);
    if(phase==='team')return !!registered;
    return !!registered?.joined;
  }catch{return false;}
}

export async function openTeamSeriesPage(request,series,allowed=()=>true){
  const title=series.replace('Nürburgring','Nurburgring');
  const step=async(op,parameters)=>{
    if(!allowed())throw Error('预约已取消、暂停或开赛。');
    return request(op,parameters);
  };
  await step('launch_iracing');
  await step('navigate',{target:'Official'});
  await step('search_series',{series:title});
  return step('open_series',{series:title});
}

export function makeTeamAdapter(request,now=Date.now){
  function command(context,job,node,phase,extra=[]){
    if(!node||!action(node))throw Error('客户端未提供唯一且可操作的控件。');
    const identity=n=>({index:n.index,parent:n.parent,type:n.type,id:n.id||'',name:n.name||'',text:n.text||'',value:n.value||''});
    return {phase,startUtc:job.startUtc,url:context.raw.url,node:identity(node),
      anchors:[...new Set([...context.anchors,...extra].filter(Boolean))].map(identity)};
  }
  async function read(){return request('snapshot');}

  async function prepare(job,phase,allowed){
    const operate=async(context,node,extra)=>{
      if(!allowed())throw Error('预约已取消、暂停或开赛。');
      const result=await request('team_action',command(context,job,node,'prepare',extra));
      if(!result.invoked)throw Error(result.reason);
      await delay(550);
      return read();
    };
    const select=async(context,value,extra)=>{
      const option=dropOption(context.nodes,value);
      if(!option)throw Error('选择列表未显示唯一的目标选项。');
      return operate(context,option.control,[...extra,option.name]);
    };
    let raw=await read();
    if(phase==='driver'&&receipt(raw,job,phase,now()))return {confirmed:true};
    if(phase==='driver'){
      if(!allowed())throw Error('预约已取消、暂停或开赛。');
      const profile=await request('navigate',{target:'Profile'});
      validateSnapshot(profile,now());
      const match=heading(profile.nodes,job.ownDriverName);
      if(profile.url!==profileUrl||!match)throw Error('当前 iRacing 个人资料与准备单本人身份不匹配。');
      raw=await openTeamSeriesPage(request,job.series,allowed);
    }else if(!raceUrl.test(raw.url)||!raw.nodes.some(n=>type(n,'Text')&&norm(n.name)===norm(job.series))){
      if(/\bWithdraw\b|You may join your session\./i.test(raw.text||''))throw Error('客户端已有其他报名。');
      raw=await openTeamSeriesPage(request,job.series,allowed);
    }
    let context=raceContext(raw,job,now());
    const currentCar=carChoice(context);
    if(!equals(currentCar.current,job.car)){
      raw=await operate(context,currentCar.menu,[currentCar.current]);
      context=raceContext(raw,job,now());
      raw=await select(context,job.car,[currentCar.current]);
      context=raceContext(raw,job,now());
    }
    let current=carChoice(context).current;
    if(!equals(current,job.car))throw Error('所选车辆未匹配目标。');
    if(!wizard(context.nodes)){
      const eligible=heading(context.nodes,'You are eligible to race in this series!');
      if(!eligible)throw Error('客户端尚未确认所选车辆和赛道的参赛资格。');
      raw=await operate(context,context.register,[current,eligible]);
      context=raceContext(raw,job,now());
    }
    let form=wizard(context.nodes);
    if(!form)throw Error('Team Registration 窗口尚未打开。');
    let registered=teamMatch(form,job);
    if(phase==='driver'){
      const joinList=button(form.scope,'Join a Registered Team');
      if(!registered&&joinList){
        raw=await operate(context,joinList,[form.title,current]);
        context=raceContext(raw,job,now());
        form=wizard(context.nodes);
        registered=teamMatch(form,job);
      }
      if(registered?.joined)return {confirmed:true};
      if(!registered?.join)throw Error('尚未找到该场次、该车队和车辆对应的车手加入按钮。');
      return command(context,job,registered.join,'driver',[form.title,registered.name,registered.car]);
    }
    if(registered){
      if(job.driverNames.length&&!rosterProof({scope:registered.group},job.driverNames).verified)
        throw Error('该车队已经报名，客户端未显示可核对的已申报车手名单。');
      return {confirmed:true};
    }
    const selectedTeam=()=>form.scope.find(n=>equals(n,'Selected Team: '+job.teamName)||type(n,'ComboBox')&&equals(n,job.teamName));
    if(!selectedTeam()){
      const picker=one(form.scope.filter(n=>action(n)&&
        (['Select Team','Select a Team','Select a team'].some(s=>equals(n,s))||/^Selected Team: /i.test(label(n)))));
      raw=await operate(context,picker,[form.title]);
      context=raceContext(raw,job,now());
      raw=await select(context,job.teamName,[form.title]);
      context=raceContext(raw,job,now());
      form=wizard(context.nodes);
    }
    if(!form||!selectedTeam())throw Error('报名窗口未确认选中的车队。');
    const verifyTeam=button(form.scope,'Verify Team');
    if(verifyTeam){
      raw=await operate(context,verifyTeam,[form.title,selectedTeam()]);
      context=raceContext(raw,job,now());
      form=wizard(context.nodes);
    }
    for(const name of job.driverNames){
      if(!form||!selectedTeam())throw Error('车队选择已变化。');
      if(rosterProof(form,job.driverNames).names.includes(name))continue;
      raw=await operate(context,button(form.scope,'Add a Driver'),[form.title,selectedTeam()]);
      context=raceContext(raw,job,now());
      raw=await select(context,name,[form.title]);
      context=raceContext(raw,job,now());
      form=wizard(context.nodes);
    }
    current=carChoice(context).current;
    if(!form||!selectedTeam()||!equals(current,job.car))throw Error('车辆或车队确认信息已变化。');
    const roster=rosterProof(form,job.driverNames);
    if(!roster.verified)throw Error('报名窗口中的申报码单无法与准备单逐项核对。');
    const names=roster.anchor?descended(context.nodes,roster.anchor).filter(n=>job.driverNames.some(name=>equals(n,name))):[];
    return command(context,job,button(form.scope,'Register Team'),'team',[form.title,selectedTeam(),current,roster.anchor,roster.countNode,...names]);
  }
  return {
    prepare,
    submit:async(job,phase,prepared)=>{
      const result=await request('team_action',prepared);
      if(result.invoked)await delay(900);
      return result;
    },
    verify:async(job,phase)=>receipt(await read(),job,phase,now())
  };
}
