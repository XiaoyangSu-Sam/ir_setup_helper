import {test} from 'node:test';
import assert from 'node:assert/strict';
import {makeTeamAppointment, runTeamAppointment} from '../../registration/team-appointment.mjs';

const startUtc='2026-11-28T07:00:00.000Z';
const registrationOpenUtc='2026-11-28T06:00:00.000Z';
const plan={kind:'team_then_join',series:'Endurance Cup',teamId:'20',teamName:'Example Team',car:'Cup Car',startUtc,
  declaration:'required',roster:['31','32'],ownDriverId:'31',missing:[],revision:7};
const event={name:plan.series,track:'Spa - Endurance',teamRace:true,cars:['Cup Car'],minDrivers:2,maxDrivers:16,
  declaration:'required',slotDetails:[{startUtc,registrationOpenUtc,registrationKind:'confirmed'}]};
const directory={teamId:'20',teamName:plan.teamName,members:[{id:'31',name:'Example Driver'},{id:'32',name:'Second Driver'}]};
const earlier=Date.parse(registrationOpenUtc)-1000, within=earlier+2000;
const build=(changes={})=>makeTeamAppointment({...plan,...changes},event,directory,earlier);

function fixture(overrides={},kind='team_then_join'){
  let state={...build({kind}),id:'job',status:'waiting'};
  const calls=[], receipts={team:false,driver:false};
  const store={get:()=>state,updateTeam:(id,status,note,progress)=>state={...state,status,note,teamProgress:progress}};
  const adapter={
    prepare:async(j,phase)=>{calls.push('prepare:'+phase);return receipts[phase]?{confirmed:true}:{action:true};},
    submit:async(j,phase)=>{calls.push('submit:'+phase);receipts[phase]=true;return {invoked:true};},
    verify:async(j,phase)=>{calls.push('verify:'+phase);return receipts[phase];},
    ...overrides
  };
  return {store,adapter,calls,get job(){return state;}};
}

test('appointment freezes the official slot and checks roster, ownership identity and rules',()=>{
  const j=build();
  assert.equal(j.registrationOpenUtc,registrationOpenUtc);
  assert.equal(j.ownDriverName,'Example Driver');
  assert.deepEqual(j.driverNames,['Example Driver','Second Driver']);
  assert.throws(()=>build({roster:['31']}));
  assert.throws(()=>build({ownDriverId:'33'}));
  assert.throws(()=>build({startUtc:'2026-11-28T08:00:00.000Z'}));
});

test('waits for the published window then confirms both phases in order',async()=>{
  const f=fixture();
  await runTeamAppointment(f.store,f.adapter,f.job,()=>earlier);
  assert.deepEqual(f.calls,[]);
  await runTeamAppointment(f.store,f.adapter,f.job,()=>within);
  assert.equal(f.job.status,'waiting');
  assert.equal(f.job.teamProgress.team,'confirmed');
  await runTeamAppointment(f.store,f.adapter,f.job,()=>within);
  assert.equal(f.job.status,'succeeded');
  assert.equal(f.job.teamProgress.driver,'confirmed');
  assert.deepEqual(f.calls,['prepare:team','submit:team','verify:team','prepare:driver','submit:driver','verify:driver']);
});

test('an unknown result permits only verification and retains the confirmed team phase',async()=>{
  const f=fixture({submit:async(job,phase)=>{
    assert.equal(f.job.status,'submitting');
    if(phase==='driver')throw Error('connection lost');
    return {invoked:true};
  },verify:async(job,phase)=>phase==='team'});
  await runTeamAppointment(f.store,f.adapter,f.job,()=>within);
  await runTeamAppointment(f.store,f.adapter,f.job,()=>within);
  assert.equal(f.job.status,'uncertain');
  assert.deepEqual(f.job.teamProgress,{team:'confirmed',driver:'unconfirmed'});
  await runTeamAppointment(f.store,f.adapter,f.job,()=>within);
  assert.equal(f.job.status,'uncertain');
  assert.deepEqual(f.calls,['prepare:team','prepare:driver']);
});

test('join-only submits only the driver identity and team-only never joins',async()=>{
  for(const [kind,phase] of [['join_team','driver'],['team_registration','team']]){
    const f=fixture({},kind);
    await runTeamAppointment(f.store,f.adapter,f.job,()=>within);
    assert.deepEqual(f.calls,['prepare:'+phase,'submit:'+phase,'verify:'+phase]);
    assert.equal(f.job.status,'succeeded');
  }
});

test('pre-submit failure or cancellation cannot click',async()=>{
  const f=fixture({prepare:async()=>{throw Error('wrong slot');}});
  await runTeamAppointment(f.store,f.adapter,f.job,()=>within);
  assert.equal(f.job.status,'blocked');
  assert.equal(f.job.teamProgress.team,'waiting');
  const g=fixture({prepare:async()=>{
    g.store.updateTeam(g.job.id,'cancelled','cancelled',g.job.teamProgress);
    return {action:true};
  }});
  await runTeamAppointment(g.store,g.adapter,g.job,()=>within);
  assert.equal(g.job.status,'cancelled');
  assert.deepEqual(g.calls,[]);
});
