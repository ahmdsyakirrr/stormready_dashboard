"use strict";
(function(){
  const $=id=>document.getElementById(id);
  const state={user:null,items:[],operators:[],selected:null,detail:null,live:null,online:false,active:null,busy:false,polling:false,listKey:'',serverTime:0};
  const labels={open:'Unassigned',assigned:'Assigned',in_progress:'In progress',awaiting_review:'Awaiting review',closed:'Closed'};
  const locations={upstream:'Upstream chamber',downstream:'Retention pond'};
  const time=new Intl.DateTimeFormat('en-MY',{timeZone:'Asia/Kuala_Lumpur',dateStyle:'medium',timeStyle:'medium'});
  const at=value=>value===null||value===undefined?'—':time.format(new Date(value*1000));
  const set=(id,value)=>{const n=$(id);if(n.textContent!==String(value))n.textContent=String(value);};
  const fmt=value=>typeof value==='number'&&Number.isFinite(value)?value.toFixed(1):'—';
  const displayOutcome=value=>({improved:'Greater drawdown observed',not_improved:'No sufficient improvement',inconclusive:'Evidence incomplete or not comparable'}[value]||value);
  function message(value,tone='success'){$('message').hidden=!value;$('message').className=`message ${tone==='error'?'error':tone==='info'?'info':''}`;$('message').setAttribute('role',tone==='error'?'alert':'status');set('message',value||'');set('announcer',value||'');}
  async function api(url,body){
    const response=await fetch(url,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
    const data=await response.json();
    if(!response.ok){if(response.status===401&&state.user){state.user=null;showAuth(false);}throw new Error(data.error||'The server could not complete this request.');}
    return data;
  }
  function showAuth(setup){
    $('auth-panel').hidden=false;$('workspace').hidden=true;$('logout').hidden=true;
    $('setup-form').hidden=!setup;$('login-form').hidden=setup;
    set('auth-title',setup?'Set up your incident workspace':'Sign in to your workspace');
    set('auth-description',setup?'Create a supervisor account and a separate maintenance operator account.':'Operator accounts record work. Supervisor accounts assign and review cases.');
    set('signed-in-name','');
  }
  function signedIn(user){state.user=user;$('auth-panel').hidden=true;$('workspace').hidden=false;$('logout').hidden=false;set('signed-in-name',`${user.display_name} · ${user.role==='supervisor'?'Supervisor':'Operator'}`);}
  function liveValue(sensor){
    const data=state.live,row=data?.latest;
    return data?.summary.connection==='online'&&row?.[sensor+'_current_quality']==='good'&&typeof row[sensor+'_mm']==='number'?row[sensor+'_mm']:null;
  }
  function renderLive(){
    const up=liveValue('upstream'),pond=liveValue('downstream');
    set('sensor-state',!state.online?'Unavailable':up===null||pond===null?'Check readings':'Live readings');
    $('sensor-state').className=up===null||pond===null?'offline':'';
    set('sensor-detail',`Upstream ${fmt(up)} mm · Pond ${fmt(pond)} mm`);
  }
  function renderList(){
    const search=$('case-search').value.toLowerCase().trim(),status=$('status-filter').value,location=$('location-filter').value;
    const items=state.items.filter(item=>(status==='all'||status==='active'&&item.status!=='closed'||item.status===status)&&(location==='all'||item.location===location)&&(!search||[item.code,item.assigned_name,locations[item.location]].join(' ').toLowerCase().includes(search)));
    const key=JSON.stringify([items,state.selected]);if(key===state.listKey)return;state.listKey=key;
    const list=$('case-list');list.replaceChildren();
    if(!items.length){const p=document.createElement('p');p.className='queue-footnote';p.textContent=state.items.length?'No cases match these filters.':'No incidents yet. Fresh confirmed high water will create a case automatically.';list.appendChild(p);return;}
    items.forEach(item=>{
      const button=document.createElement('button');button.type='button';button.className=`case-button ${state.selected===item.id?'selected':''}`;button.setAttribute('aria-pressed',String(state.selected===item.id));
      const top=document.createElement('span');top.className='case-top';top.append(document.createTextNode(item.code));
      const badge=document.createElement('span');badge.className=`badge ${item.status}`;badge.textContent=labels[item.status];top.appendChild(badge);
      const title=document.createElement('strong');title.textContent=locations[item.location];const operator=document.createElement('small');operator.textContent=item.assigned_name?`Assigned to ${item.assigned_name}`:'Awaiting operator assignment';const when=document.createElement('small');when.textContent=at(item.detected_at);
      button.append(top,title,operator,when);button.addEventListener('click',()=>select(item.id));list.appendChild(button);
    });
  }
  function stopPrompt(reason){set('capture-dialog-message',reason+' The dashboard does not switch pump power.');if(!$('capture-dialog').open)$('capture-dialog').showModal();}
  function renderTrialHistory(runs){
    const list=$('trial-history');list.replaceChildren();
    if(!runs.length){const li=document.createElement('li');li.textContent='No captures recorded for this case.';list.appendChild(li);return;}
    runs.forEach(run=>{const li=document.createElement('li');const title=document.createElement('strong');title.textContent=`Cycle ${run.cycle} · ${run.phase==='before'?'Before':'After'} work · ${run.status}`;const copy=document.createElement('span');copy.textContent=run.reason;const when=document.createElement('time');when.textContent=at(run.started_at);when.dateTime=new Date(run.started_at*1000).toISOString();li.append(title,copy,when);list.appendChild(li);});
  }
  function renderInspection(records){
    const list=$('inspection-records');list.replaceChildren();
    if(!records.length){const p=document.createElement('p');p.className='help';p.textContent='No inspection record yet.';list.appendChild(p);return;}
    records.forEach(record=>{const card=document.createElement('article');card.className='record-card';const heading=document.createElement('strong');heading.textContent=`Cycle ${record.cycle} · ${record.operator_name}`;const findings=document.createElement('p');findings.textContent='Findings: '+record.findings;const work=document.createElement('p');work.textContent='Work: '+record.work_done;const when=document.createElement('small');when.textContent=at(record.created_at);card.append(heading,findings,work,when);list.appendChild(card);});
  }
  const eventLabels={detected:'High water confirmed',assigned:'Operator assigned',inspection_recorded:'Inspection and work recorded',evidence_started:'Evidence capture started',evidence_completed:'Evidence capture completed',evidence_inconclusive:'Capture inconclusive',evidence_cancelled:'Capture cancelled',submitted_for_review:'Submitted for review',kept_open:'Further work requested',closed_after_review:'Closed after supervisor review'};
  function renderEvents(events){
    const list=$('case-events');list.replaceChildren();
    events.forEach(event=>{const li=document.createElement('li');const title=document.createElement('strong');title.textContent=`${eventLabels[event.action]||event.action} · ${event.actor}`;const p=document.createElement('span');const d=event.detail;p.textContent=d.note||d.reason||(d.operator?`Assigned to ${d.operator}`:d.level_mm!==undefined?`${fmt(d.level_mm)} mm · alert ${fmt(d.threshold_mm)} mm`:d.phase?`${d.phase} maintenance · cycle ${event.cycle}`:d.comparison?displayOutcome(d.comparison.outcome):`Review cycle ${event.cycle}`);const when=document.createElement('time');when.textContent=at(event.created_at);when.dateTime=new Date(event.created_at*1000).toISOString();li.append(title,p,when);list.appendChild(li);});
  }
  function comparisonTable(result){
    const body=$('comparison-table');body.replaceChildren();
    for(const [label,key,unit] of [['Start upstream','start_upstream_mm',' mm'],['Start pond','start_downstream_mm',' mm'],['Observed start depth','start_mm',' mm'],['Observed end depth','end_mm',' mm'],['Depth drop','drop_mm',' mm'],['Drawdown rate','rate_mm_per_minute',' mm/min'],['Observation span','span_seconds',' s'],['Valid samples','samples','']]){
      const tr=document.createElement('tr');const th=document.createElement('th');th.scope='row';th.textContent=label;tr.appendChild(th);for(const phase of ['before','after']){const td=document.createElement('td');const value=result[phase]?.[key];td.textContent=value===undefined?'—':key==='samples'?value:fmt(value)+unit;tr.appendChild(td);}body.appendChild(tr);
    }
  }
  function controls(){
    const d=state.detail;if(!d||!state.user)return;
    const assigned=state.user.role==='operator'&&d.assigned_to===state.user.id;
    const workable=assigned&&['assigned','in_progress'].includes(d.status);
    const current=d.current_profile;
    const running=!!state.active;
    const ready=state.online&&!state.busy&&liveValue('upstream')!==null&&liveValue('downstream')!==null;
    const inspection=d.inspections.some(record=>record.cycle===d.cycle);
    const before=d.trials.some(run=>run.cycle===d.cycle&&run.phase==='before'&&run.status==='completed');
    $('assignment-form').hidden=state.user.role!=='supervisor'||d.status==='closed'||d.status==='awaiting_review';
    $('capture-form').hidden=!workable;
    $('capture-before').disabled=!ready||running||!current||inspection;
    $('capture-after').disabled=!ready||running||!current||!inspection||!before;
    $('cancel-capture').hidden=!state.active||state.active.incident_id!==d.id;
    $('cancel-capture').disabled=state.busy;
    $('inspection-form').hidden=!workable;
    $('inspection-form').querySelector('button').disabled=!state.online||state.busy||running;
    $('assignment-form').querySelector('button').disabled=!state.online||state.busy||running;
    $('operator-submit').hidden=!workable;
    $('submit-review').disabled=!state.online||state.busy||running||!inspection;
    $('review-form').hidden=state.user.role!=='supervisor'||d.status!=='awaiting_review';
    $('close-case').disabled=!state.online||state.busy||!d.closure_check.eligible;
    $('keep-open').disabled=!state.online||state.busy;
  }
  function renderDetail(data,changed=false){
    state.detail=data;$('no-selection').hidden=true;$('case-content').hidden=false;
    if(changed){$('inspection-form').reset();$('review-form').reset();$('capture-form').reset();const previous=data.trials.find(run=>run.cycle===data.cycle&&run.phase==='before');$('setup-label').value=previous?.conditions.setup_label||'Bench setup A';}
    set('case-code',`${data.code} · REVIEW CYCLE ${data.cycle}`);set('case-title',locations[data.location]);set('case-meta',`Detected ${at(data.detected_at)} · ${fmt(data.detected_level)} mm · alert ${fmt(data.threshold)} mm`);set('case-status',labels[data.status]);$('case-status').className=`badge ${data.status}`;
    const stages={open:0,assigned:1,in_progress:2,awaiting_review:3,closed:4};document.querySelectorAll('.progress li').forEach((n,i)=>n.classList.toggle('done',i<=stages[data.status]));
    set('case-context',data.status==='closed'?'Supervisor reviewed and closed this case. Its inspection records and captured evidence remain available.':!data.current_profile?'This case uses an earlier operating profile. Keep it open for supervisor assessment.':`This case remains open until a supervisor reviews the work and evidence. Water-alert acknowledgement and clearing do not close it. Closure needs fresh readings below ${fmt(data.clear_threshold)} mm for five seconds.`);
    set('assignment-current',data.assigned_name?`Assigned operator: ${data.assigned_name}`:'A supervisor must assign this case before work is recorded.');
    const selected=$('assigned-operator').value;
    if(JSON.stringify(state.operators)!==$('assigned-operator').dataset.items){$('assigned-operator').replaceChildren();state.operators.forEach(person=>{const option=document.createElement('option');option.value=person.id;option.textContent=person.display_name;$('assigned-operator').appendChild(option);});$('assigned-operator').dataset.items=JSON.stringify(state.operators);}
    if(changed||!selected)$('assigned-operator').value=data.assigned_to||state.operators[0]?.id||'';
    const pond=data.location==='downstream';
    set('test-conditions',pond?'Pond drawdown: close the gravity drain, allow no other inflow and keep the transfer pump fully submerged. Operate the pump manually during each capture, using the same hose route and power supply. Stop it immediately when capture ends or coverage becomes unsafe.':'Upstream drawdown: keep the pump OFF, open the gravity drain and allow no other inflow. Use the same container positions and drain setting for both captures. Restore both starting depths within 5 mm before the after capture.');
    set('conditions-label',pond?'I confirm matching physical conditions, no other inflow and full pump coverage. I will operate the pump manually, supervise throughout and stop it when the capture ends.':'I confirm the pump is OFF, the gravity drain is open and there is no other inflow. I will supervise the model and use matching physical conditions.');
    const result=data.comparison;set('comparison-result',`${displayOutcome(result.outcome)}. ${result.reason}`);$('comparison-result').className=`comparison-result ${result.outcome}`;comparisonTable(result);renderTrialHistory(data.trials);renderInspection(data.inspections);renderEvents(data.events);set('closure-check',data.status==='closed'?'This case is closed. Download its full record below.':data.closure_check.reason);$('export-case').href=`/api/incidents/${data.id}/export.json`;controls();
  }
  async function select(id){state.selected=id;renderList();try{renderDetail(await api(`/api/incidents/${id}`),true);}catch(error){message(error.message,'error');}}
  async function refresh(){
    if(!state.user||state.polling||state.busy)return;state.polling=true;
    try{
      const [list,live]=await Promise.all([api('/api/incidents'),api('/api/status')]);
      state.online=true;state.items=list.incidents;state.operators=list.operators;state.live=live;state.serverTime=list.server_time;
      set('metric-open',state.items.filter(x=>x.status!=='closed').length);set('metric-review',state.items.filter(x=>x.status==='awaiting_review').length);set('metric-closed',state.items.filter(x=>x.status==='closed').length);
      const previous=state.active;state.active=list.active_capture;
      if(previous&&!state.active){const ended=await api(`/api/incidents/${previous.incident_id}`);const run=ended.trials.find(x=>x.id===previous.id);stopPrompt(run?.reason||'The evidence capture ended. Inspect the model and stop any manual pump.');$('conditions-confirmed').checked=false;}
      $('capture-running').hidden=!state.active;
      if(state.active)set('capture-running',`CAPTURE RUNNING · ${locations[state.active.location]} · ${Math.max(0,list.server_time-state.active.started_at).toFixed(1)}s · Supervise the model. Pump power is manual. Stop any pump when capture ends or sooner if needed.`);
      renderLive();renderList();
      if(state.selected){const d=await api(`/api/incidents/${state.selected}`);renderDetail(d);}
      else if(state.items.length)await select(state.items[0].id);
      if(!previous&&state.active)set('announcer','A controlled capture is running. Supervise the model.');
    }catch(error){state.online=false;state.live=null;renderLive();controls();if(state.active)stopPrompt('Dashboard connection lost. Stop any manual pump now. Recovery evidence is unavailable.');message(error.message==='Failed to fetch'?'Dashboard connection lost. Current readings are unavailable.':error.message,'error');}
    finally{state.polling=false;}
  }
  async function act(path,body,success){
    if(state.busy)return;state.busy=true;controls();
    try{await api(path,body);message(success);return true;}catch(error){message(error.message,'error');$('message').scrollIntoView({behavior:'smooth',block:'nearest'});return false;}
    finally{state.busy=false;await refresh();controls();}
  }
  $('login-form').addEventListener('submit',async event=>{event.preventDefault();try{const result=await api('/api/workflow/login',{username:$('login-username').value,password:$('login-password').value});$('login-password').value='';signedIn(result.user);message('Signed in. Your work and review decisions are recorded under your account.');await refresh();}catch(error){message(error.message,'error');}});
  $('setup-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;const data=new FormData(form);const body={};for(const role of ['supervisor','operator'])body[role]={username:data.get(role+'_username'),display_name:data.get(role+'_name'),password:data.get(role+'_password')};try{await api('/api/workflow/setup',body);form.reset();showAuth(false);$('login-username').value=body.supervisor.username;message('Accounts created. Sign in as the supervisor to assign incidents.');}catch(error){message(error.message,'error');}});
  $('logout').addEventListener('click',async()=>{if(state.active){stopPrompt('Before signing out, stop any manual pump and cancel the active capture.');return;}try{await api('/api/workflow/logout',{});state.user=null;state.detail=null;state.selected=null;showAuth(false);message('Signed out. Incident records remain saved.');}catch(error){message(error.message,'error');}});
  $('assignment-form').addEventListener('submit',async event=>{event.preventDefault();await act(`/api/incidents/${state.selected}/assign`,{version:state.detail.version,operator_id:Number($('assigned-operator').value)},'Operator assigned. Sign in as the assigned operator to record work and evidence.');});
  $('inspection-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;const saved=await act(`/api/incidents/${state.selected}/inspection`,{version:state.detail.version,findings:$('inspection-findings').value,work_done:$('inspection-work').value},'Inspection findings and work saved. Capture after evidence under matching conditions.');if(saved)form.reset();});
  async function capture(phase){if(!$('capture-form').reportValidity())return;const saved=await act(`/api/incidents/${state.selected}/captures`,{version:state.detail.version,phase,setup_label:$('setup-label').value,conditions_confirmed:$('conditions-confirmed').checked},'Capture started. Keep the declared conditions unchanged and supervise continuously.');if(saved)$('conditions-confirmed').checked=false;}
  $('capture-before').addEventListener('click',()=>capture('before'));$('capture-after').addEventListener('click',()=>capture('after'));
  $('cancel-capture').addEventListener('click',async()=>{stopPrompt('Cancel requested. Stop any manual pump now.');await act(`/api/incidents/${state.selected}/captures/cancel`,{},'Capture cancelled. Check the physical pump is OFF.');});
  $('submit-review').addEventListener('click',()=>act(`/api/incidents/${state.selected}/submit`,{version:state.detail.version},'Case submitted. A supervisor can now review the evidence and decide.'));
  async function review(decision){if(!$('review-form').reportValidity())return;await act(`/api/incidents/${state.selected}/review`,{version:state.detail.version,decision,review_note:$('review-note').value,evidence_reviewed:$('evidence-reviewed').checked},decision==='close'?'Supervisor approved and closed this case.':'Case kept open. The next review cycle needs new evidence and a new maintenance record.');}
  $('close-case').addEventListener('click',()=>review('close'));$('keep-open').addEventListener('click',()=>review('keep_open'));
  $('review-form').addEventListener('submit',event=>event.preventDefault());
  $('capture-dialog-done').addEventListener('click',()=>$('capture-dialog').close());
  ['case-search','status-filter','location-filter'].forEach(id=>$(id).addEventListener(id==='case-search'?'input':'change',()=>{state.listKey='';renderList();}));
  window.addEventListener('beforeunload',event=>{if(state.active){event.preventDefault();event.returnValue='';}});
  async function boot(){try{const session=await api('/api/workflow/session');if(session.user){signedIn(session.user);await refresh();}else showAuth(session.setup_required);}catch(error){message('Could not reach the incident service. Restart the upgraded server.','error');}}
  boot();setInterval(refresh,1500);
})();
