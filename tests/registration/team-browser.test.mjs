import {test} from 'node:test';
import assert from 'node:assert/strict';
import {makeTeamAdapter,raceContext,receipt} from '../../registration/team-browser.mjs';
import {runTeamAppointment} from '../../registration/team-appointment.mjs';
import {currentTeamClient} from './current-team-form.fixture.mjs';

const startUtc='2026-11-28T07:00:00.000Z',now=Date.parse(startUtc)-90000;
const url='https://members-ng.iracing.com/web/racing/official/series-list/6777/go-racing';
const job={series:'Test Endurance Cup',track:'Spa - Endurance',car:'Cup Car',startUtc,teamId:'20',
  teamName:'Example Team',ownDriverName:'Example Driver',driverNames:['Example Driver','Second Driver']};

function raw({form=true,registered=false,joined=false,regTeam=job.teamName,regCar=job.car,
              plannedNames=job.driverNames,team='Team (2 - 16)',clock='1:58:30 AM',open='Open Now',
              treeCountdown='1:30',liveCountdown='1:30'}={}){
  const nodes=[];
  function add(type,name='',parent=0,id='',invoke=false,text=''){
    const index=nodes.length;
    nodes.push({index,parent,type:'ControlType.'+type,name,id,invoke,enabled:true,text,value:'',patterns:[]});
    return index;
  }
  const doc=add('Document','',-1);
  add('Text',job.series,doc);
  add('Text',team,doc);
  add('Text','Next Race @ Spa Endurance',doc);
  add('Text','You are eligible to race in this series!',doc);
  const card=add('Group','',doc);
  add('Text','2:00 AM',card);
  add('Text',treeCountdown,card);
  add('Text',open,card);
  add('Text','Race Duration',card);
  add('Button','button',card,'id-race',true,'Register');
  const choice=add('Group','',doc);
  add('Text','Selected Car',choice);
  add('Text',job.car,choice);
  const menu=add('Group','',choice);
  add('Button','',menu,'menu-button-123',true);
  add('Button','',add('Group','',menu),'favorite_cars-14',true);
  add('Text','Available Sessions',doc);
  if(form){
    const dialog=add('Pane','',doc,'team-registration-dialog');
    add('Text','Team Registration',dialog);
    const setup=add('Group','',dialog);
    add('Text','Team Setup',setup);
    add('Button','Selected Team: '+job.teamName,setup,'select-team',true);
    add('Button','Register Team',setup,'register-team',true);
    if(plannedNames.length){
      add('Text',plannedNames.length+' Drivers Selected',setup);
      const roster=add('Table','',setup);
      add('Text','Display Name',roster);
      for(const name of plannedNames)add('Text',name,add('DataItem',name,roster));
    }
    add('Button','Add a Driver',setup,'add-driver',true);
    const section=add('Group','',dialog);
    add('Text','Registered Teams',section);
    if(registered){
      const row=add('Group','',section);
      add('Text',regTeam,row);
      add('Text',regCar,row);
      if(joined){
        add('Text',job.ownDriverName,row);
        add('Text','Registered as Driver',row);
      }else add('Button','Register as Driver',row,'register-driver',true);
    }
  }
  const text=`${clock}\nNext Race @ Spa Endurance\n\ufffc\n2:00 AM\n\ufffc\n${liveCountdown} ${open.trim()}\n\ufffc\nRace Duration 4 hrs`;
  return {ok:true,url,nodes,observedAt:new Date(now).toISOString(),text};
}

test('generic Register is tied to the exact open team race, never a different date or layout',()=>{
  assert.equal(raceContext(raw({form:false}),job,now).register?.id,'id-race');
  for(const [snapshot,plan] of [
    [raw({team:'Single Driver'}),job],
    [raw({clock:'5:14:00 PM'}),job],
    [raw({open:'Closed'}),job],
    [raw(),{...job,track:'Spa Grand Prix'}],
    [raw(),{...job,startUtc:'2026-11-29T07:00:00.000Z'}],
  ])assert.throws(()=>raceContext(snapshot,plan,now));
});

test('uses the live race-card countdown when the accessible control name is stale',()=>{
  const snapshot=raw({form:false,treeCountdown:'27:10',open:' Open Now'});
  assert.equal(raceContext(snapshot,job,now).register?.id,'id-race');
  const stale=raw({form:false,liveCountdown:'27:10'});
  stale.text+='\nAvailable Sessions\n1:30 Open Now';
  assert.throws(()=>raceContext(stale,job,now),/倒计时/);
});

test('registered team and registered driver are separate scoped receipts',()=>{
  assert.equal(receipt(raw({registered:true}),job,'team',now),true);
  assert.equal(receipt(raw({registered:true}),job,'driver',now),false);
  assert.equal(receipt(raw({registered:true,joined:true}),job,'driver',now),true);
  assert.equal(receipt(raw({registered:true,joined:true}),{...job,ownDriverName:'Different Driver'},'driver',now),false);
  assert.equal(receipt(raw({registered:true,regCar:'Different Car'}),job,'team',now),false);
  assert.equal(receipt(raw({registered:true,regTeam:'Different Team'}),job,'team',now),false);
});

test('does not borrow the matching car from another registered team',()=>{
  const snapshot=raw({registered:true,regCar:'Different Car'});
  const {nodes}=snapshot;
  const originalRow=nodes.find(n=>n.name===job.teamName).parent;
  const originalParent=nodes[originalRow].parent;
  const list=nodes.length;
  nodes[originalRow].parent=list;
  nodes.push({index:list,parent:originalParent,type:'ControlType.Group'});
  nodes.push({index:list+1,parent:list,type:'ControlType.Group'});
  nodes.push({index:list+2,parent:list+1,type:'ControlType.Text',name:'Different Team'});
  nodes.push({index:list+3,parent:list+1,type:'ControlType.Text',name:job.car});
  assert.equal(receipt(snapshot,job,'team',now),false);
});

test('the submit payload identifies the exact team button and both roster rows',async()=>{
  const adapter=makeTeamAdapter(async op=>{
    assert.equal(op,'snapshot');
    return raw();
  },()=>now);
  const prepared=await adapter.prepare(job,'team',()=>true);
  assert.equal(prepared.node.name,'Register Team');
  assert.ok(prepared.anchors.some(n=>n.name==='Second Driver'));
  assert.ok(prepared.anchors.some(n=>n.name==='Selected Team: Example Team'));
  const ambiguous=makeTeamAdapter(async()=>raw({plannedNames:[...job.driverNames,'Extra Driver']}),()=>now);
  await assert.rejects(()=>ambiguous.prepare(job,'team',()=>true),/申报码单/);
  const existing=makeTeamAdapter(async()=>raw({registered:true}),()=>now);
  await assert.rejects(()=>existing.prepare(job,'team',()=>true),/已申报车手名单/);
});

test('requires the signed-in profile before preparing a matching driver action',async()=>{
  const profile=(name)=>({...raw(),url:'https://members-ng.iracing.com/web/racing/profile',
    nodes:[name,'SPORTS CAR RACING',name,'Class B','3.00'].map((name,index)=>({index,parent:-1,type:'ControlType.Text',name}))});
  function request(name){
    return async(op,args)=>{
      if(op==='navigate'&&args.target==='Profile')return profile(name);
      return raw({registered:true});
    };
  }
  const adapter=makeTeamAdapter(request(job.ownDriverName),()=>now);
  const prepared=await adapter.prepare(job,'driver',()=>true);
  assert.equal(prepared.node.name,'Register as Driver');
  const other=makeTeamAdapter(request('Other Account'),()=>now);
  await assert.rejects(()=>other.prepare(job,'driver',()=>true),/本人身份/);
});

test('current client completes the appointment through the car picker, bound form and team receipt',async()=>{
  const client=currentTeamClient(()=>raw({form:false}),job);
  const adapter=makeTeamAdapter(client.request,()=>now,async()=>{});
  let state={...job,id:'current',status:'waiting',bookingMode:'team_then_join',
    registrationOpenUtc:new Date(now-1000).toISOString(),teamProgress:{team:'waiting',driver:'waiting'}};
  const transitions=[];
  const store={get:()=>state,updateTeam:(id,status,note,teamProgress,steps)=>{
    state={...state,status,note,teamProgress:{...teamProgress},teamSteps:{...steps}};
    transitions.push(state);
  }};
  await runTeamAppointment(store,adapter,state,()=>now);
  assert.deepEqual(client.actions,['open race','select car','continue','open teams','select team','open drivers','select driver','verify team','register team']);
  assert.equal(state.teamProgress.team,'confirmed');
  assert.equal(state.teamProgress.driver,'waiting');
  for(const key of ['car','team','roster','verify','submit']){
    assert.ok(transitions.some(s=>s.teamSteps[key]==='checking'),key+' never started');
    assert.equal(state.teamSteps[key],'confirmed',key);
  }
  await runTeamAppointment(store,adapter,state,()=>now);
  assert.equal(state.status,'succeeded');
  assert.equal(client.actions.at(-1),'join as driver');
});

test('rejects a current form tied to another race, ambiguous team or extra declared driver',async()=>{
  for(const [options,why] of [[{wrongSession:true},/窗口.*场次/],[{wrongSeries:true},/窗口.*场次/],[{duplicateTeam:true},/唯一/],[{extraDriver:true},/申报码单/]]){
    const client=currentTeamClient(()=>raw({form:false}),job,options);
    const adapter=makeTeamAdapter(client.request,()=>now,async()=>{});
    await assert.rejects(()=>adapter.prepare(job,'team',()=>true),why);
    assert.equal(client.actions.includes('verify team'),false);
    assert.equal(client.actions.includes('register team'),false);
  }
});

test('a missing team receipt preserves prior steps and never repeats registration or joins',async()=>{
  const client=currentTeamClient(()=>raw({form:false}),job,{noReceipt:true});
  const adapter=makeTeamAdapter(client.request,()=>now,async()=>{});
  let state={...job,id:'current-no-receipt',status:'waiting',bookingMode:'team_then_join',
    registrationOpenUtc:new Date(now-1000).toISOString(),teamProgress:{team:'waiting',driver:'waiting'}};
  const store={get:()=>state,updateTeam:(id,status,note,teamProgress,steps)=>{
    state={...state,status,note,teamProgress:{...teamProgress},teamSteps:{...steps}};
  }};
  await runTeamAppointment(store,adapter,state,()=>now);
  await runTeamAppointment(store,adapter,state,()=>now);
  assert.equal(state.status,'uncertain');
  assert.deepEqual(state.teamSteps,{car:'confirmed',team:'confirmed',roster:'confirmed',verify:'confirmed',submit:'unconfirmed'});
  assert.equal(client.actions.filter(action=>action==='register team').length,1);
  assert.equal(client.actions.includes('join as driver'),false);
});
