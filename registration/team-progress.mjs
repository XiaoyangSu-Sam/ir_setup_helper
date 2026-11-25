// Read-only observations. These are deliberately not registration receipts.
const clean=value=>String(value??'').replace(/\ufffc/g,'').replace(/\s+/g,' ').trim();
const seriesName=value=>clean(value).replace(/Nürburgring/g,'Nurburgring');

const key = value => clean(value).normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();
const purchase = /(?:you need to )?purchase the content licenses? for (.+)/i;

function descendants(root, nodes) {
  const parents = new Set([root.index]);
  return nodes.filter(node => {
    if (!parents.has(node.parent)) return false;
    parents.add(node.index);
    return true;
  });
}

function eligibilityRows(panel, nodes) {
  const rows = [];
  let fragments = [];
  for (const node of descendants(panel, nodes)) {
    if (node.type === 'ControlType.Separator') {
      rows.push(clean(fragments.join(' ')));
      fragments = [];
    } else if (node.type === 'ControlType.Text' && node.name) {
      fragments.push(node.name);
    }
  }
  rows.push(clean(fragments.join(' ')));
  return rows;
}

function ownership(owned, missing) {
  return owned === missing ? 'unknown' : owned ? 'owned' : 'missing';
}

function contentCard(type, nodes, byIndex) {
  const favorite = nodes.find(node => node.id?.startsWith('favorite_' + type + '-'));
  // The bridge exposes the title beside the menu and its nested favorite button.
  const menu = byIndex.get(byIndex.get(favorite?.parent)?.parent);
  return byIndex.get(menu?.parent);
}

function inspectEligibility(plan, nodes, url, matchingSeries) {
  const car = {name: plan.car || '', status: 'unknown'};
  const track = {name: '', status: 'unknown'};
  const license = {requirement: '', status: 'unknown'};
  const result = {status: 'unknown', car, track, license, nextStep: ''};
  if (!matchingSeries || !/^\/web\/racing\/official\/series-list\/\d+\/go-racing\/?$/.test(url.pathname)) {
    result.nextStep = '在 iRacing 打开准备单对应系列的 Go Racing 页面，再检查。';
    return result;
  }

  const text = nodes.filter(node => node.type === 'ControlType.Text');
  const headline = text.find(node => /^Next Race @ /i.test(clean(node.name)));
  track.name = clean(headline?.name).replace(/^Next Race @ /i, '');
  const byIndex = new Map(nodes.map(node => [node.index, node]));
  const carCard = contentCard('cars', nodes, byIndex);
  const selectedCar = carCard && text.find(node => node.parent === carCard.index);
  if (!car.name) car.name = clean(selectedCar?.name);
  const sameCar = Boolean(car.name && key(selectedCar?.name) === key(car.name));
  const panel = nodes.find(node => clean(node.name) === 'Eligibility' && node.id?.startsWith('accordion-panel-'));
  const rows = panel ? eligibilityRows(panel, nodes) : [];
  const needs = rows.map(row => row.match(purchase)?.[1]).filter(Boolean);
  const summary = headline && text.find(node => node.index > headline.index && node.parent === headline.parent);
  const bannerNeeds = clean(summary?.name).match(purchase)?.[1];
  if (bannerNeeds) needs.push(bannerNeeds);

  const trackCard = contentCard('tracks', nodes, byIndex);
  const venue = trackCard && text.find(node => node.parent === trackCard.index);
  const trackNames = new Set(track.name ? [key(track.name)] : []);
  const venueName = key(venue?.name);
  if (venueName && key(track.name).startsWith(venueName + ' ')) trackNames.add(venueName);
  const missingNames = new Set(needs.flatMap(value => [
    key(value).replace(/[.。]$/, ''),
    ...key(value).replace(/[.。]$/, '').split(/,\s*(?:and\s+)?|\s+and\s+/),
  ]));
  const ownedNames = new Set(rows.map(row => key(row.match(/^You licensed (.+)$/i)?.[1]).replace(/[.。]$/, '')));
  if (sameCar) {
    const confirmedContent = /^You are eligible to race in this series!$/i.test(clean(summary?.name)) &&
      rows.some(row => /^You purchased the content license for (?:[1-9]\d*|a) cars? competing in this event\.?$/i.test(row));
    car.status = ownership(ownedNames.has(key(car.name)) || confirmedContent,
      missingNames.has(key(car.name)) || missingNames.has('a car in this event'));
  }
  if (track.name) {
    track.status = ownership([...trackNames].some(name => ownedNames.has(name)),
      [...trackNames].some(name => missingNames.has(name)) || missingNames.has('the track') || missingNames.has('this track'));
  }

  const minimum = rows.map(row => row.match(/^Your license is (.+?) or above(?:\.|$)/i)).find(Boolean);
  const licenseBlocked = rows.map(row => row.match(/^Your license is below\s+([^.!]+(?:\.\d+)?)/i)).find(Boolean);
  const raceBlocked = rows.some(row => /^(?:Ineligible|Not eligible) for race session\b|^You are not eligible (?:to compete|for (?:this|the) race)/i.test(row));
  license.requirement = minimum?.[1] || licenseBlocked?.[1] || '';
  license.status = licenseBlocked ? 'unmet' : minimum ? 'met' : 'unknown';
  if (car.status === 'missing' || track.status === 'missing' || license.status === 'unmet' || raceBlocked) {
    result.status = 'blocked';
  } else if (car.status === 'owned' && track.status === 'owned' && license.status === 'met') {
    result.status = 'met';
  }
  if (!sameCar && car.name) {
    result.nextStep = '在 iRacing 的 Selected Car 切换到准备单车型后重新检查。';
  } else if (!car.name) {
    result.nextStep = '在 iRacing 的 Selected Car 选择本场使用的车型后重新检查。';
  } else if (!rows.some(Boolean)) {
    result.nextStep = '展开 iRacing 页面里的 Eligibility 后重新检查。';
  } else if (result.status === 'unknown') {
    result.nextStep = '请在 iRacing 的 Eligibility 栏查看尚未确认的项目。';
  } else if (raceBlocked) {
    result.nextStep = 'iRacing 当前显示该场次不可参赛。请查看 Eligibility 栏的原因。';
  }
  return result;
}

export function inspectTeamProgress(plan,raw,now=Date.now()){
  const observed=Date.parse(raw?.observedAt);
  if(!raw?.ok||!Array.isArray(raw.nodes)||!Number.isFinite(observed)||Math.abs(now-observed)>15000)
    throw Error('请重新读取客户端窗口');
  let url;
  try{url=new URL(raw.url);}catch{throw Error('请打开 iRacing 官方客户端');}
  if(url.origin!=='https://members-ng.iracing.com')throw Error('请打开 iRacing 官方客户端');
  const nodes=raw.nodes.filter(n=>n.type!=='ControlType.Image');
  const labels=new Set(nodes.map(n=>clean(n.name)).filter(Boolean));
  const has=label=>labels.has(label);
  const actions=new Set(nodes.filter(n=>['ControlType.Button','ControlType.Hyperlink'].includes(n.type)&&n.enabled&&n.invoke)
    .map(n=>clean(n.text)||clean(n.name)));
  const matchingSeries=!!plan.series&&[...labels].some(x=>seriesName(x)===seriesName(plan.series));
  const teamVisible=!!plan.teamName&&has(plan.teamName);
  const carVisible=!!plan.car&&has(plan.car);
  const wizard=has('Team Registration');
  const stage=!matchingSeries?'different_event':!wizard?'event_page':actions.has('Verify Team')?'team_selection':'team_window';
  const notes=matchingSeries?['当前窗口出现目标赛事名称。']:
    ['当前窗口未识别到准备单中的赛事。待该赛开放后，打开目标场次的队伍报名窗口，再读取。'];
  if(matchingSeries){
    const found=['Verify Team','Add a Driver','Register','Register Team','Register as Driver'].filter(x=>actions.has(x));
    notes.push(found.length?'可用按钮：'+found.join('、')+'。':'当前窗口尚未识别到该报名方式的按钮。');
    if(plan.teamName)notes.push(teamVisible?'页面出现准备单中的队名。':'页面尚未显示准备单中的队名。');
    if(plan.car)notes.push(carVisible?'页面出现准备单中的车辆。':'页面尚未显示准备单中的车辆。');
  }
  if(has('Registered'))notes.push('客户端显示已有报名，但尚未关联到准备单的场次和车队，不能据此确认本次任务成功。');
  if(has('Join a Registered Team'))notes.push('已打开加入车队区域；出现队名不代表你已经以车手身份加入。');
  notes.push('具体开赛时间、Team ID 和车手名单仍需在报名时核对。');
  const phases=[{key:'target',label:'核对场次、车辆和车队',state:matchingSeries?'partial':'pending',detail:matchingSeries?'已识别系列名称；场次身份尚未核实。':'请在电脑打开准备单对应的官方场次。'}];
  if(plan.kind!=='join_team')phases.push({key:'team',label:'替整队报名',state:'unverified',detail:'需要该场次的车队报名凭据；仅显示队名或 Register 按钮不算完成。'});
  if(plan.kind!=='team_registration')phases.push({key:'driver',label:'以车手身份加入',state:'unverified',detail:'整队报名之后，还需单独加入，并核对本人的报名状态。'});
  return {observedAt:raw.observedAt,revision:plan.revision??null,stage,matchingSeries,teamVisible,carVisible,
    eligibility:inspectEligibility(plan,nodes,url,matchingSeries),
    registrationConfirmed:false,phases,notes,automaticSubmissionAvailable:false};
}
