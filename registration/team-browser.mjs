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

function liveRaceCountdown(text,headline){
  const rows=String(text||'').split(/\r?\n/).map(clean);
  const first=rows.indexOf(clean(headline));
  const end=rows.findIndex((row,index)=>index>first&&/^Race Duration\b/.test(row));
  if(first<0||end<0)return NaN;
  const timer=one(rows.slice(first+1,end).map(row=>/^(\d{1,2}:\d{2}(?::\d{2})?) Open Now$/.exec(row)).filter(Boolean));
  return timer?timer[1].split(':').reduce((total,part)=>total*60+Number(part),0):NaN;
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
  const remaining=liveRaceCountdown(raw.text,next.name);
  const clock=clean(raw.text?.match(/\b\d{1,2}:\d{2}:\d{2}\s[AP]M\b/)?.[0]);
  const diff=Math.abs(sec(clock)-sec(localTime(clockFormat,now)));
  const countdownMatches=open&&Math.abs(remaining-(start-now)/1000)<=35&&Math.min(diff,86400-diff)<=35;
  if(requireOpen&&(!open||now>=start))throw Error('报名窗口尚未在客户端开放，或目标场次已开赛。');
  if(requireOpen&&!countdownMatches)throw Error('iRacing 的实时倒计时或时钟无法核对到目标场次。');
  if(!requireOpen&&!countdownMatches&&label(raceLabel)!==absolute)
    throw Error('客户端未显示足以确认该场次日期的时间。');
  const register=button(nodes.slice(end?.index??0,after?.index??nodes.length),'Register');
  const anchors=[title,next,team,raceLabel,...(requireOpen?[open]:[])];
  return {raw,nodes,register,anchors};
}

function selectedCar(context){
  const {nodes}=context;
  if(context.formRoot){
    const scope=descended(nodes,context.formRoot);
    const setup=heading(scope,'Team Setup');
    return heading(scope.filter(n=>n.index>(setup?.index??-1)),context.raw.teamTarget.car);
  }
  const chosen=heading(nodes,'Selected Car');
  const favorite=one(nodes.filter(n=>n.id?.startsWith('favorite_cars-')));
  if(chosen&&favorite){
    const card=ancestors(nodes,favorite)[2];
    if(card&&descended(nodes,card).includes(chosen)){
      return one(nodes.filter(n=>n!==chosen&&n.parent===card.index&&type(n,'Text')));
    }
  }
  return null;
}

function raceCarPicker(nodes,car){
  const modal=one(nodes.filter(n=>n.id==='select-car-modal-modal-dialog'));
  if(!modal)return null;
  const scope=descended(nodes,modal);
  const title=heading(scope,'Select a car');
  const name=heading(scope,car);
  const card=name&&nodes[name.parent];
  if(!title||!card?.id?.startsWith('series-select-car-modal-car-card-')||card.parent!==modal.index||!action(card))
    throw Error('选车窗口没有显示唯一的目标车辆。');
  if(descended(scope,card).some(n=>/\$\s*\d|\b(?:Buy|Purchase|Add to Cart)\b/i.test(label(n))))
    throw Error('报名窗口提示需要购买所选车辆。');
  const next=one(scope.filter(n=>n.parent===modal.index&&type(n,'Hyperlink')&&action(n)&&
    clean(label(n).replace(/\p{Co}/gu,''))==='Continue'));
  return {modal,title,name,card,next};
}

function flowContext(raw,job,now,requireOpen=true){
  validateSnapshot(raw,now);
  const {nodes,teamTarget}=raw;
  const formRoot=one(nodes.filter(n=>type(n,'Window')&&equals(n,'Go Racing')&&n.id?.startsWith('chakra-modal-')&&
    heading(descended(nodes,n),'Team Registration')));
  if(!formRoot)return raceContext(raw,job,now,requireOpen);
  if(!raceUrl.test(raw.url)||!teamTarget||teamTarget.windowId!==formRoot.id||teamTarget.car!==job.car||
     teamTarget.series!==job.series||teamTarget.track!==job.track||
     Date.parse(teamTarget.startUtc)!==Date.parse(job.startUtc)||now>=Date.parse(job.startUtc))
    throw Error('报名窗口无法与预约场次绑定，请关闭手动打开的表单后重试。');
  return {raw,nodes,formRoot,anchors:[formRoot]};
}

function wizard(nodes){
  const title=heading(nodes,'Team Registration');
  if(!title)return null;
  for(const root of ancestors(nodes,title)){
    const scope=descended(nodes,root);
    if(['Team Setup','Registered Teams','Join a Registered Team'].some(name=>includes(scope,name)))return {title,scope,root};
  }
  throw Error('无法划定 Team Registration 窗口范围。');
}

function dropOption(nodes,value){
  const options=new Map();
  for(const name of nodes.filter(n=>equals(n,value))){
    const chain=[name,...ancestors(nodes,name)];
    if(!chain.some(n=>/^(menu-list-|popover-content-|listbox|react-select-.*-listbox)/.test(n.id||'')||type(n,'Menu')))continue;
    const control=chain.find(n=>action(n)&&(['MenuItem','ListItem','Button','DataItem'].some(kind=>type(n,kind))||/-option-\d+$/.test(n.id||'')));
    if(control)options.set(control.index,{control,name});
  }
  return one([...options.values()]);
}

function rosterProof(w,names){
  const countNode=w.scope.find(n=>/^\d+ Drivers? Selected$/i.test(label(n)));
  const count=countNode?label(countNode).match(/^\d+/)[0]:undefined;
  const table=one(w.scope.filter(n=>type(n,'Table')&&includes(descended(w.scope,n),'Display Name')));
  // The roster summary and the table both have to agree before registration.
  if(!table)return {names:[],verified:names.length===0&&!count};
  const rows=descended(w.scope,table);
  const present=names.filter(name=>rows.some(n=>(type(n,'Text')||type(n,'DataItem'))&&equals(n,name)));
  if(count!==undefined)return {names:present,verified:Number(count)===names.length&&present.length===names.length,anchor:table,countNode};
  const cells=rows.filter(n=>type(n,'DataItem')&&label(n)&&!equals(n,'Display Name'));
  return {names:present,verified:cells.length===names.length&&names.every(name=>includes(cells,name)),anchor:table};
}

const teamField=form=>one(form?.scope.filter(n=>type(n,'Edit')&&equals(n,'Select a Team to Register'))||[]);
function selectedTeam(form,name){
  const field=teamField(form);
  if(field){
    if(clean(field.value)===name)return field;
    const parent=form.scope.find(n=>n.index===field.parent);
    if(parent)return heading(descended(form.scope,parent),name);
  }
  return form?.scope.find(n=>equals(n,'Selected Team: '+name)||type(n,'ComboBox')&&equals(n,name));
}

function teamMatch(w,job){
  if(!w)return null;
  const registered=heading(w.scope,'Registered Teams')||heading(w.scope,'Join a Registered Team');
  if(!registered)return null;
  const section=ancestors(w.scope,registered).find(root=>includes(descended(w.scope,root),job.teamName));
  const setup=w.scope.find(n=>n.index>registered.index&&equals(n,'Team Setup'));
  const scope=section?descended(w.scope,section):registered.parent===w.root.index?
    w.scope.filter(n=>n.index>registered.index&&n.index<(setup?.index??Infinity)):[];
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
    const context=flowContext(raw,job,now,false);
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

export function makeTeamAdapter(request,now=Date.now,settle=delay){
  let signedInFor;
  function command(context,job,node,phase,extra=[]){
    const opensTeamPicker=phase==='prepare'&&context.formRoot&&type(node,'Edit')&&node?.enabled&&equals(node,'Select a Team to Register');
    if(!node||(!action(node)&&!opensTeamPicker))throw Error('客户端未提供唯一且可操作的控件。');
    const identity=n=>({index:n.index,parent:n.parent,type:n.type,id:n.id||'',name:n.name||'',text:n.text||'',value:n.value||''});
    return {phase,startUtc:job.startUtc,series:job.series,track:job.track,car:job.car,url:context.raw.url,node:identity(node),
      anchors:[...new Set([...context.anchors,...extra].filter(Boolean))].map(identity)};
  }
  async function read(){return request('snapshot');}

  async function prepare(job,phase,allowed,report=()=>{}){
    const check=raw=>flowContext(raw,job,now());
    const operate=async(context,node,extra)=>{
      if(!allowed())throw Error('预约已取消、暂停或开赛。');
      const result=await request('team_action',command(context,job,node,'prepare',extra));
      if(!result.invoked)throw Error(result.reason);
      await settle(550);
      return check(await read());
    };
    const select=async(context,value,extra)=>{
      const option=dropOption(context.formRoot?descended(context.nodes,context.formRoot):context.nodes,value);
      if(!option)throw Error('选择列表未显示唯一的目标选项。');
      return operate(context,option.control,[...extra,option.name]);
    };
    let raw=await read();
    if(phase==='driver'&&receipt(raw,job,phase,now()))return {confirmed:true};
    const identityKey=JSON.stringify([job.startUtc,job.series,job.teamId,job.ownDriverId,job.ownDriverName]);
    const needsIdentity=phase==='driver'||(job.bookingMode==='team_then_join'&&!wizard(raw.nodes));
    if(needsIdentity&&signedInFor!==identityKey){
      if(!allowed())throw Error('预约已取消、暂停或开赛。');
      let profile;
      try{
        profile=await request('navigate',{target:'Profile'});
        validateSnapshot(profile,now());
      }catch(e){if(phase==='driver')throw e;profile=null;}
      if(profile?.url===profileUrl){
        if(!heading(profile.nodes,job.ownDriverName))throw Error('当前 iRacing 个人资料与准备单本人身份不匹配。');
        signedInFor=identityKey;
      }else if(phase==='driver')throw Error('当前 iRacing 个人资料与准备单本人身份不匹配。');
      raw=await openTeamSeriesPage(request,job.series,allowed);
    }else if(!raceUrl.test(raw.url)||(!wizard(raw.nodes)&&!raw.nodes.some(n=>type(n,'Text')&&norm(n.name)===norm(job.series)))){
      if(/\bWithdraw\b|You may join your session\./i.test(raw.text||''))throw Error('客户端已有其他报名。');
      raw=await openTeamSeriesPage(request,job.series,allowed);
    }
    if(phase==='team')report('car','checking');
    let context=check(raw);
    if(!wizard(context.nodes)&&!raceCarPicker(context.nodes,job.car)){
      const eligible=heading(context.nodes,'You are eligible to race in this series!');
      if(!eligible)throw Error('客户端尚未确认所选车辆和赛道的参赛资格。');
      context=await operate(context,context.register,[eligible]);
    }
    const carPicker=raceCarPicker(context.nodes,job.car);
    if(carPicker){
      context=await operate(context,carPicker.card,[carPicker.modal,carPicker.title,carPicker.name]);
      const chosen=raceCarPicker(context.nodes,job.car);
      if(!chosen)throw Error('选车窗口在确认之前发生变化。');
      context=await operate(context,chosen.next,[chosen.modal,chosen.title,chosen.name]);
    }
    let form=wizard(context.nodes);
    if(!form)throw Error('Team Registration 窗口尚未打开。');
    const current=selectedCar(context);
    if(!equals(current,job.car))throw Error('客户端未确认选中的车辆。');
    let registered=teamMatch(form,job);
    if(phase==='driver'){
      const joinList=button(form.scope,'Join a Registered Team');
      if(!registered&&joinList){
        context=await operate(context,joinList,[form.title,current]);
        form=wizard(context.nodes);
        registered=teamMatch(form,job);
      }
      if(registered?.joined)return {confirmed:true};
      if(!registered?.join)throw Error('尚未找到该场次、该车队和车辆对应的车手加入按钮。');
      return command(context,job,registered.join,'driver',[form.title,registered.name,registered.car]);
    }
    report('car','confirmed');
    report('team','checking');
    if(registered){
      if(job.driverNames.length&&!rosterProof({scope:registered.group},job.driverNames).verified)
        throw Error('该车队已经报名，客户端未显示可核对的已申报车手名单。');
      report('team','confirmed');
      report('roster','confirmed');
      return {confirmed:true};
    }
    const selection=()=>selectedTeam(form,job.teamName);
    if(!selection()){
      const picker=teamField(form)||one(form.scope.filter(n=>action(n)&&
        (['Select Team','Select a Team','Select a team'].some(s=>equals(n,s))||/^Selected Team: /i.test(label(n)))));
      context=await operate(context,picker,[form.title]);
      form=wizard(context.nodes);
      if(!form)throw Error('车队选择窗口已关闭。');
      context=await select(context,job.teamName,[form.title]);
      form=wizard(context.nodes);
    }
    if(!form||!selection())throw Error('报名窗口未确认选中的车队。');
    report('team','confirmed');
    report('roster','checking');
    for(const name of job.driverNames){
      if(!form||!selection())throw Error('车队选择已变化。');
      if(rosterProof(form,job.driverNames).names.includes(name))continue;
      context=await operate(context,button(form.scope,'Add a Driver'),[form.title,selection()]);
      form=wizard(context.nodes);
      if(!form)throw Error('车手选择窗口已关闭。');
      context=await select(context,name,[form.title]);
      form=wizard(context.nodes);
    }
    const anchors=()=>{
      const car=selectedCar(context);
      if(!form||!selection()||!equals(car,job.car))throw Error('车辆或车队确认信息已变化。');
      const roster=rosterProof(form,job.driverNames);
      if(!roster.verified)throw Error('报名窗口中的申报码单无法与准备单逐项核对。');
      const names=roster.anchor?descended(context.nodes,roster.anchor).filter(n=>job.driverNames.some(name=>equals(n,name))):[];
      return [form.title,selection(),car,roster.anchor,roster.countNode,...names];
    };
    anchors();
    report('roster','confirmed');
    report('verify','checking');
    const verifyTeam=button(form.scope,'Verify Team');
    if(verifyTeam){
      context=await operate(context,verifyTeam,anchors());
      form=wizard(context.nodes);
    }
    const proof=anchors();
    const register=button(form.scope,'Register Team');
    if(!register||button(form.scope,'Verify Team'))throw Error('Verify Team 后未显示可提交的整队报名按钮。');
    report('verify','confirmed');
    return command(context,job,register,'team',proof);
  }
  return {
    prepare,
    submit:async(job,phase,prepared)=>{
      const result=await request('team_action',prepared);
      if(result.invoked)await settle(900);
      return result;
    },
    verify:async(job,phase)=>receipt(await read(),job,phase,now())
  };
}
