import {DatabaseSync} from 'node:sqlite';
import {randomUUID} from 'node:crypto';
import {VERSION} from './maintenance.mjs';
export class Store{
  constructor(file){
    this.db=new DatabaseSync(file);this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, session_key TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL, updated TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS rules(id TEXT PRIMARY KEY, weekday INTEGER NOT NULL, time TEXT NOT NULL, mode TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
      CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, job_id TEXT, at TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS registration_evidence(job_id TEXT PRIMARY KEY,invoke_at TEXT NOT NULL,invoke_state TEXT NOT NULL,confirm_at TEXT,confirm_state TEXT);`);
    this.db.exec('CREATE TABLE IF NOT EXISTS verification_checks(job_id TEXT PRIMARY KEY,payload TEXT NOT NULL)');
    this.db.exec('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)');
    this.db.exec('CREATE TABLE IF NOT EXISTS recovery_checks(job_id TEXT PRIMARY KEY,payload TEXT NOT NULL)');
    this.db.exec('CREATE INDEX IF NOT EXISTS events_job ON events(job_id,id); CREATE INDEX IF NOT EXISTS jobs_updated ON jobs(updated); CREATE TABLE IF NOT EXISTS issues(id INTEGER PRIMARY KEY,at TEXT NOT NULL,scope TEXT NOT NULL,code TEXT NOT NULL,note TEXT NOT NULL)');
    for(const row of this.db.prepare('SELECT job_id,payload FROM recovery_checks').all()){
      const r=JSON.parse(row.payload);if(r.status==='recovering')this.saveRecovery(row.job_id,{...r,status:'interrupted',message:'恢复期间助手曾退出；未确认恢复成功，已保留尝试次数'});
    }
    // Old clients could create lock-only jobs. Keep the original ID and deadline.
    this.db.exec(`UPDATE jobs SET payload=json_remove(payload,'$.requireLocked'),
      status=CASE WHEN status='blocked' AND note IN ('等待 Windows 锁屏后提交','提交前检测到锁屏状态变化，等待再次锁屏') THEN 'waiting' ELSE status END,
      note=CASE WHEN note IN ('等待 Windows 锁屏后提交','提交前检测到锁屏状态变化，等待再次锁屏') THEN '等待目标场次报名开放' ELSE note END
      WHERE status IN ('waiting','blocked') AND json_type(payload,'$.requireLocked') IS NOT NULL`);
    // Never resubmit a command whose completion is unknown after restart.
    for(const row of this.db.prepare("SELECT id FROM jobs WHERE status='submitting'").all())this.set(row.id,'uncertain','程序曾在提交期间退出；只核实结果，不重复报名');
  }
  get(id){const row=this.db.prepare('SELECT * FROM jobs WHERE id=?').get(id);const check=this.db.prepare('SELECT payload FROM verification_checks WHERE job_id=?').get(id);return row?{...JSON.parse(row.payload),id:row.id,status:row.status,note:row.note,updated:row.updated,verification:check?JSON.parse(check.payload):null,recovery:this.recovery(id)}:null;}
  recovery(id){const row=this.db.prepare('SELECT payload FROM recovery_checks WHERE job_id=?').get(id);return row?JSON.parse(row.payload):null;}
  saveRecovery(id,report){this.db.prepare('INSERT INTO recovery_checks VALUES(?,?) ON CONFLICT(job_id) DO UPDATE SET payload=excluded.payload').run(id,JSON.stringify(report));this.event(id,'recovery',report.message);}
  hasInvoke(id){return !!this.db.prepare('SELECT 1 FROM registration_evidence WHERE job_id=?').get(id);}
  lastRecoveryAt(){const rows=this.db.prepare('SELECT payload FROM recovery_checks').all();return rows.length?Math.max(...rows.map(r=>Date.parse(JSON.parse(r.payload).at))):null;}
  recordVerification(id,report){this.db.prepare('INSERT INTO verification_checks VALUES(?,?) ON CONFLICT(job_id) DO UPDATE SET payload=excluded.payload').run(id,JSON.stringify(report));}
  isPaused(){return this.db.prepare("SELECT value FROM settings WHERE key='scheduler_paused'").get()?.value==='true';}
  setPaused(paused){this.db.prepare("INSERT INTO settings VALUES('scheduler_paused',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value").run(String(paused));}
  list(limit=300){return this.db.prepare('SELECT id FROM jobs ORDER BY updated DESC LIMIT ?').all(limit).map(r=>this.get(r.id));}
  active(){return this.db.prepare("SELECT id FROM jobs WHERE status IN ('waiting','blocked','submitting','uncertain') ORDER BY updated").all().map(r=>this.get(r.id));}
  add(job){
    const storageKey=`${job.key}:${job.mode}`;
    const existing=this.db.prepare('SELECT id FROM jobs WHERE session_key=?').get(storageKey);if(existing)return this.get(existing.id);
    const id=randomUUID(),at=new Date().toISOString();
    this.db.prepare('INSERT INTO jobs VALUES(?,?,?,?,?,?)').run(id,storageKey,JSON.stringify({...job,appVersion:VERSION}),'waiting','等待目标场次报名开放',at);
    this.event(id,'waiting','已保存任务');return this.get(id);
  }
  addTeam(job){
    const existing=this.db.prepare('SELECT id FROM jobs WHERE session_key=?').get(`${job.key}:${job.mode}`);
    if(!existing)return this.add(job);
    const saved=this.get(existing.id);
    if(saved.status==='cancelled'&&!Object.values(saved.teamProgress).some(x=>x==='confirmed')){
      this.db.prepare('UPDATE jobs SET payload=? WHERE id=?').run(JSON.stringify({...job,appVersion:VERSION}),saved.id);
      return this.set(saved.id,'waiting','已重新保存车队预约。');
    }
    const fields=['bookingMode','car','track','ownDriverId','declaration','roster'];
    if(fields.some(field=>JSON.stringify(saved[field])!==JSON.stringify(job[field])))
      throw Error('同场次的车队已有预约。请先查看或取消之前的预约。');
    return saved;
  }
  updateTeam(id,status,note,progress,steps){
    const before=this.get(id);
    if(!before||before.kind!=='team_appointment')throw Error('车队预约不存在。');
    steps??=before.teamSteps||{};
    if(before.status===status&&before.note===note&&JSON.stringify(before.teamProgress)===JSON.stringify(progress)&&
       JSON.stringify(before.teamSteps||{})===JSON.stringify(steps))return before;
    this.db.exec('BEGIN IMMEDIATE');
    try{
      this.db.prepare("UPDATE jobs SET payload=json_set(payload,'$.teamProgress',json(?),'$.teamSteps',json(?)),status=?,note=?,updated=? WHERE id=?")
        .run(JSON.stringify(progress),JSON.stringify(steps),status,note,new Date().toISOString(),id);
      this.event(id,status,note);
      this.db.exec('COMMIT');
    }catch(error){this.db.exec('ROLLBACK');throw error;}
    return this.get(id);
  }
  recordTeamWithdrawal(id,state,message){
    const job=this.get(id);
    if(!job||job.kind!=='team_appointment'||job.teamProgress.team!=='confirmed')throw Error('未找到已确认的整队报名。');
    const at=new Date().toISOString(), status=state==='confirmed'?'withdrawn':job.status;
    const withdrawal={state,message,at,driverWithdrawn:state==='personal_confirmed'||!!job.teamWithdrawal?.driverWithdrawn};
    this.db.exec('BEGIN IMMEDIATE');
    try{
      this.db.prepare("UPDATE jobs SET payload=json_set(payload,'$.teamWithdrawal',json(?)),status=?,note=?,updated=? WHERE id=?")
        .run(JSON.stringify(withdrawal),status,state==='confirmed'?message:job.note,at,id);
      this.event(id,'withdrawal_'+state,message);
      this.db.exec('COMMIT');
    }catch(error){this.db.exec('ROLLBACK');throw error;}
    return this.get(id);
  }
  event(id,status,note){this.db.prepare('INSERT INTO events(job_id,at,status,note) VALUES(?,?,?,?)').run(id,new Date().toISOString(),status,note);}
  recordInvoke(id,r){if(!Number.isFinite(Date.parse(r?.invokedAt))||!['locked','unlocked','unobserved'].includes(r.invokeState))return;this.db.prepare('INSERT OR IGNORE INTO registration_evidence(job_id,invoke_at,invoke_state) VALUES(?,?,?)').run(id,r.invokedAt,r.invokeState);}
  recordConfirmation(id,raw){this.db.prepare('UPDATE registration_evidence SET confirm_at=?,confirm_state=? WHERE job_id=? AND confirm_at IS NULL').run(raw.observedAt,raw.lockState||'unobserved',id);}
  hasLockedReceipt(){return !!this.db.prepare("SELECT 1 FROM registration_evidence e JOIN jobs j ON j.id=e.job_id WHERE j.status='succeeded' AND e.invoke_state='locked' AND e.confirm_state='locked' AND e.confirm_at>=e.invoke_at LIMIT 1").get();}
  set(id,status,note){
    const before=this.get(id);if(!before)throw Error('任务不存在');
    if(before.status===status&&before.note===note)return before;
    this.db.prepare('UPDATE jobs SET status=?,note=?,updated=? WHERE id=?').run(status,note,new Date().toISOString(),id);
    this.event(id,status,note);return this.get(id);
  }
  cancel(id){const j=this.get(id);if(!j)throw Error('任务不存在');if(!['waiting','blocked'].includes(j.status))throw Error('任务已经执行或正在核实，不能当作未执行任务取消');return this.set(id,'cancelled','已取消预约；没有执行退赛');}
  resolve(id){const j=this.get(id);if(!j||j.status!=='uncertain')throw Error('只有结果待核实的任务可以结束跟踪');return this.set(id,'reviewed','用户已自行核实客户端并结束跟踪；不代表报名成功，没有执行退赛');}
  rules(){return this.db.prepare('SELECT * FROM rules ORDER BY rowid DESC').all();}
  addRule({weekday,time,mode}){if(!Number.isInteger(weekday)||weekday<0||weekday>6||!/^([01]\d|2[0-3]):[0-5]\d$/.test(time)||!['verify','live'].includes(mode))throw Error('每周预约参数不正确');const id=randomUUID();this.db.prepare('INSERT INTO rules VALUES(?,?,?,?,1)').run(id,weekday,time,mode);return id;}
  disableRule(id){this.db.prepare('UPDATE rules SET enabled=0 WHERE id=?').run(id);}
  events(){return this.db.prepare('SELECT * FROM events ORDER BY id DESC LIMIT 100').all();}
  history({page=0,status='all'}={}){
    if(!Number.isInteger(page)||page<0||page>100000)throw Error('历史页码无效');
    const states=['all','waiting','blocked','submitting','uncertain','succeeded','checked','cancelled','expired','reviewed','withdrawn'];
    if(!states.includes(status))throw Error('历史状态无效');
    const where=status==='all'?'':' WHERE status=?',args=status==='all'?[]:[status];
    const total=this.db.prepare('SELECT count(*) n FROM jobs'+where).get(...args).n;
    const jobs=this.db.prepare('SELECT id FROM jobs'+where+' ORDER BY updated DESC,id LIMIT 25 OFFSET ?').all(...args,page*25).map(r=>this.get(r.id));
    return {page,total,jobs};
  }
  historyDetail(id){const job=this.get(id);if(!job)throw Error('历史任务不存在');return {job,events:this.db.prepare('SELECT at,status,note FROM events WHERE job_id=? ORDER BY id').all(id),evidence:this.db.prepare('SELECT * FROM registration_evidence WHERE job_id=?').get(id)||null};}
  issue(scope,code,note){
    const safe=String(note).replace(/[a-f0-9]{64}/gi,'[密钥已隐藏]').slice(0,1200);
    const last=this.db.prepare('SELECT * FROM issues ORDER BY id DESC LIMIT 1').get();
    if(last?.scope===scope&&last.code===code&&last.note===safe&&Date.now()-Date.parse(last.at)<60000)return;
    this.db.prepare('INSERT INTO issues(at,scope,code,note) VALUES(?,?,?,?)').run(new Date().toISOString(),scope,code,safe);
    this.db.exec('DELETE FROM issues WHERE id NOT IN (SELECT id FROM issues ORDER BY id DESC LIMIT 1000)');
  }
  issues(){return this.db.prepare('SELECT at,scope,code,note FROM issues ORDER BY id DESC LIMIT 30').all();}
  close(){this.db.close();}
}
