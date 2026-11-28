import {setTimeout as delay} from 'node:timers/promises';

const official='https://members-ng.iracing.com';
const raceUrl=/^https:\/\/members-ng\.iracing\.com\/web\/racing\/official\/series-list\/\d+\/go-racing$/;
const profileUrl=official+'/web/racing/profile';
const driverConfirmation='Above is the list of selected drivers for the session.';
const registeredCarLabels=new Map([['Porsche 911 Cup (992.2)','P9922']]);
const toronto='America/Toronto';
const timeFormat=new Intl.DateTimeFormat('en-US',{timeZone:toronto,hour:'numeric',minute:'2-digit',hour12:true});
const clockFormat=new Intl.DateTimeFormat('en-US',{timeZone:toronto,hour:'numeric',minute:'2-digit',second:'2-digit',hour12:true});
const time24Format=new Intl.DateTimeFormat('en-CA',{timeZone:toronto,hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
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
const flowChanged=step=>Error('iRacing 报名流程可能已变化，无法核对'+step+'。请打开该场次查看。');

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
  const m=/^(\d{1,2}):(\d{2})(?::(\d{2}))?(?: ([AP]M))?$/.exec(clock);
  if(!m||+m[1]>(m[4]?12:23)||+m[2]>59||+(m[3]||0)>59)return NaN;
  return (m[4]?+m[1]%12+(m[4]==='PM'?12:0):+m[1])*3600+ +m[2]*60+ +(m[3]||0);
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
  const timer=one(rows.slice(first+1,end).map(row=>/^(?:(\d{1,2}:\d{2}(?::\d{2})?)|(\d+) hrs?(?: (\d+) mins?)?) Open Now$/.exec(row)).filter(Boolean));
  if(!timer)return NaN;
  return timer[1]?timer[1].split(':').reduce((total,part)=>total*60+Number(part),0):Number(timer[2])*3600+Number(timer[3]||0)*60;
}

export function raceContext(raw,job,now=Date.now(),requireOpen=true,registered=false){
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
  const start=Date.parse(job.startUtc);
  const absolute=localTime(new Intl.DateTimeFormat('en-US',{timeZone:toronto,month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',hour12:true}),start);
  const expectedTime=[localTime(timeFormat,start),localTime(time24Format,start),absolute];
  const datedTime=timeRows.filter(n=>/^(?:[A-Z][a-z]{2} \d+, \d{4}, )?\d{1,2}:\d{2} [AP]M$/.test(label(n)));
  const raceLabel=datedTime.length?one(datedTime):timeRows.find(n=>/^\d{2}:\d{2}$/.test(label(n)));
  const open=heading(timeRows,'Open Now');
  const remaining=liveRaceCountdown(raw.text,next.name);
  const header=String(raw.text||'').split(next.name,1)[0];
  const clock=clean(header.match(/\b\d{1,2}:\d{2}:\d{2}(?:\s[AP]M)?\b/)?.[0]);
  const clockValue=sec(clock);
  const displayedStart=sec(label(raceLabel).replace(/^[A-Z][a-z]{2} \d+, \d{4}, /,''));
  const displayedGap=(displayedStart-clockValue+86400)%86400;
  const targetGap=(start-now)/1000;
  const clientZoneMatch=!!open&&Math.abs(remaining-targetGap)<=8&&Math.abs(displayedGap-remaining)<=12;
  if(!raceLabel||(!expectedTime.includes(label(raceLabel))&&!clientZoneMatch)){
    if(requireOpen&&now<start&&!heading(timeRows,'Open Now'))
      throw Object.assign(Error('等待 iRacing 显示本次预约场次的报名窗口。'),{code:'TEAM_WINDOW_WAIT'});
    throw Object.assign(Error('客户端下一场开赛时间与准备单不一致。'),{code:'TEAM_RACE_PAGE'});
  }
  const card=nodes.slice(end?.index??0,after?.index??nodes.length);
  if(registered){
    const withdraw=button(card,'Withdraw');
    if(!withdraw||!heading(nodes,'Registered')||!String(raw.text).includes('You may join your session.'))
      throw Error('尚未读取到本人已登记的会话凭据。');
    return {raw,nodes,withdraw,anchors:[title,next,team,raceLabel,withdraw]};
  }
  const lag=(sec(localTime(clockFormat,now))-clockValue+129600)%86400-43200;
  const opening=job.registrationKind==='confirmed'?Date.parse(job.registrationOpenUtc):NaN;
  const normal=Math.abs(remaining-(start-now)/1000)<=35&&Math.abs(lag)<=35;
  const liveWithoutHeader=!Number.isFinite(lag)&&Math.abs(remaining-(start-now)/1000)<=8;
  const consistentDelay=lag>=0&&lag<=150&&(!Number.isFinite(opening)||now-lag*1000>=opening-5000)&&
    Math.abs(remaining-((start-now)/1000+lag))<=12;
  const countdownMatches=open&&(normal||liveWithoutHeader||consistentDelay||clientZoneMatch)&&(!Number.isFinite(opening)||now>=opening);
  if(requireOpen&&(!open||now>=start))
    throw Object.assign(Error('报名窗口尚未在客户端开放，或目标场次已开赛。'),{code:'TEAM_WINDOW_WAIT'});
  if(requireOpen&&!countdownMatches){
    const error=Error('iRacing 的实时倒计时或时钟无法核对到目标场次。');
    error.code='TEAM_RACE_CLOCK';
    throw error;
  }
  if(!requireOpen&&!countdownMatches&&label(raceLabel)!==absolute)
    throw Error('客户端未显示足以确认该场次日期的时间。');
  const register=button(card,'Register');
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

function confirmationDialog(nodes){
  return one(nodes.filter(n=>type(n,'Window')&&equals(n,'Team Registration')&&n.id?.startsWith('chakra-modal-')&&
    descended(nodes,n).some(child=>type(child,'Text')&&label(child).startsWith(driverConfirmation))));
}

function flowContext(raw,job,now,requireOpen=true){
  validateSnapshot(raw,now);
  const {nodes,teamTarget}=raw;
  const confirmation=confirmationDialog(nodes);
  const formRoot=confirmation||one(nodes.filter(n=>type(n,'Window')&&equals(n,'Go Racing')&&n.id?.startsWith('chakra-modal-')&&
    heading(descended(nodes,n),'Team Registration')));
  if(!formRoot)return raceContext(raw,job,now,requireOpen);
  if(!raceUrl.test(raw.url)||!teamTarget||teamTarget.windowId!==formRoot.id||teamTarget.car!==job.car||
     teamTarget.series!==job.series||teamTarget.track!==job.track||
     Date.parse(teamTarget.startUtc)!==Date.parse(job.startUtc)||now>=Date.parse(job.startUtc)||
     confirmation&&!(teamTarget.verified&&teamTarget.confirmation))
    throw Error('报名窗口无法与预约场次绑定，请关闭手动打开的表单后重试。');
  return {raw,nodes,formRoot,confirmation,anchors:[formRoot]};
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

function dropOption(context,value){
  const {nodes,formRoot}=context;
  const scope=formRoot?descended(nodes,formRoot):nodes;
  const options=new Map();
  for(const name of nodes.filter(n=>equals(n,value))){
    const chain=[name,...ancestors(nodes,name)];
    const menu=chain.find(n=>type(n,'Menu')||(!type(n,'MenuItem')&&/^(menu-list-|popover-content-|listbox|react-select-.*-listbox)/.test(n.id||'')));
    if(!menu)continue;
    const control=chain.find(n=>action(n)&&(['MenuItem','ListItem','Button','DataItem'].some(kind=>type(n,kind))||/-option-\d+$/.test(n.id||'')));
    if(!control)continue;
    const portal=formRoot&&!scope.includes(control);
    const owner=portal&&menu.id?.startsWith('menu-list-')?one(scope.filter(n=>n.id==='menu-button-'+menu.id.slice(10))):null;
    if(portal&&(!owner||!type(control,'MenuItem')))continue;
    options.set(control.index,{control,name,extra:owner?[menu,owner]:[]});
  }
  return one([...options.values()]);
}

function driverTable(form){
  const open=button(form.scope,'Add a Driver');
  if(!open)return null;
  const panel=one(form.scope.filter(n=>n.parent===open.parent&&n.index>open.index&&
    n.id?.startsWith('accordion-panel-')&&form.scope.some(control=>
      control.parent===open.parent&&control.id==='accordion-button-'+n.id.slice('accordion-panel-'.length))));
  return panel&&one(descended(form.scope,panel).filter(n=>type(n,'Table')));
}

function driverOption(form,table,name,customerId){
  const options=[];
  for(const row of form.scope.filter(n=>n.parent===table.index&&type(n,'DataItem'))){
    const cells=descended(form.scope,row);
    const driver=one(cells.filter(n=>n.parent===row.index&&type(n,'DataItem')&&equals(n,name)));
    const identity=customerId&&one(cells.filter(n=>n.parent===row.index&&type(n,'DataItem')&&
      clean(label(n).replace(/\p{Co}/gu,''))===customerId));
    const control=button(cells,'Select');
    if(driver&&control&&(!customerId||identity))options.push({control,anchors:[table,row,driver,identity]});
  }
  return one(options);
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

function rosterAnchors(scope,roster,names){
  const rows=roster.anchor?descended(scope,roster.anchor).filter(n=>names.some(name=>equals(n,name))):[];
  return [roster.anchor,roster.countNode,...rows];
}

function confirmationProof(context,job){
  const scope=descended(context.nodes,context.confirmation);
  const teamLabel=heading(scope,'Selected Team:');
  const team=teamLabel&&heading(scope.filter(n=>n.parent===teamLabel.parent&&n.index===teamLabel.index+1),job.teamName);
  const roster=rosterProof({scope},job.driverNames);
  const register=one(scope.filter(n=>type(n,'Button')&&action(n)&&equals(n,'Register')&&/^\d+-reg-button$/.test(n.id||'')));
  if(!team||!roster.verified||!register)throw Error('最终报名确认页中的车队、名单或提交按钮与预约不匹配。');
  return {register,anchors:[teamLabel,team,...rosterAnchors(scope,roster,job.driverNames)]};
}

const teamField=form=>one(form?.scope.filter(n=>type(n,'Edit')&&equals(n,'Select a Team to Register'))||[]);
function teamPicker(form){
  const field=teamField(form);
  return field&&(one(form.scope.filter(n=>n.parent===form.root.index&&n.index>field.index&&n.index<field.index+5&&
    n.id?.startsWith('menu-button-')&&action(n)))||field);
}
function selectedTeam(form,name){
  const field=teamField(form);
  if(field){
    if(clean(field.value)===name)return field;
    const parent=form.scope.find(n=>n.index===field.parent);
    if(parent)return heading(descended(form.scope,parent),name);
  }
  return form?.scope.find(n=>equals(n,'Selected Team: '+name)||type(n,'ComboBox')&&equals(n,name));
}

function signedInAs(profile,name){
  const text=profile.nodes.filter(n=>type(n,'Text'));
  const cards=text.filter(n=>/^(?:OVAL|SPORTS CAR|FORMULA|DIRT OVAL|DIRT ROAD) RACING$/.test(label(n)));
  return cards.length?cards.some(card=>equals(text.find(n=>n.index>card.index&&n.parent===card.parent),name)):
    !!heading(text,name);
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

function registeredTeamRow(form,teamName){
  if(!form)return null;
  const title=heading(form.scope,'Join a Registered Team');
  const setup=heading(form.scope,'Team Setup');
  if(!title||!setup)return null;
  const table=one(form.scope.filter(n=>type(n,'Table')&&n.parent===title.parent&&n.index>title.index&&n.index<setup.index));
  if(!table)return null;
  const rows=descended(form.scope,table).filter(n=>type(n,'DataItem')&&n.parent===table.index);
  const cells=row=>form.scope.filter(n=>type(n,'DataItem')&&n.parent===row.index);
  const header=one(rows.filter(row=>includes(cells(row),'Team Name')&&includes(cells(row),'Car')));
  if(!header)return null;
  const columns=cells(header);
  const carOffset=columns.findIndex(n=>equals(n,'Car'))-columns.findIndex(n=>equals(n,'Team Name'));
  const matches=[];
  for(const row of rows){
    if(row===header)continue;
    const rowCells=cells(row);
    const team=one(rowCells.filter(n=>equals(n,teamName)));
    if(!team)continue;
    const scope=descended(form.scope,row);
    const withdraw=button(scope,'widthdraw-button')||button(scope,'Withdraw Team');
    const personalWithdraw=button(scope,'Withdraw as Driver')||button(scope,'Withdraw from Session')||button(scope,'Withdraw');
    const join=one(scope.filter(n=>type(n,'Button')&&action(n)&&equals(n,'Register')&&/^\d+-reg-button$/.test(n.id||'')));
    matches.push({row,team,title,car:rowCells[rowCells.indexOf(team)+carOffset],scope,withdraw,personalWithdraw,join});
  }
  return one(matches);
}

function teamAbsent(form,teamName,matchedWithdrawal){
  const title=heading(form?.scope||[],'Join a Registered Team');
  const setup=heading(form?.scope||[],'Team Setup');
  if(!title||!setup||setup.index<=title.index)return false;
  const section=form.scope.filter(n=>n.index>title.index&&n.index<setup.index);
  const loaded=section.some(n=>type(n,'Table')&&includes(descended(section,n),'Team Name')&&includes(descended(section,n),'Car'))||
    section.some(n=>type(n,'Text')&&(
      /^(?:There are )?no (?:registered teams|teams (?:are )?registered)(?: for this (?:race|session))?\.?$/i.test(label(n))||
      (matchedWithdrawal&&/^There are no registered teams that you may join of \d+ teams? currently in the session\.?$/i.test(label(n)))));
  return loaded&&!section.some(n=>equals(n,teamName)||/^Loading(?:…|\.\.\.)?$/i.test(label(n)));
}

function withdrawalDialog(nodes,job,phase){
  const isTeam=phase==='withdraw_team';
  const personalDialogId='withdraw-modal-modal-dialog';
  const dialog=one(nodes.filter(n=>(!isTeam&&type(n,'Group')&&n.id===personalDialogId&&
    nodes.some(parent=>parent.index===n.parent&&type(parent,'Group')&&parent.id==='withdraw-modal'))||
    (type(n,'Window')&&n.id?.startsWith('chakra-modal-')&&
      /^(?:Confirm Withdrawal|Withdraw(?: from (?:the )?Session| Team)?)$/i.test(label(n)))));
  if(!dialog)return null;
  const scope=descended(nodes,dialog);
  const cancel=button(scope,'Cancel');
  if(dialog.id===personalDialogId){
    const body=scope.filter(n=>n.parent===dialog.index);
    const question=heading(body,'Are you sure you want to leave this session?');
    const confirm=button(scope,'Withdraw');
    const footer=one(body.filter(n=>type(n,'Group')&&n.index===cancel?.parent&&n.index===confirm?.parent));
    return heading(body,'Withdraw')&&question&&footer?{dialog,question,cancel,confirm}:null;
  }
  const question=scope.find(n=>type(n,'Text')&&/withdraw/i.test(label(n))&&
    (isTeam?/\bteam\b/i.test(label(n))||label(n).includes(job.teamName):/\b(?:you|your|driver)\b/i.test(label(n))&&!/whole team|entire team|withdraw (?:the|your) team/i.test(label(n))));
  const confirm=one(scope.filter(n=>type(n,'Button')&&action(n)&&['Withdraw','Withdraw Team','Confirm Withdrawal'].some(name=>equals(n,name))));
  return question&&cancel&&confirm?{dialog,question,cancel,confirm}:null;
}

const matchesRegisteredCar=(row,car)=>row?.car&&[car,registeredCarLabels.get(car)].filter(Boolean).some(name=>equals(row.car,name));

export function receipt(raw,job,phase,now=Date.now()){
  try{
    const context=flowContext(raw,job,now,false);
    if(context.confirmation)return false;
    const form=wizard(context.nodes);
    const registered=teamMatch(form,job);
    const row=registeredTeamRow(form,job.teamName);
    if(phase==='team'){
      if(registered)return true;
      if(!context.formRoot||!raw.teamTarget?.verified)return false;
      return !!row?.withdraw&&matchesRegisteredCar(row,job.car)&&
        equals(selectedCar(context),job.car)&&!!selectedTeam(form,job.teamName)&&rosterProof(form,job.driverNames).verified;
    }
    return !!registered?.joined||!!(context.formRoot&&matchesRegisteredCar(row,job.car)&&job.ownDriverName&&
      includes(row.scope,job.ownDriverName)&&['Registered as Driver','You are registered as a driver'].some(name=>includes(row.scope,name)));
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
  let lastClockRefresh=0;
  let driverAttempt;
  let teamExitAction;
  function command(context,job,node,phase,extra=[]){
    const opensTeamPicker=phase==='prepare'&&context.formRoot&&type(node,'Edit')&&node?.enabled&&equals(node,'Select a Team to Register');
    if(!node||(!action(node)&&!opensTeamPicker))throw Error('客户端未提供唯一且可操作的控件。');
    const identity=n=>({index:n.index,parent:n.parent,type:n.type,id:n.id||'',name:n.name||'',text:n.text||'',value:n.value||''});
    return {phase,startUtc:job.startUtc,registrationOpenUtc:job.registrationKind==='confirmed'?job.registrationOpenUtc:null,
      series:job.series,track:job.track,car:job.car,teamName:job.teamName,ownDriverName:job.ownDriverName,
      url:context.raw.url,node:identity(node),
      anchors:[...new Set([...context.anchors,...extra].filter(Boolean))].map(identity)};
  }
  async function read(){return request('snapshot');}
  const sameDriverAttempt=job=>driverAttempt&&(driverAttempt.job===job||job.id&&driverAttempt.job.id===job.id);
  const nativeDriverTarget=(raw,job)=>sameDriverAttempt(job)&&raw.url===driverAttempt.url&&
    Date.parse(raw.driverTarget?.startUtc)===Date.parse(job.startUtc)&&
    raw.driverTarget.team===job.teamName&&raw.driverTarget.car===job.car&&
    raw.driverTarget.controlId===driverAttempt.controlId&&Date.parse(raw.driverTarget.submittedAt)>=driverAttempt.at-2000;

  async function openForm(context,job,operate){
    if(!wizard(context.nodes)&&!raceCarPicker(context.nodes,job.car)){
      const eligible=heading(context.nodes,'You are eligible to race in this series!');
      if(!eligible)throw Error('客户端尚未确认所选车辆和赛道的参赛资格。');
      if(!context.register)throw flowChanged('目标场次的入口');
      context=await operate(context,context.register,[eligible]);
    }
    const picker=raceCarPicker(context.nodes,job.car);
    if(picker){
      context=await operate(context,picker.card,[picker.modal,picker.title,picker.name]);
      const chosen=raceCarPicker(context.nodes,job.car);
      if(!chosen)throw flowChanged('选车窗口的 Continue');
      context=await operate(context,chosen.next,[chosen.modal,chosen.title,chosen.name]);
    }
    return context;
  }

  async function withdraw(job,allowed,progress,verifyStage=null){
    const cutoff=Date.parse(job.startUtc)-120000;
    const canAct=()=>allowed()&&now()<cutoff;
    const dispatch=async(context,node,phase,anchors)=>{
      if(!canAct())throw Error('已到赛前两分钟的退出截止时间，或助手已暂停。');
      return request('team_action',command(context,job,node,phase,anchors));
    };
    const inspect=async()=>{await settle(900);return read();};
    async function readAfterWithdrawal(source,phase){
      const raw=await inspect();
      const confirmation=raw.url===source.raw.url&&withdrawalDialog(raw.nodes,job,phase);
      if(!confirmation)return raw;
      validateSnapshot(raw,now());
      const {dialog,question,cancel,confirm}=confirmation;
      const result=await dispatch({raw,anchors:[dialog]},confirm,phase+'_confirm',[question,cancel]);
      if(!result.invoked)throw Error(result.reason);
      return inspect();
    }
    const scopedRow=context=>registeredTeamRow(wizard(context.nodes),job.teamName);
    const teamExitConfirmed=context=>{
      if(!context.formRoot)return false;
      if(context.nodes.some(n=>n!==context.formRoot&&(type(n,'Window')||/-modal-dialog$/.test(n.id||''))))return false;
      const matchingAction=teamExitAction&&(teamExitAction.job===job||job.id&&teamExitAction.job.id===job.id)&&
        teamExitAction.windowId===context.formRoot.id&&now()-teamExitAction.at<=120000;
      return teamAbsent(wizard(context.nodes),job.teamName,matchingAction);
    };
    let raw=await read();
    let context;
    let row;
    const personalExitRecorded=job.teamWithdrawal?.driverWithdrawn===true;
    const savedPersonal=!personalExitRecorded&&['confirmed','unconfirmed'].includes(job.teamProgress.driver);
    const showMainRegistration=nativeDriverTarget(raw,job)&&
      raw.text?.includes('You may join your session.');
    if(verifyStage==='team'){
      const confirmed=raw=>teamExitConfirmed(flowContext(raw,job,now()));
      if(confirmed(raw)&&confirmed(await inspect()))return true;
      throw Error('本次整队退出尚未确认。请查看 iRacing 的报名车队列表。');
    }
    if(personalExitRecorded&&(raw.text?.includes('You may join your session.')||heading(raw.nodes,'Registered')))
      throw Error('iRacing 又显示本人已登记，请先核对当前会话。');
    if(showMainRegistration){
      context=raceContext(raw,job,now(),false,true);
      if(verifyStage==='personal')throw Error('iRacing 仍显示本人已登记，请查看当前退出提示。');
      progress('personal_submitting','正在退出本人车手登记。');
      const result=await dispatch(context,context.withdraw,'withdraw_driver',[]);
      if(!result.invoked){progress('blocked',result.reason);throw Error(result.reason);}
      raw=await readAfterWithdrawal(context,'withdraw_driver');
      if(raw.text?.includes('You may join your session.')||!raceContext(raw,job,now()).register)
        throw Error('iRacing 尚未确认本人已退出。请查看是否出现新的退出确认。');
      progress('personal_confirmed','本人车手登记已退出，正在重新核对车队。');
    }else if(savedPersonal){
      context=flowContext(raw,job,now());
      row=scopedRow(context);
      if(row?.personalWithdraw&&matchesRegisteredCar(row,job.car)&&includes(row.scope,job.ownDriverName)){
        if(verifyStage==='personal')throw Error('iRacing 仍显示本人已登记，请查看当前退出提示。');
        progress('personal_submitting','正在退出本人车手登记。');
        const result=await dispatch(context,row.personalWithdraw,'withdraw_driver',[row.title,row.row,row.team,row.car]);
        if(!result.invoked){progress('blocked',result.reason);throw Error(result.reason);}
        raw=await readAfterWithdrawal(context,'withdraw_driver');
        context=flowContext(raw,job,now());
        row=scopedRow(context);
        if(!row?.join||row.personalWithdraw||!matchesRegisteredCar(row,job.car))
          throw Error('iRacing 尚未确认本人已退出。请查看是否出现新的退出确认。');
        progress('personal_confirmed','本人车手登记已退出，正在核对车队。');
      }else if(verifyStage==='personal'&&!context.formRoot&&sameDriverAttempt(job)&&raw.url===driverAttempt.url&&
               context.register&&!heading(raw.nodes,'Registered')&&!raw.text?.includes('You may join your session.')){
        progress('personal_confirmed','本人车手登记已退出，正在重新核对车队。');
      }else if(!row?.join||!matchesRegisteredCar(row,job.car)||raw.text?.includes('You may join your session.')){
        throw flowChanged('本人车手登记状态');
      }else if(verifyStage==='personal'||job.teamProgress.driver==='confirmed'){
        progress('personal_confirmed','本人车手登记已退出，正在核对车队。');
      }
    }
    if(!raceUrl.test(raw.url)||(!wizard(raw.nodes)&&!raw.nodes.some(n=>type(n,'Text')&&norm(n.name)===norm(job.series)))){
      if(/\bWithdraw\b|You may join your session\./i.test(raw.text||''))throw flowChanged('当前退出场次');
      raw=await openTeamSeriesPage(request,job.series,canAct);
    }
    for(let attempt=0;;attempt++){
      try{
        context=await openForm(flowContext(raw,job,now()),job,async(current,node,anchors)=>{
          const result=await dispatch(current,node,'prepare',anchors);
          if(!result.invoked){
            const error=Error(result.reason);
            if(['预约窗口在执行前发生变化。','预约控件位置已变化。'].includes(result.reason))error.code='TEAM_VIEW_SHIFTED';
            throw error;
          }
          return flowContext(await inspect(),job,now());
        });
        break;
      }catch(error){
        if(error.code!=='TEAM_VIEW_SHIFTED'||attempt>=2||!canAct())throw error;
        raw=await inspect();
      }
    }
    row=scopedRow(context);
    if(!row)throw Error('当前场次未显示可核对的车队报名。请查看 iRacing。');
    if(row.personalWithdraw||(job.ownDriverName&&includes(row.scope,job.ownDriverName)&&
       ['Registered as Driver','You are registered as a driver'].some(name=>includes(row.scope,name))))
      throw Error('iRacing 又显示本人已登记，请先核对当前会话。');
    if(!context.formRoot||!row.withdraw||!matchesRegisteredCar(row,job.car))
      throw Error('iRacing 尚未提供该车队的退出权限。请检查是否仍有队员登记，或退出窗口是否已关闭。');
    progress('team_submitting','正在退出整队报名。');
    const result=await dispatch(context,row.withdraw,'withdraw_team',[row.title,row.row,row.team,row.car]);
    if(!result.invoked){progress('blocked',result.reason);throw Error(result.reason);}
    teamExitAction={job,windowId:context.formRoot.id,at:now()};
    let latest=await readAfterWithdrawal(context,'withdraw_team');
    let absent=0;
    for(let attempt=0;attempt<3;attempt++){
      const next=flowContext(latest,job,now());
      if(teamExitConfirmed(next)){
        if(++absent===2)return true;
      }else absent=0;
      if(attempt<2)latest=await inspect();
    }
    throw Error('iRacing 尚未确认整队退出。请查看是否出现新的退出确认。');
  }

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
      const option=dropOption(context,value);
      if(!option)throw Error('选择列表未显示唯一的目标选项。');
      return operate(context,option.control,[...extra,...option.extra,option.name]);
    };
    const finalConfirmation=context=>{
      if(phase!=='team')throw Error('请先完成整队报名确认。');
      const proof=confirmationProof(context,job);
      report('verify','confirmed');
      return command(context,job,proof.register,'team',proof.anchors);
    };
    let raw=await read();
    if(confirmationDialog(raw.nodes||[]))return finalConfirmation(check(raw));
    const idleForm=wizard(raw.nodes||[]);
    if(idleForm?.root.id?.startsWith('chakra-modal-')&&!raw.teamTarget){
      if(!allowed())throw Error('预约已取消、暂停或开赛。');
      raw=await request('close_idle_team_form',{url:raw.url});
    }
    if(phase==='driver'&&receipt(raw,job,phase,now()))return {confirmed:true};
    if(heading(raw.nodes,'Registered')||raw.text?.includes('You may join your session.'))
      throw Error('iRacing 已有个人登记，请先核对当前会话。');
    const identityKey=JSON.stringify([job.startUtc,job.series,job.teamId,job.ownDriverId,job.ownDriverName]);
    const needsIdentity=phase==='driver'||(job.bookingMode==='team_then_join'&&!wizard(raw.nodes));
    if(needsIdentity&&signedInFor!==identityKey){
      if(!allowed())throw Error('预约已取消、暂停或开赛。');
      let profile;
      try{
        if(phase==='driver'&&raw.teamTarget){
          const context=check(raw);
          const scope=descended(raw.nodes,context.formRoot);
          const header=one(scope.filter(n=>n.parent===context.formRoot.index&&n.id?.startsWith('chakra-modal--header-')));
          if(header)await operate(context,button(descended(scope,header),'Close'),[]);
        }
        profile=await request('navigate',{target:'Profile'});
        validateSnapshot(profile,now());
      }catch(e){if(phase==='driver')throw e;profile=null;}
      if(profile?.url===profileUrl){
        if(signedInAs(profile,job.ownDriverName))signedInFor=identityKey;
        else if(phase==='driver')throw Error('当前 iRacing 个人资料与准备单本人身份不匹配。');
      }else if(phase==='driver')throw Error('当前 iRacing 个人资料与准备单本人身份不匹配。');
      raw=await openTeamSeriesPage(request,job.series,allowed);
    }else if(!raceUrl.test(raw.url)||(!wizard(raw.nodes)&&!raw.nodes.some(n=>type(n,'Text')&&norm(n.name)===norm(job.series)))){
      if(/\bWithdraw\b|You may join your session\./i.test(raw.text||''))throw Error('客户端已有其他报名。');
      raw=await openTeamSeriesPage(request,job.series,allowed);
    }
    if(phase==='team')report('car','checking');
    let context;
    try{context=check(raw);}
    catch(error){
      if(!['TEAM_RACE_CLOCK','TEAM_RACE_PAGE','TEAM_WINDOW_WAIT'].includes(error.code)||now()-lastClockRefresh<60000||wizard(raw.nodes)||
         raceCarPicker(raw.nodes,job.car)||/\bWithdraw\b|You may join your session\./i.test(raw.text||''))throw error;
      lastClockRefresh=now();
      context=check(await openTeamSeriesPage(request,job.series,allowed));
    }
    context=await openForm(context,job,operate);
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
      if(registered?.join)return command(context,job,registered.join,'driver',[form.title,registered.name,registered.car]);
      const row=registeredTeamRow(form,job.teamName);
      const declaredHere=job.bookingMode==='team_then_join'&&job.teamProgress?.team==='confirmed'&&job.declaration==='required'&&
        job.roster?.includes(job.ownDriverId)&&job.driverNames.includes(job.ownDriverName);
      if(context.formRoot&&declaredHere&&row?.withdraw&&row.join&&matchesRegisteredCar(row,job.car))
        return command(context,job,row.join,'driver',[form.title,row.title,row.row,row.team,row.car,row.withdraw]);
      throw flowChanged('当前车队的本人车手登记按钮');
    }
    report('car','confirmed');
    report('team','checking');
    if(registeredTeamRow(form,job.teamName)?.withdraw)
      throw Error('该车队已在当前场次的报名名单中，请核对已有记录。');
    if(registered){
      if(job.driverNames.length&&!rosterProof({scope:registered.group},job.driverNames).verified)
        throw Error('该车队已经报名，客户端未显示可核对的已申报车手名单。');
      report('team','confirmed');
      report('roster','confirmed');
      return {confirmed:true};
    }
    const selection=()=>selectedTeam(form,job.teamName);
    if(!selection()){
      const picker=teamPicker(form)||one(form.scope.filter(n=>action(n)&&
        (['Select Team','Select a Team','Select a team'].some(s=>equals(n,s))||/^Selected Team: /i.test(label(n)))));
      if(!dropOption(context,job.teamName)){
        context=await operate(context,picker,[form.title]);
        form=wizard(context.nodes);
      }
      if(!form)throw Error('车队选择窗口已关闭。');
      context=await select(context,job.teamName,[form.title]);
      form=wizard(context.nodes);
    }
    if(!form||!selection())throw Error('报名窗口未确认选中的车队。');
    report('team','confirmed');
    report('roster','checking');
    for(const [index,name] of job.driverNames.entries()){
      if(!form||!selection())throw Error('车队选择已变化。');
      if(rosterProof(form,job.driverNames).names.includes(name))continue;
      if(!driverTable(form)&&!dropOption(context,name)){
        context=await operate(context,button(form.scope,'Add a Driver'),[form.title,selection()]);
        form=wizard(context.nodes);
      }
      if(!form)throw Error('车手选择窗口已关闭。');
      const table=driverTable(form);
      if(table){
        const option=driverOption(form,table,name,job.roster?.[index]);
        if(!option)throw Error('可选车手表未显示唯一匹配的车手和 Customer ID。');
        context=await operate(context,option.control,[form.title,selection(),...option.anchors]);
      }else{
        context=await select(context,name,[form.title,selection()]);
      }
      form=wizard(context.nodes);
      if(!form||!rosterProof(form,job.driverNames).names.includes(name))
        throw Error('客户端尚未将所选车手列入申报名单。');
    }
    const anchors=()=>{
      const car=selectedCar(context);
      if(!form||!selection()||!equals(car,job.car))throw Error('车辆或车队确认信息已变化。');
      const roster=rosterProof(form,job.driverNames);
      if(!roster.verified)throw Error('报名窗口中的申报码单无法与准备单逐项核对。');
      return [form.title,selection(),car,...rosterAnchors(context.nodes,roster,job.driverNames)];
    };
    anchors();
    report('roster','confirmed');
    report('verify','checking');
    const verifyTeam=button(form.scope,'Verify Team');
    if(verifyTeam){
      context=await operate(context,verifyTeam,anchors());
      if(context.confirmation)return finalConfirmation(context);
      form=wizard(context.nodes);
    }
    const proof=anchors();
    const register=button(form.scope,'Register Team')||(context.raw.teamTarget?.verified===true?button(form.scope,'Register'):null);
    if(!register||button(form.scope,'Verify Team'))throw flowChanged('Verify Team 后的最终整队报名按钮');
    report('verify','confirmed');
    return command(context,job,register,'team',proof);
  }
  return {
    prepare,
    withdraw,
    submit:async(job,phase,prepared)=>{
      if(phase==='driver')driverAttempt={job,url:prepared.url,controlId:prepared.node.id,at:now()};
      const result=await request('team_action',prepared);
      if(result.invoked)await settle(900);
      else if(phase==='driver')driverAttempt=null;
      return result;
    },
    verify:async(job,phase)=>{
      const raw=await read();
      if(receipt(raw,job,phase,now()))return true;
      if(phase!=='driver'||!nativeDriverTarget(raw,job)||now()-driverAttempt.at>120000)return false;
      try{return !!raceContext(raw,job,now(),false,true).withdraw;}catch{return false;}
    }
  };
}
