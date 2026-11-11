(() => {
 'use strict';
 let user=window.CURRENT_USER;
 const q=selector=>document.querySelector(selector);
 const node=(tag,text,className)=>{
  const element=document.createElement(tag);
  if(text!==undefined)element.textContent=text;
  if(className)element.className=className;
  return element;
 };
 const has=permission=>user.role==='admin'||user.permissions?.[permission]===true;
 const arabic=value=>Number(value).toLocaleString('ar-IQ');
 const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Baghdad',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
 const displayDate=value=>value?new Date(value+'T12:00:00Z').toLocaleDateString('ar-IQ'):'—';
 const displayTime=value=>value?new Date(value).toLocaleString('ar-IQ',{timeZone:'Asia/Baghdad'}):'—';
 const personLabel=(name,username)=>name+(username?' ('+username+')':'');
 const noEditor=item=>item.version>1?'غير موثّق في السجل القديم':'لم يُعدّل';
 const api=async(path,data)=>{
  const response=await fetch(path,{
   method:data===undefined?'GET':'POST',
   headers:{'Content-Type':'application/json','X-Workspace-Token':window.WORKSPACE_TOKEN},
   ...(data===undefined?{}:{body:JSON.stringify(data)}),
  });
  if(response.status===401){location.assign('/');throw Error('انتهت جلسة الدخول.');}
  if(!response.ok){
   const result=await response.json();
   const error=Error(result.error||'تعذر إكمال العملية.');
   error.status=response.status;
   throw error;
  }
  return response;
 };
 const json=async(path,data)=>(await api(path,data)).json();
 const showError=error=>{
  q('#pageError').hidden=false;
  q('#pageError').textContent=error.message;
 };
 q('#accountName').textContent=user.name;
 q('#accountsLink').hidden=user.role!=='admin';
 q('#departmentsLink').hidden=user.role!=='admin';
 q('#homeLink').setAttribute('aria-current',window.ACTIVE_MODULE==='home'?'page':'false');
 let direction=new URLSearchParams(location.search).get('direction')||'all';
 if(!['all','incoming','outgoing'].includes(direction))direction='all';
 let page=1,loadVersion=0,dirty=false;
 const dialog=q('#entryDialog');
 const openDialog=title=>{
  dirty=false;
  q('#dialogTitle').textContent=title;
  q('#dialogContent').replaceChildren();
  if(!dialog.open)dialog.showModal();
  return q('#dialogContent');
 };
 const closeDialog=()=>{
  if(dirty&&!confirm('توجد بيانات غير محفوظة. هل تريد إغلاق النافذة؟'))return;
  dirty=false;
  dialog.close();
 };
 q('#closeDialog').onclick=closeDialog;
 dialog.addEventListener('cancel',event=>{event.preventDefault();closeDialog();});
 window.addEventListener('beforeunload',event=>{
  if(dirty){event.preventDefault();event.returnValue='';}
 });
 q('#logout').onclick=async()=>{
  if(dirty&&!confirm('توجد بيانات غير محفوظة. هل تريد تسجيل الخروج؟'))return;
  try{await json('/api/auth/logout',{});dirty=false;location.assign('/');}catch(error){showError(error);}
 };
 q('#changePassword').onclick=()=>{
  const content=openDialog('تغيير كلمة المرور');
  const form=node('form',undefined,'entry-form');
  for(const [key,label]of [['current','كلمة المرور الحالية'],['password','كلمة المرور الجديدة']]){
   const wrap=node('label',label,'wide'),input=node('input');
   input.name=key;
   input.type='password';
   input.required=true;
   input.autocomplete=key==='current'?'current-password':'new-password';
   input.maxLength=256;
   if(key==='password')input.minLength=12;
   wrap.append(input);
   form.append(wrap);
  }
  const errorLine=node('p','', 'form-error wide');
  errorLine.setAttribute('role','alert');
  const save=node('button','حفظ كلمة المرور','primary');
  save.type='submit';
  const actions=node('div',undefined,'form-actions wide');
  actions.append(save);
  form.append(errorLine,actions);
  content.append(form);
  form.oninput=()=>{dirty=true;};
  form.onsubmit=async event=>{
   event.preventDefault();
   save.disabled=true;
   try{await json('/api/auth/password',Object.fromEntries(new FormData(form)));dirty=false;location.assign('/');}
   catch(error){errorLine.textContent=error.message;save.disabled=false;}
  };
 };
 async function loadHome(){
  q('#homeView').hidden=false;
  q('#greeting').textContent='مرحبًا، '+user.name;
  q('#today').textContent=new Date().toLocaleDateString('ar-IQ',{timeZone:'Asia/Baghdad',weekday:'long',day:'numeric',month:'long',year:'numeric'});
  try{
   const data=await json('/api/portal');
   user=data.user;
   q('#accountsLink').hidden=user.role!=='admin';
   q('#departmentsLink').hidden=user.role!=='admin';
   q('#adminHome').hidden=user.role!=='admin';
   if(has('viewCorrespondence')&&!has('accessPurchases')){q('.register-module').style.order='-1';}
   q('#openPurchases').hidden=!has('accessPurchases');
   q('#purchaseAccessNote').hidden=has('accessPurchases');
   q('#openCorrespondence').hidden=!has('viewCorrespondence');
   q('#registerAccessNote').hidden=has('viewCorrespondence');
   q('#purchaseCount').textContent=data.purchaseCount===null?'—':arabic(data.purchaseCount);
   q('#purchasePending').textContent=has('accessPurchases')?arabic(data.purchasePending):'—';
   q('#incomingCount').textContent=has('viewCorrespondence')?arabic(data.correspondenceCounts.incoming||0):'—';
   q('#outgoingCount').textContent=has('viewCorrespondence')?arabic(data.correspondenceCounts.outgoing||0):'—';
   q('#recentSection').hidden=!data.latest.length;
   for(const item of data.latest){
    const link=node('a',undefined,'recent-row');
    link.href='/correspondence?direction='+item.direction+'&id='+encodeURIComponent(item.id);
    const tag=node('span',item.direction==='incoming'?'وارد':'صادر','direction-tag '+item.direction);
    const text=node('div');
    text.append(node('strong',item.subject),node('small',item.agency+(item.documentNumber?' · رقم الكتاب '+item.documentNumber:'')));
    link.append(tag,text,node('time',displayDate(item.documentDate)));
    q('#recentEntries').append(link);
   }
  }catch(error){showError(error);}
 }
 const filters=()=>({direction,q:q('#searchEntries').value.trim(),from:q('#fromDate').value,to:q('#toDate').value,page});
 const bookLabel=item=>'كتاب '+(item.direction==='incoming'?'وارد':'صادر')+(item.documentNumber?' رقم '+item.documentNumber:'');
 function updateDirection(){
  q('#directionFilter').value=direction;
  q('#addEntry').textContent='+ تسجيل كتاب';
  q('#addEntry').hidden=!has('createCorrespondence');
  q('#exportRegister').hidden=!has('exportCorrespondence');
 }
 async function loadEntries(){
  const ticket=++loadVersion;
  q('#pageError').hidden=true;
  q('#registerStatus').textContent='جارٍ تحميل السجل…';
  try{
   const data=await json('/api/correspondence?'+new URLSearchParams(filters()));
   if(ticket!==loadVersion)return;
   page=data.page;
   q('#registerRows').replaceChildren();

   for(const item of data.items){
    const row=node('tr');
    row.dataset.entryId=item.id;
    const type=node('td');
    type.append(node('span',item.direction==='incoming'?'وارد':'صادر','direction-tag '+item.direction));
    row.append(type);
    for(const value of [item.agency,item.documentNumber||'—',displayDate(item.documentDate),item.subject]){
     const cell=node('td',value);
     if(value===item.subject)cell.className='subject-cell';
     row.append(cell);
    }
    for(const [name,username,at]of [[item.createdByName,item.createdByUsername,item.createdAt],[item.lastEditedByName,item.lastEditedByUsername,item.lastEditedAt]]){
     const person=node('td',undefined,'person-cell');
     person.append(node('strong',name||noEditor(item)));
     if(username){const login=node('small',username,'account-login');login.dir='ltr';person.append(login);}
     if(at)person.append(node('small',displayTime(at)));
     row.append(person);
    }
    const actions=node('td'),buttons=node('div',undefined,'row-actions');
    const view=node('button','عرض');
    view.onclick=()=>viewEntry(item.id).catch(showError);
    buttons.append(view);
    if(has('editCorrespondence')){
     const edit=node('button','تعديل');
     edit.onclick=async()=>{
      try{const result=await json('/api/correspondence/item?id='+encodeURIComponent(item.id));entryForm(result.item);}
      catch(error){showError(error);}
     };
     buttons.append(edit);
    }
    if(has('deleteCorrespondence')){
     const remove=node('button','حذف','delete');
     remove.onclick=async()=>{
      if(!confirm('حذف '+bookLabel(item)+'؟'))return;
      remove.disabled=true;
      try{await json('/api/correspondence/delete',{id:item.id,version:item.version});await loadEntries();}
      catch(error){showError(error);remove.disabled=false;}
     };
     buttons.append(remove);
    }
    actions.append(buttons);
    row.append(actions);
    q('#registerRows').append(row);
   }
   if(!data.items.length){
    const row=node('tr'),cell=node('td',data.total?'لا توجد نتائج في هذه الصفحة.':'لا توجد قيود مطابقة. يمكنك تسجيل كتاب جديد أو تعديل البحث.','empty');
    cell.colSpan=8;
    row.append(cell);
    q('#registerRows').append(row);
   }
   q('#entryCount').textContent=arabic(data.total)+' قيد';
   q('#pageNumber').textContent=arabic(data.page)+' / '+arabic(data.pages);
   q('#previousPage').disabled=data.page===1;
   q('#nextPage').disabled=data.page===data.pages;
   q('#registerStatus').textContent='';
  }catch(error){
   if(ticket!==loadVersion)return;
   q('#registerStatus').textContent=error.message;
  }
 }
 function entryForm(item){
  const editing=Boolean(item);
  const content=openDialog(editing?'تعديل '+bookLabel(item):'تسجيل كتاب');
  const values=item||{id:'COR-'+crypto.randomUUID(),version:0,direction:direction==='all'?'incoming':direction,agency:'',documentNumber:'',documentDate:today(),subject:'',notes:''};
  const form=node('form',undefined,'entry-form');
  form.id='correspondenceForm';
  const controls={};
  let numberMode=editing?'manual':'auto',numberTicket=0;
  const numberHint=node('p','','entry-meta');
  numberHint.setAttribute('role','status');
  const useNext=node('button','استخدام الرقم التالي');
  useNext.type='button';
  useNext.hidden=true;
  const numberTools=node('div',undefined,'number-suggestion wide');
  numberTools.append(numberHint,useNext);
  const refreshNumber=async()=>{
   const ticket=++numberTicket,type=controls.direction.value;
   numberHint.textContent='جارٍ قراءة تسلسل الأرقام…';
   try{
    const result=await json('/api/correspondence/next-number?direction='+encodeURIComponent(type));
    if(ticket!==numberTicket||!form.isConnected||controls.direction.value!==type)return;
    if(numberMode==='auto')controls.documentNumber.value=result.number;
    const shownNumber=node('bdi',result.number);shownNumber.dir='ltr';
    numberHint.replaceChildren('عداد مشترك للصادر والوارد · الرقم التالي ',shownNumber,'. يُثبت عند الحفظ، ويمكنك إدخال رقم آخر ليكمل النظام بعده.');
   }catch(error){if(ticket===numberTicket&&form.isConnected)numberHint.textContent=error.message;}
  };
  const fields=[
   ['agency','اسم الدائرة','text',true,300],
   ['documentNumber','رقم الكتاب','text',false,100],
   ['documentDate','تاريخ الكتاب','date',false,10],
   ['subject','الموضوع','textarea',true,2000],
   ['notes','ملاحظات','textarea',false,4000],
  ];
  const meta=node('p',editing?'سجل '+(values.direction==='incoming'?'الوارد':'الصادر'):'رقم الكتاب يستخدم عدادًا مشتركًا للصادر والوارد.','entry-meta');
  content.append(meta);
  if(!editing){
   const typeLabel=node('label','نوع القيد'),typeSelect=node('select');
   typeSelect.name='direction';
   for(const [value,label]of [['incoming','وارد'],['outgoing','صادر']]){
    const option=node('option',label);
    option.value=value;
    typeSelect.append(option);
   }
   typeSelect.value=values.direction;
   typeLabel.append(typeSelect);
   form.append(typeLabel);
   controls.direction=typeSelect;
   typeSelect.onchange=()=>refreshNumber();
  }
  for(const [key,label,type,required,max]of fields){
   const wrap=node('label',label,type==='textarea'?'wide':undefined);
   const input=node(type==='textarea'?'textarea':'input');
   if(type!=='textarea')input.type=type;
   input.name=key;
   if(key==='documentNumber')input.dir='ltr';
   input.value=values[key];
   input.required=required;
   input.maxLength=max;
   wrap.append(input);
   form.append(wrap);
   controls[key]=input;
   if(key==='documentDate'&&!editing)form.append(numberTools);
  }
  if(!editing){
   controls.documentNumber.addEventListener('input',()=>{numberMode='manual';useNext.hidden=false;});
   useNext.onclick=()=>{numberMode='auto';useNext.hidden=true;refreshNumber();};
  }
  const errorLine=node('p','','form-error wide');
  errorLine.setAttribute('role','alert');
  const save=node('button',editing?'حفظ التعديلات':'حفظ القيد','primary');
  save.type='submit';
  const cancel=node('button','إلغاء');
  cancel.type='button';
  cancel.onclick=closeDialog;
  const actions=node('div',undefined,'form-actions wide');
  actions.append(cancel,save);
  form.append(errorLine,actions);
  form.oninput=()=>{dirty=true;};
  form.onsubmit=async event=>{
   event.preventDefault();
   save.disabled=true;
   errorLine.textContent='';
   try{
    const data={id:values.id,version:values.version,direction:values.direction,numberMode,...Object.fromEntries(Object.entries(controls).map(([key,input])=>[key,input.value.trim()]))};
    const result=await json('/api/correspondence',data);
    dirty=false;
    dialog.close();
    await loadEntries();
    q('#registerStatus').textContent=editing?(result.unchanged?'لا توجد تغييرات جديدة.':'حُفظت التعديلات.'):'حُفظ الكتاب '+(result.item.direction==='incoming'?'الوارد':'الصادر')+(result.item.documentNumber?' بالرقم '+result.item.documentNumber:'')+'.';
   }catch(error){errorLine.textContent=error.message;save.disabled=false;}
  };
  content.append(form);
  if(!editing)refreshNumber();
  controls.agency.focus();
 }
 async function viewEntry(ident){
  const result=await json('/api/correspondence/item?id='+encodeURIComponent(ident));
  const {item}=result;
  const content=openDialog(bookLabel(item));
  const fields=node('dl',undefined,'detail-grid');
  for(const [key,label]of [['agency','اسم الدائرة'],['documentNumber','رقم الكتاب'],['documentDate','تاريخ الكتاب'],['subject','الموضوع'],['notes','ملاحظات']]){
   const wrap=node('div',undefined,['subject','notes'].includes(key)?'wide':undefined);
   wrap.append(node('dt',label),node('dd',key==='documentDate'?displayDate(item[key]):item[key]||'—'));
   fields.append(wrap);
  }
  content.append(fields);
  const people=node('section',undefined,'book-people');
  people.setAttribute('aria-label','من أنشأ الكتاب ومن عدّله');
  for(const [title,name,username,at]of [['أنشأ الكتاب',item.createdByName,item.createdByUsername,item.createdAt],['آخر من عدّل الكتاب',item.lastEditedByName,item.lastEditedByUsername,item.lastEditedAt]]){
   const card=node('div');card.append(node('h3',title),node('p',name?personLabel(name,username):noEditor(item)));
   if(at)card.append(node('small',displayTime(at)));
   people.append(card);
  }
  content.append(people);
  if(has('editCorrespondence')){
   const edit=node('button','تعديل القيد','primary');
   edit.onclick=()=>entryForm(item);
   content.append(edit);
  }
  const events=node('section',undefined,'entry-history');
  events.append(node('h3','سجل الإنشاء والتعديلات'));
  const list=node('ol',undefined,'book-history');
  const more=node('button','عرض تعديلات أقدم');more.type='button';
  const historyStatus=node('p','','entry-meta');historyStatus.setAttribute('role','status');
  const fieldNames={agency:'اسم الدائرة',documentNumber:'رقم الكتاب',documentDate:'تاريخ الكتاب',subject:'الموضوع',notes:'الملاحظات',direction:'نوع القيد'};
  let cursor;
  const appendEvents=data=>{
   for(const event of data.history){
    const entry=node('li');entry.dataset.eventSeq=event.seq;
    entry.append(node('strong',event.action),node('p',personLabel(event.actor,event.username)),node('time',displayTime(event.at)));
    if(event.action.startsWith('تعديل')&&event.changedFields?.length)entry.append(node('small','الحقول المعدّلة: '+event.changedFields.map(key=>fieldNames[key]).filter(Boolean).join('، ')));
    list.append(entry);
   }
   cursor=data.historyBefore;
   more.hidden=!data.historyHasMore;
   if(!list.children.length)historyStatus.textContent='لا يوجد سجل عمليات سابق لهذا الكتاب.';
  };
  appendEvents(result);
  more.onclick=async()=>{
   more.disabled=true;historyStatus.textContent='';
   try{
    const older=await json('/api/correspondence/history?'+new URLSearchParams({id:ident,before:cursor}));
    if(events.isConnected)appendEvents(older);
   }catch(error){if(events.isConnected)historyStatus.textContent=error.message;}
   finally{more.disabled=false;}
  };
  events.append(list,more,historyStatus);
  content.append(events);
 }
 async function initRegister(){
  q('#registerView').hidden=false;
  q('#homeLink').removeAttribute('aria-current');
  updateDirection();
  q('#directionFilter').onchange=()=>{
   direction=q('#directionFilter').value;
   page=1;
   updateDirection();
   history.replaceState(null,'','/correspondence?direction='+direction);
   loadEntries();
  };
  q('#filterForm').onsubmit=event=>{event.preventDefault();page=1;loadEntries();};
  q('#resetFilters').onclick=()=>{for(const id of ['searchEntries','fromDate','toDate'])q('#'+id).value='';direction='all';page=1;updateDirection();history.replaceState(null,'','/correspondence');loadEntries();};
  q('#previousPage').onclick=()=>{page--;loadEntries();};
  q('#nextPage').onclick=()=>{page++;loadEntries();};
  q('#addEntry').onclick=()=>entryForm();
  q('#exportRegister').onclick=async()=>{
   const button=q('#exportRegister');
   button.disabled=true;
   try{
    const response=await api('/api/correspondence/export',filters());
    const url=URL.createObjectURL(await response.blob()),link=node('a');
    link.href=url;
    link.download=({all:'Correspondence',incoming:'Incoming',outgoing:'Outgoing'})[direction]+'_Register.xlsx';
    link.click();
    setTimeout(()=>URL.revokeObjectURL(url),3000);
    q('#registerStatus').textContent='تم تصدير القيود المطابقة للبحث إلى Excel.';
   }catch(error){showError(error);}
   finally{button.disabled=false;}
  };
  await loadEntries();
  const params=new URLSearchParams(location.search);
  if(params.get('id'))await viewEntry(params.get('id')).catch(showError);
 }
 async function initAdministration(){
  if(user.role!=='admin')throw Error('إدارة النظام متاحة لمدير النظام فقط.');
  const mode=window.ACTIVE_MODULE;
  q('#adminView').hidden=false;
  q('#homeLink').removeAttribute('aria-current');
  q(mode==='users'?'#accountsLink':'#departmentsLink').setAttribute('aria-current','page');
  const content=q('#adminPageContent'),back=q('#adminBack');
  let administration;
  const open=(title,onBack,screen)=>{
   dirty=false;
   q('#adminPageTitle').textContent=title;
   document.title='شمارة · '+title;
   content.replaceChildren();
   back.hidden=['users','departments'].includes(screen);
   back.onclick=onBack||(()=>mode==='users'?administration.showUsers():administration.showDepartments());
   window.scrollTo(0,0);
   return content;
  };
  content.oninput=()=>{dirty=true;};
  administration=window.createShamaraAdmin({user,templates:window.ADMIN_TEMPLATES,api:json,open,navigateDepartments:()=>location.assign('/departments')});
  await(mode==='users'?administration.showUsers():administration.showDepartments());
 }
 if(window.ACTIVE_MODULE==='correspondence')initRegister().catch(showError);
 else if(['users','departments'].includes(window.ACTIVE_MODULE))initAdministration().catch(showError);
 else loadHome();
})();
