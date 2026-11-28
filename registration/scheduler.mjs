import {assertTarget,SERIES,CAR,ZONE} from './racing.mjs';
import {Recovery,recoveryReason} from './recovery.mjs';
import {runTeamAppointment} from './team-appointment.mjs';
const localFormatter=new Intl.DateTimeFormat('en-US',{timeZone:ZONE,weekday:'short',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
export function matchesRule(rule,startUtc){
  const p=Object.fromEntries(localFormatter.formatToParts(new Date(startUtc)).map(p=>[p.type,p.value]));
  return ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].indexOf(p.weekday)===rule.weekday&&`${p.hour}:${p.minute}`===rule.time;
}
export function makeJob(snapshot,session,mode,ruleId=null){return {...session,series:SERIES,car:CAR,kind:'individual',season:snapshot.season,track:snapshot.track,mode,ruleId,createdAt:new Date().toISOString()};}
export class Scheduler{
  constructor(store,adapter,now=()=>Date.now(),teamAdapter=null){this.store=store;this.adapter=adapter;this.now=now;this.running=false;this.lastError=null;this.teamAdapter=teamAdapter;this.recovery=new Recovery(store,adapter,()=>this.now());}
  get paused(){return this.store.isPaused();}
  pause(){this.store.setPaused(true);}
  resume(){if(this.running)throw Error('仍有操作正在结束，请稍后恢复');this.store.setPaused(false);}
  async tick(){
    if(this.running||this.paused)return;this.running=true;
    try{
      const now=this.now();
      const individual=()=>this.store.active().filter(j=>j.kind!=='team_appointment');
      for(const job of individual()){
        if(['waiting','blocked'].includes(job.status)&&Date.parse(job.startUtc)-now<=180000)this.store.set(job.id,'expired','距开赛不足 3 分钟，本场未提交。最后记录：'+job.note);
      }
      let jobs=individual().filter(j=>['waiting','blocked','uncertain'].includes(j.status));
      const team=this.store.active().filter(j=>j.kind==='team_appointment');
      const rules=this.store.rules().filter(r=>r.enabled);
      // An uncertain registration blocks new submissions until explicitly resolved.
      const uncertain=[...jobs,...team].find(j=>j.status==='uncertain');
      if(uncertain){
        if(uncertain.kind==='team_appointment'){
          if(this.teamAdapter)await runTeamAppointment(this.store,this.teamAdapter,uncertain,this.now,()=>this.paused);
          return;
        }
        const confirmed=await this.adapter.verify(uncertain);
        this.lastError=null;
        if(confirmed)this.store.set(uncertain.id,'succeeded','已重新读取并确认目标场次报名');
        return;
      }
      const dueTeam=team.find(j=>['waiting','blocked'].includes(j.status)&&now>=Date.parse(j.registrationOpenUtc));
      if(dueTeam&&this.teamAdapter){
        await runTeamAppointment(this.store,this.teamAdapter,dueTeam,this.now,()=>this.paused);
        return;
      }
      if(!jobs.length&&!rules.length)return;
      if(!rules.length&&!jobs.some(j=>Date.parse(j.startUtc)-now<=31*60000))return;
      const due=j=>Date.parse(j.startUtc)-now<=31*60000;
      let snapshot;
      try{snapshot=await this.adapter.snapshot();}catch(e){
        for(const j of individual().filter(j=>due(j)&&['waiting','blocked'].includes(j.status)))this.store.set(j.id,j.status,'读取客户端失败：'+e.message);
        for(const j of individual().filter(j=>due(j)&&['waiting','blocked'].includes(j.status)))if(await this.recovery.consider(j,recoveryReason(null,e),()=>this.paused))break;
        throw e;
      }
      this.lastError=null;
      if(this.paused)return;
      for(const rule of rules)for(const session of snapshot.sessions)if(matchesRule(rule,session.startUtc))this.store.add(makeJob(snapshot,session,rule.mode,rule.id));
      jobs=individual().filter(j=>['waiting','blocked'].includes(j.status));
      for(const job of jobs){
        if(job.startUtc!==snapshot.nextStartUtc){
          this.recovery.clear(job.id);
          if(due(job))this.store.set(job.id,'waiting','UI 当前展示的下一场为 '+new Date(snapshot.nextStartUtc).toLocaleTimeString('zh-CN',{timeZone:ZONE,hour:'2-digit',minute:'2-digit',hourCycle:'h23'})+'（多伦多），尚未匹配目标场次');
          continue;
        }
        let alreadyRegistered;
        try{alreadyRegistered=await this.adapter.verify(job);}catch(e){
          if(['waiting','blocked'].includes(this.store.get(job.id).status))this.store.set(job.id,'blocked','读取报名状态失败：'+e.message);
          throw e;
        }
        if(!['waiting','blocked'].includes(this.store.get(job.id).status))continue;
        if(alreadyRegistered){this.store.set(job.id,job.mode==='verify'?'checked':'succeeded','检测到目标场次已经报名，未重复提交');continue;}
        if(this.paused)return;
        try{assertTarget(snapshot,job,this.now());}catch(e){
          this.store.set(job.id,'blocked',e.message);
          if(await this.recovery.consider(job,recoveryReason(snapshot),()=>this.paused))return;
          continue;
        }
        this.recovery.clear(job.id);
        // Cancel may have been requested while the read was in flight.
        if(!['waiting','blocked'].includes(this.store.get(job.id).status))continue;
        if(job.mode==='verify'){this.store.set(job.id,'checked','检查通过：系列、车辆、场次和报名按钮匹配；未报名');continue;}
        this.store.set(job.id,'submitting','正在提交；重复触发不会再次点击');
        try{
          await this.adapter.register(job);
          if(await this.adapter.verify(job))this.store.set(job.id,'succeeded','已重新读取并确认目标场次报名');
          else this.store.set(job.id,'uncertain','已触发报名，但尚未取得完整成功凭据；请查看 iRacing，程序不会重复提交');
        }catch(e){
          if(e.code==='PAUSED_BEFORE_SUBMIT')this.store.set(job.id,'waiting','执行已暂停，尚未发出报名命令');
          else this.store.set(job.id,'uncertain',`提交结果待核实：${e.message}`);
        }
        break;
      }
    }catch(e){this.lastError=e.message;}finally{this.running=false;}
  }
}
