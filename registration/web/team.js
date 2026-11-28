(()=>{
  const sheet=document.getElementById('team-sheet');
  const form=document.getElementById('team-form');
  const fields=document.getElementById('team-fields');
  const result=document.getElementById('team-result');
  const reload=document.getElementById('team-reload');
  const inspect=document.getElementById('team-inspect');
  const progress=document.getElementById('team-progress');
  inspect.textContent='检查赛车、赛道和驾照';
  const input=name=>form.elements.namedItem(name);
  let revision=null;
  let dirty=false;
  let catalog,directory,members=null,memberSelection=false;
  let calendarDay='';
  const el=id=>document.getElementById(id);
  const todayFormatter=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Toronto',year:'numeric',month:'2-digit',day:'2-digit'});
  const today=()=>todayFormatter.format(new Date());
  const weekdays=['周一','周二','周三','周四','周五','周六','周日'];
  const trackNames=[
    [/spa-francorchamps/i,'斯帕-弗朗科尔尚赛道'],[/n[uü]rburgring|nordschleife/i,'纽博格林赛道'],
    [/daytona/i,'代托纳国际赛道'],[/sebring/i,'赛百灵国际赛道'],[/watkins glen/i,'沃特金斯格伦国际赛道'],
    [/road atlanta/i,'亚特兰大公路赛道'],[/road america/i,'美洲公路赛道'],[/circuit of the americas/i,'美洲赛道'],
    [/laguna seca/i,'拉古纳塞卡赛道'],[/virginia international/i,'弗吉尼亚国际赛道'],[/indianapolis/i,'印第安纳波利斯赛道'],
    [/mount panorama|bathurst/i,'巴瑟斯特全景山赛道'],[/suzuka/i,'铃鹿赛道'],[/fuji/i,'富士赛道'],[/okayama/i,'冈山国际赛道'],
    [/motegi/i,'茂木赛道'],[/tsukuba/i,'筑波赛道'],[/silverstone/i,'银石赛道'],[/brands hatch/i,'布兰兹哈奇赛道'],
    [/donington/i,'多宁顿公园赛道'],[/oulton park/i,'奥尔顿公园赛道'],[/snetterton/i,'斯内特顿赛道'],
    [/imola|enzo e dino/i,'伊莫拉赛道'],[/monza/i,'蒙扎赛道'],[/mugello/i,'穆杰洛赛道'],
    [/barcelona|catalunya/i,'巴塞罗那-加泰罗尼亚赛道'],[/aragon|aragón/i,'阿拉贡赛道'],
    [/algarve|portim[aã]o/i,'阿尔加维国际赛道（波尔蒂芒）'],[/estoril/i,'埃斯托里尔赛道'],
    [/le mans|sarthe/i,'勒芒萨尔特赛道'],[/magny-cours/i,'马尼库尔赛道'],[/dijon/i,'第戎赛道'],
    [/zandvoort/i,'赞德沃特赛道'],[/zolder/i,'佐尔德赛道'],[/red bull ring/i,'红牛环赛道'],
    [/interlagos|jos[eé] carlos pace/i,'因特拉格斯赛道'],[/hockenheim/i,'霍根海姆赛道'],
    [/misano/i,'米萨诺赛道'],[/hungaroring/i,'匈牙利亨格罗林赛道'],[/jerez/i,'赫雷斯赛道'],
    [/mosport|canadian tire/i,'加拿大轮胎赛车公园（莫斯波特）'],[/l[aá]nke/i,'兰克赛道'],
    [/summit point/i,'萨米特角赛道']
  ];

  function chineseTrack(track){
    const name=trackNames.find(([pattern])=>pattern.test(track||''))?.[1];
    if(!name)return '';
    const layout=track.match(/\bEndurance\b/i)?'耐力布局':/\bGrand Prix\b/i.test(track)?'大奖赛布局':
      /\b(?:VLN|NLS)\b/i.test(track)?'VLN / NLS 布局':/\bRoad Course\b/i.test(track)?'公路布局':'';
    return layout?name+' · '+layout:name;
  }

  function weatherText(weather){
    if(weather?.kind==='dry')return {label:'干地设定',type:'dry'};
    if(weather?.kind==='forecast'){
      const rain=weather.rainChance>0||weather.beforeChance>0;
      return {label:weather.rainChance>0?'降雨 '+weather.rainChance+'%':'场内降雨 0%',
        detail:weather.beforeChance===null||weather.beforeChance===undefined?'':'赛前 '+weather.beforeChance+'%',
        type:rain?'rain':'dry'};
    }
    if(weather?.kind==='dynamic')return {label:'动态天气',detail:'降雨概率待确认'};
    return {label:'天气待确认'};
  }

  const calendarHeadings=['开赛','赛事 / 赛道','我的资格','最低驾照','车辆组别','比赛时长','报名窗口','天气'];
  const slotKey=slot=>slot?.startUtc||slot?.localStart||'';
  const raceSlots=entry=>entry?.slotDetails?.length?entry.slotDetails:
    (entry?.slots||[]).map(localStart=>({localStart,startLabel:localStart.replace('T',' ')}));
  const classesText=entry=>(entry.classes||[]).map(x=>x.name).join('、');
  const minimumLicense=entry=>entry.licenseRequirement?.minimum?.replace(/^Class\s+/i,'')||'待核对';

  function eligibilityText(eligibility){
    if(!eligibility)return {status:'unknown',label:'待核对',detail:''};
    const items=[['驾照',eligibility.license],['赛车授权',eligibility.car],['赛道授权',eligibility.track]];
    const missing=items.filter(([,item])=>item.status==='missing').map(([name])=>name);
    const unknown=items.filter(([,item])=>item.status==='unknown').map(([name])=>name);
    return {status:eligibility.status,label:missing.length?'缺'+missing.join('、'):eligibility.status==='eligible'?'符合条件':'待核对',
      detail:unknown.length?'待核对：'+unknown.join('、'):''};
  }

  function chooseCalendarSlot(entry,slot){
    const same=input('series').value===entry.name;
    choices(entry.name,slotKey(slot),same?input('car').value:'');
    if(!same)input('declaration').value=entry.declaration||'unknown';
    invalidate();
    const feedback=el('calendar-feedback');
    feedback.hidden=false;
    feedback.textContent='已选择 '+entry.name+' '+(slot?.startLabel||'（开赛时间待确认）')+'。';
    el('selected-race').scrollIntoView({block:'start'});
    el('selected-race-title').focus({preventScroll:true});
  }

  function renderCalendar(visible,selected){
    const overview=el('week-calendar'), rail=el('calendar-days'), agenda=el('calendar-agenda');
    const scope=el('calendar-selected-only');
    const eligible=el('calendar-eligible-only');
    if(!selected)scope.checked=false;
    scope.disabled=!selected;
    eligible.disabled=!catalog.eligibilityCheckedAt;
    if(eligible.disabled)eligible.checked=false;
    const candidates=scope.checked&&selected?[selected]:visible;
    const events=eligible.checked?candidates.filter(event=>event.eligibility?.status==='eligible'):candidates;
    const waiting=candidates.filter(event=>event.eligibility?.status==='unknown').length;
    el('calendar-eligibility-status').textContent=catalog.eligibilityCheckedAt?
      '已按 iRacing 账号资料核对 · '+fmt(catalog.eligibilityCheckedAt)+'（多伦多）。开放时间见各场。'+(catalog.eligibilityPartial?' 授权列表未读全，部分资格待核对。':'')+
      (eligible.checked&&waiting?' · 已隐藏 '+waiting+' 个待核对系列。':''):
      '读取 iRacing 的驾照和授权后可按资格筛选。';
    const days=weekdays.map((label,i)=>{
      const date=new Date(Date.parse(catalog.monday+'T12:00Z')+i*86400000).toISOString().slice(0,10);
      return {date,label,rows:[]};
    });
    const unscheduled=[];
    for(const entry of events){
      const slots=raceSlots(entry);
      if(!slots.length)unscheduled.push({entry});
      for(const slot of slots){
        const day=days.find(d=>d.date===slot.localStart.slice(0,10));
        if(day)day.rows.push({entry,slot});
      }
    }
    overview.hidden=false;
    const date=today();
    el('calendar-date').textContent='今天 '+date+' · 多伦多 · '+catalog.monday.slice(5)+' 至 '+catalog.sunday.slice(5);
    rail.replaceChildren();
    for(const day of days){
      day.rows.sort((a,b)=>a.slot.localStart.localeCompare(b.slot.localStart)||slotKey(a.slot).localeCompare(slotKey(b.slot)));
      const button=element('button',undefined,'calendar-day');
      button.type='button';
      button.setAttribute('aria-pressed',String(calendarDay===day.date));
      if(day.date===date)button.setAttribute('aria-current','date');
      button.append(element('span',day.label),element('strong',day.date.slice(5).replace('-','/')),
        element('small',day.rows.length+' 场'));
      button.onclick=()=>{
        calendarDay=calendarDay===day.date?'':day.date;
        renderCalendar(visible,selected);
        rail.children[days.indexOf(day)].focus();
      };
      rail.append(button);
    }
    el('calendar-all-days').hidden=!calendarDay;
    el('calendar-agenda-title').textContent=calendarDay?calendarDay.slice(5)+' 场次':'整周场次';
    agenda.replaceChildren();
    const included=days.filter(day=>!calendarDay||day.date===calendarDay);
    const pending=unscheduled.filter(({entry})=>!calendarDay||(entry.dates?.start<=calendarDay&&entry.dates?.end>=calendarDay));
    if(!included.some(day=>day.rows.length)&&!pending.length){
      agenda.append(element('p',eligible.checked?'当前范围没有已确认符合条件的比赛。取消资格筛选可查看缺项。':'这个范围暂未读到场次。试试显示整周或扫描这一周。','hint calendar-empty'));
      return;
    }
    const table=element('table',undefined,'calendar-table');
    table.setAttribute('aria-label','耐力赛场次与参赛条件');
    table.setAttribute('role','table');
    const headings=table.createTHead().insertRow();
    headings.parentElement.setAttribute('role','rowgroup');
    headings.setAttribute('role','row');
    for(const label of calendarHeadings){
      const th=element('th',label);th.scope='col';th.setAttribute('role','columnheader');headings.append(th);
    }
    function rows(label,items){
      const body=table.createTBody();
      body.setAttribute('role','rowgroup');
      const heading=body.insertRow();heading.className='calendar-day-row';
      heading.setAttribute('role','row');
      const th=element('th',label);th.colSpan=calendarHeadings.length;th.scope='rowgroup';heading.append(th);
      for(const {entry,slot} of items){
        const row=body.insertRow();row.className='calendar-event-row';
        row.setAttribute('role','row');
        const cell=(caption)=>{
          const td=row.insertCell();td.setAttribute('role','cell');
          if(caption)td.dataset.label=caption;
          return td;
        };
        const pick=element('button',slot?.localStart.slice(11,16)||'选赛事','calendar-slot');pick.type='button';
        const active=input('series').value===entry.name&&input('localStart').value===slotKey(slot);
        row.dataset.selected=String(active);
        pick.setAttribute('aria-pressed',String(active));
        pick.setAttribute('aria-controls','selected-race');
        pick.setAttribute('aria-label',slot?('选择 '+entry.name+' '+slot.startLabel):('查看 '+entry.name));
        pick.onclick=()=>chooseCalendarSlot(entry,slot);
        row.onclick=event=>{if(event.target!==pick)pick.click();};
        cell().append(pick);
        const race=cell();
        race.append(element('strong',entry.name));
        const translated=chineseTrack(entry.track);
        race.append(element('small',translated||entry.track||'赛道待确认'));
        if(translated)race.append(element('small',entry.track));
        if(!slot&&(entry.dateLabel||entry.dates?.start))race.append(element('small',entry.dateLabel||entry.dates.start));
        const qualification=eligibilityText(entry.eligibility);
        const qualificationCell=cell('我的资格');
        qualificationCell.append(element('strong',qualification.label,'calendar-eligibility-'+qualification.status));
        if(qualification.detail&&catalog.eligibilityCheckedAt&&qualification.status!=='eligible')qualificationCell.append(element('small',qualification.detail));
        cell('最低驾照').textContent=minimumLicense(entry);
        cell('车辆组别').textContent=classesText(entry)||'待核对';
        cell('比赛时长').textContent=entry.durationLabel||'待核对';
        const registration=cell('报名窗口');
        if(slot?.registrationOpenUtc&&slot.registrationLabel){
          const when=slot.registrationLabel.slice(0,10)===slot.localStart.slice(0,10)?slot.registrationLabel.slice(11,16):slot.registrationLabel.slice(5,16);
          registration.append(element('strong',when+'–'+slot.localStart.slice(11,16)));
          const now=Date.now();
          const available=now>=Date.parse(slot.registrationOpenUtc)&&now<Date.parse(slot.startUtc);
          registration.append(element('small',now>=Date.parse(slot.startUtc)?'已到开赛时间':slot.registrationKind==='estimated'?'预计 · 以客户端为准':available?'已到公布开放时间':'官方公布'));
        }else registration.append(element('small',slot?'开放时间待确认':'场次时间待确认'));
        const weather=weatherText(slot?.weather||entry.weather), conditions=cell('天气');
        conditions.append(element('span',weather.label,weather.type?'calendar-weather-'+weather.type:undefined));
        if(weather.detail)conditions.append(element('small',weather.detail));
      }
    }
    for(const day of included){
      if(day.rows.length)rows(day.label+' '+day.date.slice(5)+(day.date===date?' · 今天':''),day.rows);
    }
    if(pending.length)rows('场次待公布或待核对',pending);
    agenda.append(table);
  }
  function invalidate(){dirty=true;inspect.disabled=true;el('team-open').disabled=true;progress.hidden=true;result.textContent='资料有修改，请先保存，再打开对应赛事。保存资料不会创建预约。';}
  for(const event of ['input','change']){
    form.addEventListener(event,e=>{
      if(!['calendar-selected-only','endurance-search'].includes(e.target.id))invalidate();
    });
  }
  function showProgress(response){
    progress.replaceChildren();progress.hidden=false;
    const caption=document.createElement('p');
    caption.textContent='iRacing 当前场次 · '+fmt(response.observedAt)+'（多伦多）';
    caption.className='hint';progress.append(caption);
    const eligibility=response.eligibility;
    if(eligibility){
      const section=document.createElement('div');section.className='team-phase';
      const title=document.createElement('strong');
      title.textContent={met:'赛车、赛道和驾照均符合要求',blocked:'当前有参赛条件未满足',unknown:'部分参赛条件待确认'}[eligibility.status];
      const statuses={owned:'已有授权',missing:'缺少授权',met:'达标',unmet:'未达标',unknown:'待确认'};
      section.append(title);
      for(const [label,name,status] of [
        ['赛车',eligibility.car.name,eligibility.car.status],
        ['赛道',eligibility.track.name,eligibility.track.status],
        ['驾照',eligibility.license.requirement,eligibility.license.status],
      ]){
        const row=document.createElement('p');
        row.textContent=[label,name,statuses[status]].filter(Boolean).join(' · ');
        section.append(row);
      }
      if(eligibility.nextStep){
        const hint=document.createElement('p');hint.className='hint';
        hint.textContent=eligibility.nextStep;section.append(hint);
      }
      progress.append(section);
    }
    for(const phase of response.phases){
      const row=document.createElement('div');row.className='team-phase';
      const title=document.createElement('strong');title.textContent=phase.label+' · '+(phase.state==='partial'?'部分已核对':phase.state==='pending'?'待核对':'结果未核实');
      const detail=document.createElement('p');detail.textContent=phase.detail;
      row.append(title,detail);progress.append(row);
    }
  }
  function showValidation(report){
    const box=el('team-validation');box.replaceChildren();
    const context=document.createElement('p');context.textContent=[report.session,report.track,report.type,report.team,report.car,report.method].join(' · ');box.append(context);
    for(const check of report.checks){
      const row=document.createElement('p'),title=document.createElement('strong');
      title.textContent=check.label+'：'+check.result+'。';row.append(title,document.createTextNode(check.detail));box.append(row);
    }
  }
  function options(select,prompt,values,current,format=value=>value.replace(/^(\d{4}-\d\d-\d\d)T/,'$1 ')){
    select.replaceChildren(new Option(prompt,''));
    for(const value of values)select.add(new Option(format(value),value));
    if(current&&!values.includes(current))select.add(new Option(current+'（旧草稿，待重选）',current));
    select.value=current||'';
  }
  function choices(series,slot,car){
    const query=el('endurance-search').value.trim().toLocaleLowerCase();
    const visible=catalog.series.filter(x=>(x.name+' '+(x.track||x.detail||'')+' '+chineseTrack(x.track)).toLocaleLowerCase().includes(query));
    const entry=catalog.series.find(x=>x.name===series);
    const session=raceSlots(entry).find(x=>slotKey(x)===slot||x.localStart===slot);
    input('series').value=series||'';
    input('localStart').value=slotKey(session)||slot||'';
    el('selected-race').hidden=!series;
    el('selected-race-title').textContent=series||'';
    options(input('car'),entry?.cars.length?'暂不选择车辆':'尚无已核实的车辆名单',entry?.cars||[],car,value=>{const group=entry?.classes?.find(x=>x.cars.includes(value));return (group?'['+group.name+'] ':'')+value;});
    const facts=el('race-detail');facts.replaceChildren();
    if(entry){
      const line=(label,value)=>{const p=document.createElement('p'),b=document.createElement('strong');b.textContent=label+'：';p.append(b,document.createTextNode(value));facts.append(p);};
      line('比赛赛道 / 布局',[chineseTrack(entry.track),entry.track].filter(Boolean).join(' · ')||'待官方公布或客户端核对');
      const forecast=session?.weather||entry.weather;
      const weather=weatherText(forecast);
      line('天气 / 赛道条件',[weather.label,weather.detail].filter(Boolean).join(' · '));
      if(forecast?.source){
        const link=element('a','查看官方天气来源');link.href=forecast.source;link.target='_blank';link.rel='noopener noreferrer';facts.append(link);
      }
      if(entry.specialEvent)line('特殊赛事日期',entry.dateLabel);
      const license=entry.licenseRequirement;
      line('参赛驾照',license?[license.minimum,license.maximum].filter(Boolean).join(' 至 '):'待客户端核对');
      const qualification=eligibilityText(entry.eligibility);
      line('我的参赛资格',[qualification.label,qualification.detail].filter(Boolean).join(' · '));
      if(entry.eligibility?.license.current)line('我的驾照',entry.eligibility.license.discipline+' '+entry.eligibility.license.current);
      if(entry.eligibility?.car.owned.length)line('我已授权的参赛车辆',entry.eligibility.car.owned.join('、'));
      if(license?.source){const a=element('a','查看官方驾照来源');a.href=license.source;a.target='_blank';a.rel='noopener noreferrer';facts.append(a);}
      line('Race duration · 比赛时长',entry.durationLabel||'待核对（未读到可靠的比赛时长）');
      if(entry.scheduleWeek)line('时长依据','官方赛程 '+entry.scheduleWeek+' 周次的 Duration 列；不包含练习和排位');
      line('允许的车辆组别',classesText(entry)||entry.carLabel||'待客户端核对');
      line('多组别混跑',entry.multiclass===true?'是，同场有不同组别':entry.multiclass===false?'否，单一组别（可含多款车型）':'待核对，不能仅凭车型数量判断');
      if(entry.classBasis)line('组别依据',entry.classBasis);
      if(entry.unknownCars?.length)line('尚未识别组别的车型',entry.unknownCars.join('、'));
      line('参赛要求',(entry.teamRace===false?'个人或可单人参赛':'车队赛事')+(entry.minDrivers?' · 车手 '+entry.minDrivers+'–'+entry.maxDrivers+' 人':''));
      if(entry.durationSource){const a=document.createElement('a');a.href=entry.durationSource;a.target='_blank';a.rel='noopener noreferrer';a.textContent='查看官方时长来源';facts.append(a);}
    }else facts.textContent='保存的赛事不在这周的赛程资料中。请从周历重新选场次。';
    el('weekend-info').textContent=catalog.monday+'（周一）至 '+catalog.sunday+'（周日）'+' · '+catalog.series.length+' 个赛事/系列（搜索匹配 '+visible.length+' 个）。'+catalog.note+(catalog.observedAt?' 最近更新 '+fmt(catalog.observedAt):'')+(catalog.warnings||[]).join('；');
    const coverage=el('catalog-coverage');coverage.replaceChildren();
    const add=text=>{const p=document.createElement('p');p.textContent=text;coverage.append(p);};
    const special=catalog.specialCalendar;
    if(catalog.seasonCoverage)add('当前赛季 PDF 周末范围：'+catalog.seasonCoverage.firstWeekend+' 至 '+catalog.seasonCoverage.lastWeekend+'。');
    if(special){
      add('官方特殊赛事日历：'+special.year+' 年，共读取 '+special.total+' 项；所选周匹配 '+special.matched+' 项耐力/车队赛事。更新于 '+fmt(special.observedAt)+'（多伦多）。');
      if(String(special.year)!==catalog.saturday.slice(0,4))add('所选年份不在当前特殊赛事日历中，请等待官方发布对应年份。');
      if(special.undated.length)add('日期尚未确定，未归入任何一周：'+special.undated.map(x=>x.name+'（'+x.dateLabel+'）').join('；'));
      if(special.other.length)add('同周其他官方特殊赛事（尚未归类为耐力赛）：'+special.other.map(x=>x.name+'（'+x.dateLabel+'）').join('；'));
    }
    if(catalog.specialError)add(catalog.specialError);
    add('扫描范围：已发布的官方赛季赛程、周报和特殊赛事日历。尚未公布的场次不会自动补时间；未包含私人房间和联赛。');
    const link=document.createElement('a');link.href='https://www.iracing.com/special-events/';link.target='_blank';link.rel='noopener noreferrer';link.textContent='查看官方特殊赛事日历';coverage.append(link);
    el('calendar-feedback').hidden=true;
    renderCalendar(visible,entry);
    showSlot();
  }
  function showSlot(){
    const box=el('race-time-summary'),entry=catalog?.series.find(x=>x.name===input('series').value);
    const slot=raceSlots(entry).find(x=>slotKey(x)===input('localStart').value);
    const target=el('team-booking-target');
    const now=Date.now();
    const canSchedule=entry?.teamRace===true&&Date.parse(slot?.startUtc)>now;
    target.textContent=slot?entry.name+' · '+slot.startLabel+' 开赛（多伦多）':'先在周历选择要预约的场次。';
    if(slot&&!canSchedule)target.append(element('small',entry.teamRace===false?' · 此场次可在 iRacing 手动报名。':!slot.startUtc?' · 需先核对开赛时间。':Date.parse(slot.startUtc)<=now?' · 该场次已开赛。':' · 需先核对车队赛事资格。'));
    el('team-schedule').disabled=!canSchedule;
    const earlier=entry?.slotDetails?.find(x=>Date.parse(x.startUtc)<Date.parse(slot?.startUtc)&&
      now>=Date.parse(x.registrationOpenUtc)&&now<Date.parse(x.startUtc));
    if(earlier)target.append(element('small',' · 较早的 '+earlier.startLabel+' 场已到预计报名时段。要约这场，请在周历改选。'));
    box.replaceChildren();
    if(!slot){box.textContent=input('localStart').value?'保存的场次不在当前赛程中，请从周历重新选择。':'场次和报名时间待官方公布。';return;}
    for(const text of [(slot.registrationKind==='confirmed'?'报名开放：':'预计报名开放：')+(slot.registrationLabel||'待确认'),'场次开赛：'+slot.startLabel,'时区：多伦多 America/Toronto；EDT 夏令时 / EST 冬令时']){const p=document.createElement('p');p.textContent=text;box.append(p);}
  }
  el('calendar-return').onclick=()=>{
    const pick=el('calendar-agenda').querySelector('.calendar-slot[aria-pressed=true]');
    (pick||el('endurance-search')).focus();
  };
  el('endurance-search').oninput=()=>choices(input('series').value,input('localStart').value,input('car').value);
  el('calendar-selected-only').onchange=()=>choices(input('series').value,input('localStart').value,input('car').value);
  el('calendar-eligible-only').onchange=()=>choices(input('series').value,input('localStart').value,input('car').value);
  el('calendar-read-eligibility').onclick=async()=>{
    const control=el('calendar-read-eligibility');
    const message=el('calendar-eligibility-status');
    fields.disabled=true;reload.disabled=true;
    message.textContent='正在读取 iRacing 的驾照、赛车和赛道授权…';
    try{
      catalog=await api('/api/team-options/eligibility',{weekend:input('weekend').value});
      choices(input('series').value,input('localStart').value,input('car').value);
    }catch(e){message.textContent=e.message;}
    finally{fields.disabled=false;reload.disabled=false;control.focus();}
  };
  el('calendar-all-days').onclick=()=>{
    calendarDay='';
    choices(input('series').value,input('localStart').value,input('car').value);
    el('calendar-days').querySelector('button')?.focus();
  };
  async function changeWeekend(){
    el('scan-feedback').textContent='日期已切换；点击“扫描这一周”更新官方资料。';
    fields.disabled=true;invalidate();
    try{catalog=(await api('/api/team-options?weekend='+encodeURIComponent(input('weekend').value))).catalog;calendarDay='';input('weekend').value=catalog.monday;choices('','','');}
    catch(e){result.textContent=e.message;}finally{fields.disabled=false;}
  }
  input('weekend').onchange=changeWeekend;
  el('weekend-today').onclick=()=>{input('weekend').value=today();void changeWeekend();};
  for(const [id,days] of [['weekend-prev',-7],['weekend-next',7]])el(id).onclick=()=>{const date=new Date((input('weekend').value||catalog.monday)+'T12:00Z');date.setUTCDate(date.getUTCDate()+days);input('weekend').value=date.toISOString().slice(0,10);void changeWeekend();};
  function renderMembers(){
    const valid=members&&members.teamId===input('teamId').value&&members.teamName===input('teamName').value;
    const rows=valid?members.members:[],picked=new Set(input('rosterEntries').value.split(/[\n,，]+/).map(s=>s.trim()).filter(Boolean));
    const box=el('member-list');box.replaceChildren();memberSelection=!!valid;
    for(const m of rows){
      const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.value=m.id;check.checked=picked.has(m.id);check.disabled=input('kind').value==='join_team';
      label.className='member-option';label.append(check,document.createTextNode(m.name+' · '+m.id));box.append(label);
      check.onchange=()=>{const chosen=[...box.querySelectorAll('input:checked')].map(c=>c.value);input('rosterEntries').value=chosen.join('\n');memberSelection=true;invalidate();};
    }
    const own=el('own-driver-choice');options(own,'选择本机登录的车手',rows.map(m=>m.id),input('ownDriverEntry').value,id=>{const m=rows.find(m=>m.id===id);return m?m.name+' · '+id:id;});
    own.onchange=()=>{input('ownDriverEntry').value=own.value;memberSelection=!!valid;invalidate();};
    const unknown=[...picked].filter(id=>!rows.some(m=>m.id===id));
    el('members-info').textContent=valid?members.teamName+' · '+rows.length+' 位成员 · '+fmt(members.observedAt)+' 读取。'+(unknown.length?'旧名单含未匹配成员，请重新勾选或检查手动名单。':'只勾选本场参赛车手。'):'尚未读取所选车队成员。请点“扫描所选车队成员”。';
  }
  async function loadMembers(){
    const id=input('teamId').value;members=null;renderMembers();
    if(!/^[1-9]\d*$/.test(id))return;
    try{const value=await api('/api/team-options/members?teamId='+encodeURIComponent(id));if(input('teamId').value===id){members=value;renderMembers();}}catch(e){el('members-info').textContent=e.message;}
  }
  function teamChoices(){
    const selector=el('team-choice'),teams=directory?.teams||[];
    selector.replaceChildren(new Option('手动输入车队','manual'));
    teams.forEach((t,i)=>selector.add(new Option(t.name+(t.id?' · '+t.id:' · ID 待核对'),String(i))));
    const match=teams.findIndex(t=>t.name===input('teamName').value&&(!input('teamId').value||input('teamId').value===t.id));
    selector.value=match<0?'manual':String(match);
    if(match>=0&&!input('teamId').value)input('teamId').value=teams[match].id;
    el('directory-info').textContent=directory?'上次读取：'+fmt(directory.observedAt)+'（多伦多） · '+teams.length+' 支车队':'尚未读取我的车队。';
  }
  el('team-choice').onchange=()=>{
    const t=directory?.teams[Number(el('team-choice').value)];
    input('teamName').value=t?.name||'';input('teamId').value=t?.id||'';
    input('rosterEntries').value='';input('ownDriverEntry').value='';void loadMembers();
    if(!t)input('teamName').focus();
  };
  for(const field of ['teamId','teamName'])input(field).oninput=()=>{el('team-choice').value='manual';members=null;renderMembers();};
  for(const field of ['rosterEntries','ownDriverEntry'])input(field).oninput=()=>{memberSelection=false;};
  function scan(button,fn){
    button.onclick=async()=>{
      const caption=button.textContent;button.textContent='正在扫描…';
      if(button.id==='weekend-scan'){el('scan-feedback').className='notice';el('scan-feedback').textContent='正在扫描官方赛程，请稍候。完成后这里会显示结果。';}
      fields.disabled=true;reload.disabled=true;inspect.disabled=true;el('team-open').disabled=true;progress.hidden=true;result.textContent='正在读取，请稍候…';
      try{await fn();dirty=true;result.textContent='读取完成；点“保存名单和赛事资料”才会保存选择。';if(button.id==='weekend-scan'){
        const r=catalog.scanReport,label=r?.status==='success'?'扫描成功':r?.status==='partial'?'扫描部分完成':'扫描失败，显示缓存资料';
        const text=label+'：'+catalog.monday+' 至 '+catalog.sunday+'，找到 '+catalog.series.length+' 个赛事/系列。'+(r?.completedAt?'完成于 '+fmt(r.completedAt)+'（多伦多）。':'')+(r?.failures?.length?' '+r.failures.join('；'):'')+' 请选择赛事查看详情；扫描不会报名。';
        el('scan-feedback').textContent=text;el('scan-feedback').className=r?.status==='success'?'task-feedback success':'notice';result.textContent=text;message(text,r?.status==='success');
      }}
      catch(e){result.textContent=e.message;if(button.id==='weekend-scan'){el('scan-feedback').textContent='扫描失败：'+e.message;el('scan-feedback').className='notice';}}
      finally{button.textContent=caption;fields.disabled=false;reload.disabled=false;inspect.disabled=dirty||revision===null;}
    };
  }
  scan(el('weekend-scan'),async()=>{
    catalog=await api('/api/team-options/weekend',{weekend:input('weekend').value});input('weekend').value=catalog.monday;choices(input('series').value,input('localStart').value,input('car').value);
  });
  scan(el('teams-scan'),async()=>{directory=await api('/api/team-options/teams',{});teamChoices();});
  scan(el('members-scan'),async()=>{members=await api('/api/team-options/members',{teamId:input('teamId').value,teamName:input('teamName').value});renderMembers();});

  function showMode(){
    const kind=input('kind').value;
    document.getElementById('team-register-fields').hidden=kind==='join_team';
    el('team-auto-join-option').hidden=kind==='join_team';
    el('team-join-fields').hidden=kind==='team_registration'&&!el('team-auto-join').checked;
    if(catalog)renderMembers();
  }

  function display(plan){
    revision=plan.revision;
    dirty=false;progress.hidden=true;inspect.disabled=false;el('team-open').disabled=!plan.series||revision===0;
    input('weekend').value=catalog.monday;
    choices(plan.series,plan.startUtc||plan.localStart,plan.car);
    input('kind').value=plan.kind==='join_team'?'join_team':'team_registration';
    el('team-auto-join').checked=revision>0&&plan.kind==='team_then_join';
    for(const name of ['teamName','teamId','declaration']){
      input(name).value=plan[name];
    }
    input('ownDriverEntry').value=plan.ownDriverEntry??plan.ownDriverId;
    input('rosterEntries').value=(plan.rosterEntries??plan.roster).join('\n');
    teamChoices();
    showMode();
    const past=plan.startUtc&&Date.parse(plan.startUtc)<=Date.now();
    el('team-next-step').textContent=plan.series?'已保存选择 · '+plan.series+' · '+(plan.localStart||'未选场次')+'（多伦多）。'+(past?'目标场次已过期，请重新选择。':'点「预约自动报名」可安排执行，也可打开客户端核对。'):'先选择比赛周、系列、场次和车队。';
    result.textContent=revision===0?'尚未保存准备单。':plan.missing.length
      ?'已保存草稿。待补全 '+plan.missing.join('、')+'。'
      :'准备单已保存，可点「预约自动报名」。';
  }

  let displayedAppointments='';
  window.renderTeamAppointments=jobs=>{
    const box=el('team-appointments');
    const signature=JSON.stringify([jobs,Math.floor(Date.now()/10000)]);
    if(signature===displayedAppointments)return;
    displayedAppointments=signature;
    box.replaceChildren();
    if(!jobs.length)box.append(element('p','还没有车队预约。','hint'));
    for(const job of jobs){
      const item=element('div',undefined,'team-phase');
      item.append(element('strong',fmt(job.startUtc)+' · '+job.series+' · '+(statuses[job.status]||job.status)));
      item.append(element('p',job.teamName+' · '+job.car));
      const checkTime=job.registrationKind==='confirmed'?job.registrationOpenUtc:new Date(Date.parse(job.startUtc)-3600000).toISOString();
      item.append(element('p',(job.registrationKind==='confirmed'?'官方报名开放 · ':'开始检查报名窗口 · ')+fmt(checkTime)+'（多伦多）','hint'));
      const progress={waiting:'待执行',unconfirmed:'结果待核实',confirmed:'已确认',not_requested:'未选择'};
      const withdrawal=job.teamWithdrawal;
      const teamState=job.status==='withdrawn'?'已退出':progress[job.teamProgress.team];
      const driverState=withdrawal?.driverWithdrawn?'已退出':progress[job.teamProgress.driver];
      item.append(element('p','整队报名 '+teamState+' · 本人加入 '+driverState));
      const declared=job.teamProgress.team==='confirmed'&&job.teamSteps?.roster==='confirmed';
      const names=[...new Set([...(job.driverNames||[]),job.ownDriverName].filter(Boolean))];
      const roster=element('ul',undefined,'team-booking-roster hint');
      roster.setAttribute('aria-label','队员报名明细');
      for(const name of names){
        const marks=[];
        if(job.driverNames?.includes(name))marks.push(declared?'已随整队申报':'计划申报');
        if(name===job.ownDriverName)marks.push('本人加入 '+driverState);
        else if(declared)marks.push('个人加入待核实');
        roster.append(element('li',name+' · '+marks.join(' · ')));
      }
      if(names.length){item.append(element('strong','队员报名明细'));item.append(roster);}
      const canShowSteps=job.teamSteps||['waiting','blocked','submitting','uncertain'].includes(job.status);
      if(canShowSteps&&job.bookingMode!=='join_team'&&job.status!=='reviewed'){
        const steps=element('ol',undefined,'hint');
        const labels={car:'选车',team:'选择车队',roster:'申报车手',verify:'Verify Team',submit:'整队报名'};
        const states={checking:'正在核对',confirmed:'已确认',blocked:'未通过核对',unconfirmed:'结果待核实'};
        steps.setAttribute('aria-label','车队报名步骤');
        for(const [key,label] of Object.entries(labels)){
          const step=key==='submit'&&job.teamProgress.team==='unconfirmed'&&job.status==='uncertain'?'unconfirmed':job.teamSteps?.[key];
          steps.append(element('li',label+' · '+(states[step]||(key==='submit'&&job.teamProgress.team==='confirmed'?'已确认':'待执行'))));
        }
        item.append(steps);
      }
      item.append(element('p',job.note));
      if(withdrawal&&job.status!=='withdrawn')item.append(element('p',withdrawal.message,'hint'));
      const verifyWithdrawal=['personal_submitting','personal_unconfirmed','team_submitting','team_unconfirmed'].includes(withdrawal?.state);
      const inWithdrawWindow=Date.now()<Date.parse(job.startUtc)-120000;
      if(job.teamProgress.team==='confirmed'&&job.status!=='withdrawn'&&(inWithdrawWindow||verifyWithdrawal)){
        const control=element('button',verifyWithdrawal?'核对整队退出结果':'退出整队报名','ghost');
        control.type='button';
        control.onclick=()=>{
          if(!verifyWithdrawal&&!window.confirm('退出 '+fmt(job.startUtc)+' 场 · '+job.teamName+'？若已登记本人，也会先退出本人的车手登记。'))return;
          void act(async()=>{
            const result=await api('/api/team-appointments/withdraw',{id:job.id,confirmed:true});
            if(result.status!=='withdrawn')throw Error(result.teamWithdrawal?.message||'退出结果待核对，请查看 iRacing。');
          },'整队已退出。');
        };
        item.append(control);
        if(!verifyWithdrawal)item.append(element('p','可申请退出至赛前两分钟，团队管理员权限及队员状态以 iRacing 为准。','hint'));
      }
      if(!withdrawal&&['waiting','blocked','uncertain'].includes(job.status)){
        const confirm=job.status==='uncertain';
        const control=element('button',confirm?'我已核实，结束跟踪':'取消预约','ghost');
        control.type='button';
        control.onclick=()=>act(()=>api(confirm?'/api/resolve':'/api/cancel',{id:job.id,confirmed:confirm}),confirm?'已结束跟踪。':'已取消剩余预约步骤。');
        item.append(control);
      }
      box.append(item);
    }
  };

  async function read(){
    reload.disabled=true;fields.disabled=true;inspect.disabled=true;progress.hidden=true;
    try{const [plan,validation]=await Promise.all([api('/api/team-plan'),api('/api/team-validation')]);const date=plan.series&&(plan.weekend||plan.localStart?.slice(0,10));const opts=await api('/api/team-options'+(date?'?weekend='+encodeURIComponent(date):''));catalog=opts.catalog;directory=opts.directory;display(plan);await loadMembers();showValidation(validation);}
    catch(error){result.textContent=error.message;}
    finally{fields.disabled=revision===null;reload.disabled=false;}
  }

  sheet.addEventListener('toggle',()=>{if(sheet.open&&revision===null&&!reload.disabled)void read();});
  input('kind').addEventListener('change',showMode);
  el('team-auto-join').addEventListener('change',showMode);
  reload.addEventListener('click',read);
  el('team-open').onclick=async()=>{
    if(dirty||!revision)return;
    fields.disabled=true;reload.disabled=true;inspect.disabled=true;el('team-open').disabled=true;
    try{const response=await api('/api/team-plan/open',{revision});result.textContent=response.message;}
    catch(e){result.textContent=e.message;}finally{fields.disabled=false;reload.disabled=false;inspect.disabled=dirty;el('team-open').disabled=dirty;}
  };
  inspect.addEventListener('click',async()=>{
    if(dirty||revision===null)return;
    const checkedRevision=revision;
    inspect.disabled=true;fields.disabled=true;reload.disabled=true;progress.hidden=true;
    try{
      const response=await api('/api/team-plan/check',{revision});
      if(response.revision!==checkedRevision)throw Error('准备单已变化，请重新读取后检查');
      result.textContent=response.notes.join(' ');
      showProgress(response);
    }catch(error){result.textContent=error.message;}
    finally{inspect.disabled=dirty;fields.disabled=false;reload.disabled=false;}
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(fields.disabled)return;
    const data=Object.fromEntries(new FormData(form));
    if(data.kind==='team_registration'&&el('team-auto-join').checked)data.kind='team_then_join';
    data.rosterEntries=data.rosterEntries.split(/[\n,，]+/).map(s=>s.trim()).filter(Boolean)
      .flatMap(line=>/^\d+(?:\s+\d+)+$/.test(line)?line.split(/\s+/):[line]);
    const session=catalog.series.find(x=>x.name===data.series)?.slotDetails?.find(x=>x.startUtc===data.localStart);
    if(session){data.startUtc=session.startUtc;data.localStart=session.localStart;}
    data.revision=revision;
    data.memberSelection=memberSelection;
    fields.disabled=true;reload.disabled=true;inspect.disabled=true;progress.hidden=true;
    try{
      const plan=await api('/api/team-plan',data);
      display(plan);
      if(event.submitter===el('team-schedule')){
        const job=await api('/api/team-appointments',{revision:plan.revision,confirmed:true});
        result.textContent='车队预约 · '+job.startLabel+' 开赛（多伦多） · '+(statuses[job.status]||job.status)+' · '+job.note;
        await load();
      }
    }
    catch(error){result.textContent=error.message;}
    finally{fields.disabled=false;reload.disabled=false;inspect.disabled=dirty;}
  });
})();
