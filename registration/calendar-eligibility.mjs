const official='https://members-ng.iracing.com/web/racing/';
const clean=value=>String(value??'').replace(/\ufffc/g,'').replace(/\s+/g,' ').trim();
const key=value=>clean(value).normalize('NFD').replace(/\p{Diacritic}/gu,'').replace(/[^\p{L}\p{N}]/gu,'').toLowerCase();
const type=(node,tag)=>node.type==='ControlType.'+tag;
const one=list=>list.length===1?list[0]:null;
const sportsClasses=new Set(['Porsche Cup','GT3','GT4','TCR','GTP / Hypercar','LMP2','LMP3','BMW M2','GR86','Clio','MX-5']);
const disciplines={
  'OVAL RACING':'Oval','SPORTS CAR RACING':'Sports Car','FORMULA RACING':'Formula',
  'DIRT OVAL RACING':'Dirt Oval','DIRT ROAD RACING':'Dirt Road'
};

function nodesAt(raw,path){
  if(!raw?.ok||raw.url!==official+path||!Array.isArray(raw.nodes))throw Error('请在已登录的 iRacing 客户端重新读取资格。');
  return raw.nodes;
}

export function readLicenses(raw){
  const text=nodesAt(raw,'profile').filter(n=>type(n,'Text'));
  const licenses={};
  for(const [heading,discipline] of Object.entries(disciplines)){
    const marker=one(text.filter(n=>clean(n.name)===heading));
    if(!marker)continue;
    const next=text.filter(n=>n.parent===marker.parent&&n.index>marker.index).slice(0,4);
    const i=next.findIndex(n=>/^(Rookie|Class [A-D]|Pro|Pro\/WC|World Championship)$/i.test(clean(n.name)));
    const rating=clean(next[i+1]?.name);
    if(i>=0&&/^\d\.\d{2}$/.test(rating))licenses[discipline]=clean(next[i].name)+' '+rating;
  }
  if(!Object.keys(licenses).length)throw Error('个人资料页面未读到可核实的驾照，稍后重新读取。');
  return licenses;
}

function licensedRows(raw,kind){
  const nodes=nodesAt(raw,'licensed-content/'+kind);
  const column=kind==='cars'?'Car Name':'Track Name';
  const byIndex=new Map(nodes.map(n=>[n.index,n]));
  const header=one(nodes.filter(n=>type(n,'DataItem')&&clean(n.name)===column));
  const headers=byIndex.get(header?.parent);
  const table=byIndex.get(headers?.parent);
  if(!table||!type(table,'Table'))throw Error('My Content 没有显示可读取的 '+column+' 列，请在客户端切换到 List。');
  const fields=nodes.filter(n=>n.parent===headers.index&&type(n,'DataItem'));
  const col=fields.indexOf(header);
  const rows=nodes.filter(n=>n.parent===table.index&&n!==headers&&type(n,'DataItem'));
  const contents=rows.map(row=>{
    const cells=nodes.filter(n=>n.parent===row.index&&type(n,'DataItem'));
    const favorite=nodes.find(n=>n.id?.startsWith('favorite_'+kind+'-')&&byIndex.get(byIndex.get(n.parent)?.parent)?.parent===row.index);
    return favorite&&cells.length===fields.length?clean(cells[col]?.name):'';
  });
  const clear=one(nodes.filter(n=>n.id==='content-clear-button'&&clean(n.name)==='Clear Filters'));
  const paginated=nodes.some(n=>/^(?:Next|Previous) Page$|^Page \d+ of \d+$/.test(clean(n.name)));
  return {contents,unfiltered:clear?.enabled===false&&!paginated};
}

export function readLicensedContent(raw,kind){
  const {contents,unfiltered}=licensedRows(raw,kind);
  return {names:contents.filter(Boolean),complete:unfiltered&&contents.length>0&&contents.every(Boolean)};
}

export async function readFullLicensedContent(request,raw,kind){
  const first=licensedRows(raw,kind);
  const rows=[...first.contents];
  let dependable=first.unfiltered;
  for(let attempt=0;dependable&&rows.includes('')&&attempt<12;attempt++){
    const pending=rows.flatMap((name,i)=>name?[]:[i]);
    const row=pending[Math.min(8,Math.floor(pending.length/2))];
    let view;
    try{view=await request('licensed_row',{tab:kind,row},30000);}
    catch{break;}
    const next=licensedRows(view,kind);
    if(!next.unfiltered||next.contents.length!==rows.length||
       next.contents.some((name,i)=>name&&rows[i]&&key(name)!==key(rows[i]))){dependable=false;break;}
    if(!next.contents.some((name,i)=>name&&!rows[i]))break;
    for(const [i,name] of next.contents.entries())if(name)rows[i]=name;
  }
  return {names:[...new Set(rows.filter(Boolean))],complete:dependable&&rows.length>0&&rows.every(Boolean)};
}

const grade=value=>{
  const m=/^(Rookie|(?:Class )?[A-D]|Pro|Pro\/WC|World Championship)\s+(\d\.\d{1,2})$/i.exec(clean(value));
  if(!m)return null;
  const rank=['ROOKIE','D','C','B','A','PRO','PRO/WC'].indexOf(m[1].toUpperCase().replace(/^CLASS /,'').replace('WORLD CHAMPIONSHIP','PRO/WC'));
  return rank*100+Number(m[2]);
};

function checkLicense(event,profile){
  const groups=event.classes||[];
  const discipline=event.licenseDiscipline||((groups.length&&!event.unknownCars?.length&&groups.every(g=>sportsClasses.has(g.name)))?'Sports Car':null);
  const current=profile?.licenses?.[discipline];
  const requirement=event.licenseRequirement;
  const actual=grade(current), minimum=grade(requirement?.minimum), maximum=grade(requirement?.maximum);
  return {current,discipline,requirement:requirement?.minimum,
    status:actual===null||minimum===null||maximum===null?'unknown':actual>=minimum&&actual<=maximum?'met':'missing'};
}

const listed=(name,inventory)=>inventory?.names?.some(x=>key(x)===key(name));
// A published layout and a legacy track package with a year in its name are different fields.
function checkTrack(track,inventory){
  if(!clean(track)||!inventory)return 'unknown';
  const exact=listed(track,inventory);
  const layout=/^(.*) - (?:International|Endurance|Grand Prix.*|GP|National|Road Course.*|Full Course.*|Club.*|Combined.*|Nordschleife.*|Oval.*|Classic.*|Complete|No Chicane.*|Short.*|Long.*|Config(?:uration)? .*)$/i.exec(track);
  if(exact||layout&&listed(layout[1],inventory))return 'met';
  if(!inventory.complete||(!layout&&track.includes(' - ')))return 'unknown';
  return 'missing';
}

export function assessCalendarEligibility(event,profile){
  const license=checkLicense(event,profile);
  const track={status:checkTrack(event.track,profile?.tracks)};
  const allowed=event.cars||[];
  const owned=allowed.filter(name=>listed(name,profile?.cars));
  const car={owned,status:owned.length?'met':allowed.length&&profile?.cars?.complete?'missing':'unknown'};
  const statuses=[license.status,track.status,car.status];
  return {status:statuses.includes('missing')?'blocked':statuses.every(s=>s==='met')?'eligible':'unknown',license,track,car};
}

export function withCalendarEligibility(catalog,profile,now=Date.now()){
  const age=now-Date.parse(profile?.observedAt);
  const current=Number.isFinite(age)&&age>=0&&age<=2*3600000?profile:null;
  return {...catalog,eligibilityCheckedAt:current?.observedAt||null,eligibilityPartial:!!current&&(!current.cars?.complete||!current.tracks?.complete),
    series:catalog.series.map(event=>({...event,eligibility:assessCalendarEligibility(event,current)}))};
}
