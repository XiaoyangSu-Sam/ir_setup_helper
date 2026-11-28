import assert from 'node:assert/strict';
import {test} from 'node:test';
import {assessCalendarEligibility,readLicenses,readLicensedContent,readFullLicensedContent,withCalendarEligibility} from '../../registration/calendar-eligibility.mjs';

const prefix='https://members-ng.iracing.com/web/racing/';
function snapshot(path){
  const nodes=[];
  return {raw:{ok:true,url:prefix+path,nodes},add(type,name='',parent=-1,props={}){
    const index=nodes.length;
    nodes.push({index,parent,type:'ControlType.'+type,name,...props});return index;
  }};
}

test('reads category-specific license and safety rating from the active profile',()=>{
  const {raw,add}=snapshot('profile');
  add('Text','OVAL RACING',1);add('Text','Driver',1);add('Text','Rookie',1);add('Text','2.50',1);
  add('Text','SPORTS CAR RACING',1);add('Text','Driver',1);add('Text','Class B',1);add('Text','3.00',1);
  add('Text','FORMULA RACING',1);add('Text','Driver',1);add('Text','Class C',1);add('Text','2.20',1);
  assert.deepEqual(readLicenses(raw),{'Oval':'Rookie 2.50','Sports Car':'Class B 3.00',Formula:'Class C 2.20'});
  assert.throws(()=>readLicenses({...raw,url:prefix+'official'}));
});

test('reads named licensed rows, with negative proof only for an unfiltered complete table',()=>{
  const {raw,add}=snapshot('licensed-content/cars');
  const clear=add('Button','Clear Filters',-1,{id:'content-clear-button',enabled:false});
  const table=add('Table');
  const header=add('DataItem','',table);
  add('DataItem','',header);add('DataItem','Car Name',header);
  const row=add('DataItem','',table);
  add('Button','',add('Group','',add('DataItem','',row)),{id:'favorite_cars-169'});
  add('DataItem','A GT3',row);
  assert.deepEqual(readLicensedContent(raw,'cars'),{names:['A GT3'],complete:true});
  raw.nodes[clear].enabled=true;
  assert.deepEqual(readLicensedContent(raw,'cars'),{names:['A GT3'],complete:false});
});

test('combines virtual rows by their stable positions and rejects changed sorting',async()=>{
  function view(rows){
    const {raw,add}=snapshot('licensed-content/cars');
    add('Button','Clear Filters',-1,{id:'content-clear-button',enabled:false});
    const table=add('Table');const head=add('DataItem','',table);
    add('DataItem','',head);add('DataItem','Car Name',head);
    for(const [i,name] of rows.entries()){
      const row=add('DataItem','',table);
      if(name){add('Button','',add('Group','',add('DataItem','',row)),{id:'favorite_cars-'+i});add('DataItem',name,row);}
      else add('DataItem','',row);
    }
    return raw;
  }
  const first=view(['Car A','Car B','']);
  const completed=await readFullLicensedContent(async(op,args)=>{
    assert.equal(op,'licensed_row');assert.deepEqual(args,{tab:'cars',row:2});
    return view(['','Car B','Car C']);
  },first,'cars');
  assert.deepEqual(completed,{names:['Car A','Car B','Car C'],complete:true});
  assert.equal((await readFullLicensedContent(async()=>view(['','Car D','Car C']),first,'cars')).complete,false);
});

const event={classes:[{name:'GT3'},{name:'LMP3'}],cars:['A GT3','B LMP3'],track:'Spa-Francorchamps - Endurance',
  licenseRequirement:{minimum:'Class D 4.0',maximum:'Pro/WC 4.0'}};
const profile={licenses:{'Sports Car':'Class C 2.10'},cars:{names:['A GT3'],complete:true},tracks:{names:['Spa Francorchamps'],complete:true}};
test('one licensed option qualifies in multiclass; lower license SR applies only to the same license class',()=>{
  const report=assessCalendarEligibility(event,profile);
  assert.equal(report.status,'eligible');
  assert.deepEqual(report.car.owned,['A GT3']);
  assert.equal(assessCalendarEligibility(event,{...profile,licenses:{'Sports Car':'Class D 3.99'}}).license.status,'missing');
  assert.equal(assessCalendarEligibility(event,{...profile,licenses:{'Sports Car':'Class D 4.00'}}).license.status,'met');
});

test('reports multiple missing requirements without converting stale or ambiguous data to missing',()=>{
  const limited={...profile,licenses:{'Sports Car':'Class D 3.00'},cars:{names:[],complete:true},tracks:{names:[],complete:true}};
  const report=assessCalendarEligibility(event,limited);
  assert.equal(report.status,'blocked');
  assert.ok([report.license,report.car,report.track].every(r=>r.status==='missing'));
  assert.equal(assessCalendarEligibility({...event,track:'Spa-Francorchamps - 2010'},profile).track.status,'unknown');
  assert.equal(assessCalendarEligibility(event,{...profile,cars:{names:[],complete:false}}).status,'unknown');
  const now=Date.parse('2026-11-28T02:00Z');
  const calendar=withCalendarEligibility({series:[event]},{...profile,observedAt:'2026-11-27T23:59Z'},now);
  assert.equal(calendar.eligibilityCheckedAt,null);
  assert.equal(calendar.series[0].eligibility.status,'unknown');
});
