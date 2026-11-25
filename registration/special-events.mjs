import {durationLabel} from './race-details.mjs';
export const specialSource='https://www.iracing.com/special-events/';
const months=['January','February','March','April','May','June','July','August','September','October','November','December'];
const plain=s=>s.replace(/<[^>]*>/g,' ').replace(/&#(x[0-9a-f]+|\d+);/gi,(_,n)=>{const c=n[0].toLowerCase()==='x'?parseInt(n.slice(1),16):Number(n);return c>0&&c<=0x10ffff?String.fromCodePoint(c):'';}).replace(/&(?:amp|nbsp|ndash|mdash|uuml|Uuml);/g,x=>({'&amp;':'&','&nbsp;':' ','&ndash;':'–','&mdash;':'—','&uuml;':'ü','&Uuml;':'Ü'}[x])).replace(/\s+/g,' ').trim();
export function eventDates(value){
  value=value.replace(/\b(20\d)\s+(\d)\b/g,'$1$2');
  const m=value.match(/^([A-Za-z]+)\s+(\d{1,2})(?:\s*[-–—]\s*(?:([A-Za-z]+)\s+)?(\d{1,2}))?,\s*(20\d\d)$/);
  if(!m)return null;
  const month=s=>months.findIndex(x=>x.toLowerCase()===s.toLowerCase()||x.slice(0,3).toLowerCase()===s.toLowerCase());
  const a=month(m[1]),b=m[3]?month(m[3]):a;if(a<0||b<0)return null;
  const make=(mo,d)=>`${m[5]}-${String(mo+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
  const start=make(a,m[2]),end=make(b,m[4]||m[2]);
  if([start,end].some(x=>!Number.isFinite(Date.parse(x+'T12:00Z'))||new Date(x+'T12:00Z').toISOString().slice(0,10)!==x)||end<start)return null;
  return {start,end};
}
export function parseSpecialEvents(html){
  if(html.length>4000000)throw Error('特殊赛事日历过大');
  const year=[...html.matchAll(/<h1\b[^>]*>([\s\S]*?)<\/h1>/gi)].map(x=>plain(x[1]).match(/^(20\d\d) Special Events Calendar$/)?.[1]).find(Boolean);
  if(!year)throw Error('特殊赛事日历年份无法识别');
  const heads=[...html.matchAll(/<h2\b[^>]*>([\s\S]*?)<\/h2>/gi)],events=[];
  for(let i=0;i<heads.length;i++){
    const h=heads[i],name=plain(h[1]);
    const sectionStart=html.lastIndexOf('<section',h.index);
    const sectionEnd=html.indexOf('</section>',h.index);
    if(sectionStart<0||sectionEnd<0)continue;
    const block=html.slice(h.index+h[0].length,Math.min(sectionEnd,heads[i+1]?.index??html.length));
    if(!/Cars Competing/i.test(block))continue;
    const intro=block.split(/<h3\b/i)[0],paragraphs=[...intro.matchAll(/<p\b[^>]*>([\s\S]*?)<\/p>/gi)].map(x=>plain(x[1]));
    if(!paragraphs.length)throw Error('特殊赛事日期列无法识别：'+name);
    const dateLabel=paragraphs[0],dates=eventDates(dateLabel),description=paragraphs.slice(1).join(' ');
    const teamRace=/TEAM EVENT/.test(plain(html.slice(sectionStart,h.index)))||/team (?:event|racing|format)|with a team/i.test(description);
    const endurance=teamRace||/endurance|\b\d+\s*(?:hours?|HR|h)\b/i.test(name+' '+description);
    const carLabel=plain(block.match(/<summary\b[^>]*>([\s\S]*?)<\/summary>/i)?.[1]||'');
    const track=plain(intro.match(/<a\b[^>]*href=["'][^"']*\/tracks\/[^"']*["'][^>]*>([\s\S]*?)<\/a>/i)?.[1]||'');
    events.push({name,dateLabel,dates,description,teamRace,endurance,carLabel,track});
  }
  if(!events.length||new Set(events.map(e=>e.name)).size!==events.length)throw Error('特殊赛事日历结构异常，保留旧缓存');
  return {year:Number(year),events,source:specialSource};
}
export function includeSpecialEvents(catalog,calendar){
  const monday=catalog.monday||new Date(Date.parse(catalog.saturday+'T00:00Z')-5*86400000).toISOString().slice(0,10);
  const inWeekend=e=>e.dates&&e.dates.start<=catalog.sunday&&e.dates.end>=monday;
  const matching=calendar.events.filter(inWeekend),series=[...catalog.series];
  for(const e of matching.filter(e=>e.endurance)){
    // The public calendar shortens the name of the November 2026 Spa event.
    const spa992=e.name==='992 Endurance Cup'&&e.dates.start==='2026-11-27';
    const name=spa992?'Creventic 992 Endurance Cup':e.name;
    const track=e.track||(spa992?'Circuit de Spa-Francorchamps Endurance':'');
    const cars=spa992?['Porsche 911 Cup (992.2)']:[];
    if(series.some(s=>s.name===name))continue;
    const times=[...new Set([...e.description.matchAll(/\b(\d+(?:\.\d+)?)\s*[- ]\s*hours?\b/gi),...e.name.matchAll(/\b(\d+)\s*(?:hours?|hr|h)\b/gi)].map(m=>+m[1]*60))];
    const duration=times.length===1?{unit:'minutes',value:times[0],minutes:times[0],evidence:'官方特殊赛事说明'}:null;
    const labels=e.carLabel.split(/\s*\/\/\s*|\s*\\\\\s*/).filter(Boolean);
    const known=labels.length&&labels.every(x=>/GT[1-4]|GTP|HYP|LMP[23]|TCR|Touring|Porsche Cup|BMW M2/i.test(x));
    series.push({name,track,cars,slots:[],slotDetails:[],duration,minutes:duration?.minutes??null,durationLabel:durationLabel(duration),durationSource:specialSource,classes:spa992?[{name:'Porsche Cup',cars}]:known?labels.map(name=>({name,cars:[]})):[],multiclass:spa992?false:known?labels.length>1:null,classBasis:spa992?'官方特殊赛事说明及当前客户端车辆名单':'官方特殊赛事车辆分类；实际车型和分组需客户端核对',teamRace:e.teamRace,declaration:'unknown',specialEvent:true,source:specialSource,carSource:specialSource,dateLabel:e.dateLabel,carLabel:e.carLabel,detail:`特殊赛事 · ${e.dateLabel} · ${track||'赛道待核对'} · 具体开赛和报名开放时间待客户端确认`});
  }
  return {...catalog,series,specialCalendar:{year:calendar.year,observedAt:calendar.observedAt,source:specialSource,total:calendar.events.length,matched:matching.filter(e=>e.endurance).length,other:matching.filter(e=>!e.endurance).map(e=>({name:e.name,dateLabel:e.dateLabel})),undated:calendar.events.filter(e=>!e.dates).map(e=>({name:e.name,dateLabel:e.dateLabel}))}};
}
export async function fetchSpecialEvents(fetcher=fetch){
  const r=await fetcher(specialSource,{signal:AbortSignal.timeout(15000),redirect:'error'});
  if(!r.ok)throw Error('官方特殊赛事日历暂不可读');
  return {...parseSpecialEvents(await r.text()),observedAt:new Date().toISOString()};
}
