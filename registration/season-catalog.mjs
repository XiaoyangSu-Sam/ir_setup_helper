import {weekend,nec} from './endurance.mjs';
import {describeSlot,parseRaceDuration,classDetails,durationLabel,registrationSource} from './race-details.mjs';
export const scheduleSource='https://members-assets.iracing.com/public/schedulepdf/SeasonSchedule.pdf';
export const scheduleSchema=3;
const day=86400000,zone='America/Toronto';
const clean=s=>s.replace(/\s+/g,' ').trim();
const local=ms=>{const p=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(ms).map(x=>[x.type,x.value]));return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;};
export function selectedWeekend(date){
  if(date===undefined||date==='')return weekend();
  if(typeof date!=='string'||!/^20\d\d-\d\d-\d\d$/.test(date)||!Number.isFinite(Date.parse(date+'T12:00Z'))||new Date(date+'T12:00Z').toISOString().slice(0,10)!==date)throw Error('请选择有效的周末日期');
  return weekend(Date.parse(date+'T12:00Z'));
}
export function raceSlotDetails(rule,w){
  const names=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
  const re=/\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)s?\b([^]*?)(?=\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)s?\b|$)/gi;
  const found=[...rule.matchAll(re)],slots=[];
  if(!found.length||!rule.includes('GMT'))return [];
  for(const m of found){
    // Every group must explicitly contain GMT. Never infer time zones.
    if(!m[2].includes('GMT')||/\b(?:ET|local|EST|EDT)\b/i.test(m[2]))return [];
    const timeText=m[2].split('GMT')[0].replace(/^\s*(?:at\s+)?/i,'');
    if(!/^[\d\s:,&and]+$/i.test(timeText))return [];
    const times=[...timeText.matchAll(/\b([01]?\d|2[0-3])(?::([0-5]\d))?\b/g)];
    const offset=names.findIndex(x=>x.toLowerCase()===m[1].toLowerCase())-5;
    for(const t of times)for(const weekOffset of [0,7]){
      const stamp=Date.parse(w.saturday+'T00:00Z')+(offset+weekOffset)*day+(+t[1]*60+ +(t[2]||0))*60000;
      const value=local(stamp),date=value.slice(0,10);
      const monday=w.monday||new Date(Date.parse(w.saturday+'T00:00Z')-5*day).toISOString().slice(0,10);
      if(date>=monday&&date<=w.sunday)slots.push(describeSlot(stamp));
    }
  }
  return [...new Map(slots.map(s=>[s.startUtc,s])).values()].sort((a,b)=>a.startUtc.localeCompare(b.startUtc));
}
export function raceSlots(rule,w){return raceSlotDetails(rule,w).map(x=>x.localStart);}
export function readRaceWeather(row){
  if(/\bAll dry events\b/i.test(row))return {kind:'dry',source:scheduleSource};
  const match=row.match(/\bRain chance\s+(None|\d{1,3}\s*%)(?:\s*\(\s*(\d{1,3})\s*%\s+before session\s*\))?/i);
  if(!match)return {kind:'unknown'};
  const rainChance=/none/i.test(match[1])?0:parseInt(match[1],10);
  const before=match[2]===undefined?null:Number(match[2]);
  if(rainChance>100)return {kind:'unknown'};
  return {kind:'forecast',rainChance,beforeChance:before!==null&&before<=100?before:null,source:scheduleSource};
}
export function parseSeasonText(text,w){
  const headings=[...text.matchAll(/^((?:[^\n]+\b20\d\d Season|20\d\d [A-Za-z])[^\n]*)$/gm)].filter(m=>!/\.\s*\.\s*\./.test(m[1])),series=[],warnings=[];
  for(let i=0;i<headings.length;i++){
    const title=clean(headings[i][1]);
    if(/\.{3}/.test(title))continue;
    const block=text.slice(headings[i].index+headings[i][0].length,headings[i+1]?.index??text.length);
    const header=block.split(/Week \d+ \(/)[0];
    const rows=[...block.matchAll(/Week (\d+) \((20\d\d-\d\d-\d\d)\)([^]*?)(?=Week \d+ \(|$)/g)];
    const row=rows.find(m=>selectedWeekend(m[2]).saturday===w.saturday);
    if(!row)continue;
    const duration=parseRaceDuration(row[3]),minutes=duration?.minutes??null;
    if(!/Endurance|Team racing/i.test(title+' '+header)&&minutes<120)continue;
    const track=clean(row[3].split(/\(20\d\d-\d\d-\d\d\s/)[0]);
    if(!track||track.length>180)throw Error('官方赛程赛道列无法识别');
    const carText=clean(header.split(/(?:Rookie|Class [A-D]) \d\.\d\s*-->/)[0].replace(/-\s*\n\s*/g,'-'));
    const cars=carText.split(/,\s*/).filter(Boolean);
    if(!cars.length||cars.some(x=>x.length>100))throw Error('官方赛程车辆列无法识别');
    const rule=clean(header.match(/Races[^]*?(?=Min entries)/)?.[0]||
      header.split('\n').find(line=>/^\s*(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b.*\bGMT\b/i.test(line))||'');
    const slotDetails=raceSlotDetails(rule,w),slots=slotDetails.map(s=>s.localStart);
    let name=title.replace(/(?: -)? 20\d\d Season.*$/,'').replace(/^20\d\d /,'');
    if(/n[uü]rburgring endurance/i.test(name))name=nec;
    const minDrivers=Number(row[3].match(/Min\s+(\d+)\s+driver/)?.[1]||0)||null;
    const maxDrivers=Number(row[3].match(/Max\s+(\d+)\s+driver/)?.[1]||0)||null;
    if(!slots.length)warnings.push(name+'：时间规则尚不能自动解析，请在客户端核对');
    if(!duration)warnings.push(name+'：本周 Race duration 列无法可靠读取，请在客户端核对');
    series.push({name,season:title,cars,slots,slotDetails,track,minutes,duration,durationLabel:durationLabel(duration),durationSource:scheduleSource,scheduleWeek:row[2],...classDetails(cars,row[3]),registrationSource,teamRace:/Team racing/i.test(header),minDrivers,maxDrivers,declaration:/Declare\s+drivers/i.test(row[3])?'required':'unknown',detail:track,source:scheduleSource,carSource:scheduleSource,raceRule:rule,weather:readRaceWeather(row[3])});
  }
  if(!headings.length)throw Error('官方赛季赛程格式无法识别');
  if(new Set(series.map(x=>x.name)).size!==series.length)throw Error('同系列出现多个赛季，请在客户端核对，未覆盖旧资料');
  const dates=[...text.matchAll(/Week \d+ \((20\d\d-\d\d-\d\d)\)/g)].map(m=>selectedWeekend(m[1]).saturday).sort();
  const seasonCoverage={firstWeekend:dates[0],lastWeekend:dates.at(-1)};
  if(!dates.length)throw Error('官方赛季赛程没有可识别的周次日期');
  if(w.saturday<dates[0]||w.saturday>dates.at(-1))warnings.push('所选周末超出当前赛季 PDF 的日期范围；不能据此判断该周没有常规耐力赛');
  return {...w,schemaVersion:scheduleSchema,series,warnings,seasonCoverage,source:scheduleSource,note:'按多伦多周一至周日扫描官方车队赛和至少 120 分钟的定时赛。预计报名时间不代表客户端已开放。'};
}
export async function pdfText(bytes){
  const {getDocument}=await import('./runtime/pdfjs/legacy/build/pdf.mjs');
  const doc=await getDocument({data:new Uint8Array(bytes),isEvalSupported:false,useSystemFonts:false,disableFontFace:true,verbosity:0}).promise;
  try{
    if(doc.numPages>500)throw Error('官方赛程页数异常');
    let text='';
    for(let i=1;i<=doc.numPages;i++){
      const p=await doc.getPage(i),content=await p.getTextContent();
      text+=content.items.map(x=>x.str+(x.hasEOL?'\n':' ')).join('')+'\n';
      p.cleanup();
    }
    return text;
  }finally{await doc.destroy();}
}
export async function fetchSeasonText(fetcher=fetch){
  const r=await fetcher(scheduleSource,{signal:AbortSignal.timeout(20000),redirect:'error'});
  if(!r.ok)throw Error('官方完整赛程暂不可读');
  const bytes=new Uint8Array(await r.arrayBuffer());
  if(bytes.length>15000000||new TextDecoder().decode(bytes.slice(0,5))!=='%PDF-')throw Error('官方赛程文件异常');
  return pdfText(bytes);
}
