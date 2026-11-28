export function currentTeamClient(race, job, {wrongSession=false, wrongSeries=false, duplicateTeam=false, extraDriver=false, noReceipt=false}={}){
  const actions=[];
  let page='race', menu='', car='', team='', verified=false, registered=false, joined=false;
  let roster=[job.ownDriverName].filter(Boolean);
  function snapshot(){
    if(page==='race')return race();
    const base=race();
    const nodes=page==='cars'?[...base.nodes]:[];
    function add(type,name='',parent=-1,{id='',invoke=false,value='',text=''}={}){
      const index=nodes.length;
      nodes.push({index,parent,type:'ControlType.'+type,name,id,enabled:true,invoke,value,text,patterns:[]});
      return index;
    }
    const document=nodes.length?0:add('Document','iRacing');
    if(page==='cars'){
      const modal=add('Group','',document,{id:'select-car-modal-modal-dialog'});
      add('Text','Select a car',modal);
      const card=add('Group','',modal,{id:'series-select-car-modal-car-card-169',invoke:true});
      add('Text',job.car,card);
      const other=add('Group','',modal,{id:'series-select-car-modal-car-card-198',invoke:true});
      add('Text','Another Car',other);
      add('Text','$13.50',other);
      add('Hyperlink','\ue03aContinue',modal,{invoke:!!car});
      return {...base,nodes};
    }
    const id='chakra-modal-:r1:';
    const form=add('Window','Go Racing',document,{id,invoke:true});
    add('Text','Team Registration',add('Group','Heading',form));
    add('Text','Join a Registered Team',form);
    if(registered&&!noReceipt){
      const row=add('Group','',form);
      add('Text',job.teamName,row);
      add('Text',job.car,row);
      if(joined){
        add('Text',job.ownDriverName,row);
        add('Text','Registered as Driver',row);
      }else add('Button','Register as Driver',row,{invoke:true});
    }
    add('Text','Team Setup',form);
    const field=add('Group','',form);
    add('Text','Select a Team to Register',field);
    add('Edit','Select a Team to Register',field,{id:'field-:r2:',value:team});
    if(menu==='teams'||menu==='drivers'){
      const options=add('List','',form,{id:'react-select-2-listbox'});
      const names=menu==='teams'?[job.teamName,...(duplicateTeam?[job.teamName]:[])]:job.driverNames.filter(n=>!roster.includes(n));
      for(const [i,name] of names.entries())add('ListItem',name,options,{id:`react-select-2-option-${i}`,invoke:true});
    }
    const chosen=extraDriver?[...roster,'Unplanned Driver']:roster;
    add('Text',`${chosen.length} ${chosen.length===1?'Driver':'Drivers'} Selected`,form);
    const table=add('Table','',form);
    add('DataItem','Display Name',table);
    for(const name of chosen){
      const item=add('DataItem',`\ufffc\n${name}\nremove`,table);
      add('DataItem',name,item);
      add('Button','remove',item,{invoke:true});
    }
    add('Button','Add a Driver',form,{invoke:true});
    add('Text',car,add('Group',car,form));
    add('Button',verified?'Register Team':'Verify Team',form,{invoke:true});
    const startUtc=wrongSession?new Date(Date.parse(job.startUtc)+86400000).toISOString():job.startUtc;
    return {...base,nodes,text:'Team Registration',teamTarget:{startUtc,series:wrongSeries?'Other Cup':job.series,track:job.track,car,windowId:id}};
  }
  async function request(op,args){
    if(op==='snapshot')return snapshot();
    if(op==='navigate'&&args.target==='Profile')return {...race(),url:'https://members-ng.iracing.com/web/racing/profile',nodes:[{index:0,parent:-1,type:'ControlType.Text',name:job.ownDriverName}]};
    if(op==='launch_iracing'||op==='navigate'||op==='search_series'||op==='open_series')return race();
    if(op!=='team_action')throw Error('Unexpected operation '+op);
    if(page==='form'&&!args.anchors.some(n=>n.id==='chakra-modal-:r1:'))throw Error('Missing form binding');
    const {node}=args;
    if(node.text==='Register'&&page==='race'){page='cars';actions.push('open race');}
    else if(node.id==='series-select-car-modal-car-card-169'){car=job.car;actions.push('select car');}
    else if(node.name==='\ue03aContinue'&&car){page='form';actions.push('continue');}
    else if(node.name==='Select a Team to Register'){menu='teams';actions.push('open teams');}
    else if(menu==='teams'&&node.name===job.teamName){team=node.name;menu='';actions.push('select team');}
    else if(node.name==='Add a Driver'&&team){menu='drivers';actions.push('open drivers');}
    else if(menu==='drivers'&&job.driverNames.includes(node.name)){roster.push(node.name);menu='';actions.push('select driver');}
    else if(node.name==='Verify Team'&&team===job.teamName&&job.driverNames.every(name=>roster.includes(name))){verified=true;actions.push('verify team');}
    else if(node.name==='Register Team'&&args.phase==='team'&&verified){registered=true;actions.push('register team');}
    else if(node.name==='Register as Driver'&&args.phase==='driver'&&registered){joined=true;actions.push('join as driver');}
    else throw Error('Unexpected action '+node.name);
    return {invoked:true};
  }
  return {request,actions};
}
