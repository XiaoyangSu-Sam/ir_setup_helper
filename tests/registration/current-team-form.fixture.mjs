export function currentTeamClient(race, job, {wrongSession=false, wrongSeries=false, duplicateTeam=false, extraDriver=false, noReceipt=false,genericRegister=false,portalTeam=false,driverTable=false,wrongDriverId=false,separateConfirmation=false,wrongConfirmationTeam=false,tableReceipt=false,missingWithdrawReceipt=false,personalWithdrawPrompt=null}={}){
  const actions=[];
  let page='race', menu='', car='', team='', verified=false, registered=false, joined=false,withdrawn=false;
  let roster=[job.ownDriverName].filter(Boolean);
  function snapshot(){
    if(page==='race')return race();
    const base=race();
    const mainRegistration=page==='registered'||page==='withdraw-confirmation';
    const nodes=page==='cars'||mainRegistration?[...base.nodes]:[];
    function add(type,name='',parent=-1,{id='',invoke=false,value='',text=''}={}){
      const index=nodes.length;
      nodes.push({index,parent,type:'ControlType.'+type,name,id,enabled:true,invoke,value,text,patterns:[]});
      return index;
    }
    const document=nodes.length?0:add('Document','iRacing');
    if(mainRegistration){
      const raceButton=nodes.find(n=>n.id==='id-race');
      Object.assign(raceButton,{name:'Withdraw',text:'Withdraw'});
      add('Text','Registered',document);
      add('Button','button',document,{text:'Withdraw',invoke:true});
      if(page==='withdraw-confirmation'){
        const wrapper=add('Group','',document,{id:'withdraw-modal'});
        const dialog=add('Group','',wrapper,{id:'withdraw-modal-modal-dialog'});
        add('Text','Go Racing',dialog);
        add('Text','Withdraw',dialog);
        add('Text',personalWithdrawPrompt,dialog);
        const controls=add('Group','',dialog);
        add('Button','button',controls,{text:'Cancel',invoke:true});
        add('Button','button',controls,{text:'Withdraw',invoke:true});
      }
      return {...base,nodes,text:base.text+'\nYou may join your session.',driverTarget:{
        startUtc:job.startUtc,team:job.teamName,car:job.car,controlId:'123-reg-button',submittedAt:base.observedAt
      }};
    }
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
    const startUtc=wrongSession?new Date(Date.parse(job.startUtc)+86400000).toISOString():job.startUtc;
    const confirmation=separateConfirmation&&verified&&!registered&&!withdrawn;
    const id=confirmation?'chakra-modal-:confirmation:':'chakra-modal-:r1:';
    const teamTarget={startUtc,series:wrongSeries?'Other Cup':job.series,track:job.track,car,windowId:id,verified,confirmation};
    if(confirmation){
      const form=add('Window','Team Registration',document,{id,invoke:true});
      add('Text','Team Registration',add('Group','Team Registration',form));
      add('Text','Selected Team:',form);
      add('Text',wrongConfirmationTeam?'Another Team':team,form);
      add('Text',roster.length+' Drivers Selected',form);
      const table=add('Table','',form);
      add('DataItem','Display Name',add('DataItem','',table));
      for(const name of roster)add('DataItem',name,add('DataItem','',table));
      add('Text','Above is the list of selected drivers for the session. Please verify this is who you would like.',form);
      const controls=add('Group','',form);
      add('Button','Back',controls,{invoke:true});
      add('Button','button',controls,{id:'123-reg-button',text:'Register',invoke:true});
      return {...base,nodes,text:'Team Registration',teamTarget};
    }
    const form=add('Window','Go Racing',document,{id,invoke:true});
    add('Text','Team Registration',add('Group','Heading',form));
    add('Text','Join a Registered Team',form);
    if(registered&&!noReceipt&&tableReceipt){
      const table=add('Table','',form);
      const header=add('DataItem','',table);
      add('DataItem','Team Name',header);
      add('DataItem','Car',header);
      const row=add('DataItem','',table);
      add('Button','widthdraw-button',add('DataItem','widthdraw-button',row),{invoke:true});
      add('DataItem',job.teamName,row);
      add('DataItem','P9922',row);
      const registration=add('DataItem','',row);
      if(joined){
        add('Text','Registered as Driver',registration);
        add('Text',job.ownDriverName,registration);
        add('Button','Withdraw as Driver',registration,{invoke:true});
      }else add('Button','button',registration,{id:'123-reg-button',text:'Register',invoke:true});
    }else if(withdrawn&&!missingWithdrawReceipt){
      add('Text','There are no registered teams that you may join of 84 teams currently in the session',form);
    }else if(registered&&!noReceipt){
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
    if(portalTeam)add('Group','',form,{id:'menu-button-:teams:',invoke:true});
    if((menu==='teams'&&!portalTeam)||(menu==='drivers'&&!driverTable)){
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
    if(driverTable&&menu==='drivers'){
      add('Button','',form,{id:'accordion-button-:drivers:'});
      const panel=add('Group','',form,{id:'accordion-panel-:drivers:'});
      const available=add('Table','',panel);
      for(const [index,name] of job.driverNames.entries()){
        if(roster.includes(name))continue;
        const row=add('DataItem','',available);
        add('DataItem',name,row);
        add('DataItem','\ue07e'+(wrongDriverId?'900':job.roster[index]),row);
        add('Button','Select',add('DataItem','Select',row),{invoke:true});
      }
    }
    add('Text',car,add('Group',car,form));
    add('Button',verified?(genericRegister?'Register':'Register Team'):'Verify Team',form,{invoke:true});
    if(portalTeam&&menu==='teams'){
      const options=add('Menu','',document,{id:'menu-list-:teams:'});
      add('MenuItem',job.teamName,options,{id:'menu-list-:teams:-menuitem-one',invoke:true});
    }
    return {...base,nodes,text:'Team Registration',teamTarget};
  }
  async function request(op,args){
    if(op==='snapshot')return snapshot();
    if(op==='navigate'&&args.target==='Profile')return {...race(),url:'https://members-ng.iracing.com/web/racing/profile',nodes:[{index:0,parent:-1,type:'ControlType.Text',name:job.ownDriverName}]};
    if(op==='launch_iracing'||op==='navigate'||op==='search_series'||op==='open_series')return race();
    if(op!=='team_action')throw Error('Unexpected operation '+op);
    if(page==='form'&&!args.anchors.some(n=>n.id===snapshot().teamTarget.windowId))throw Error('Missing form binding');
    const {node}=args;
    if(node.text==='Register'&&page==='race'){page='cars';actions.push('open race');}
    else if(node.id==='series-select-car-modal-car-card-169'){car=job.car;actions.push('select car');}
    else if(node.name==='\ue03aContinue'&&car){page='form';actions.push('continue');}
    else if(node.name==='Select a Team to Register'||node.id==='menu-button-:teams:'){menu='teams';actions.push('open teams');}
    else if(menu==='teams'&&node.name===job.teamName){team=node.name;menu='';actions.push('select team');}
    else if(node.name==='Add a Driver'&&team){menu='drivers';actions.push('open drivers');}
    else if(menu==='drivers'&&driverTable&&node.name==='Select'){
      const selected=job.driverNames.find(name=>args.anchors.some(anchor=>anchor.name===name));
      if(!selected)throw Error('Missing driver identity');
      roster.push(selected);menu='';actions.push('select driver');
    }
    else if(menu==='drivers'&&job.driverNames.includes(node.name)){roster.push(node.name);menu='';actions.push('select driver');}
    else if(node.name==='Verify Team'&&team===job.teamName&&job.driverNames.every(name=>roster.includes(name))){verified=true;actions.push('verify team');}
    else if((['Register','Register Team'].includes(node.name)||node.id==='123-reg-button')&&args.phase==='team'&&verified){registered=true;actions.push('register team');}
    else if(node.id==='123-reg-button'&&args.phase==='driver'&&registered){
      joined=true;
      if(personalWithdrawPrompt)page='registered';
      actions.push('join as driver');
    }
    else if(page==='registered'&&node.id==='id-race'&&args.phase==='withdraw_driver'){
      page='withdraw-confirmation';
      actions.push('open personal withdrawal confirmation');
    }
    else if(page==='withdraw-confirmation'&&node.text==='Withdraw'&&args.phase==='withdraw_driver_confirm'){
      const dialog=args.anchors.find(anchor=>anchor.id==='withdraw-modal-modal-dialog');
      if(!dialog||snapshot().nodes[node.parent]?.parent!==dialog.index)throw Error('Withdrawal must use the button inside the confirmation');
      page='race';
      joined=false;
      actions.push('confirm personal withdrawal');
    }
    else if(node.name==='Withdraw as Driver'&&args.phase==='withdraw_driver'&&joined){joined=false;actions.push('withdraw driver');}
    else if(node.name==='widthdraw-button'&&args.phase==='withdraw_team'&&registered&&!joined){registered=false;withdrawn=true;actions.push('withdraw team');}
    else if(node.name==='Register as Driver'&&args.phase==='driver'&&registered){joined=true;actions.push('join as driver');}
    else throw Error('Unexpected action '+node.name);
    return {invoked:true};
  }
  return {request,actions};
}
