(() => {
 const user=window.CURRENT_USER,roles={admin:'مدير النظام',requester:'مقدم طلب',approver:'رئيس قسم',buyer:'المشتريات',warehouse:'المخازن',finance:'المالية',viewer:'عرض فقط'};
 const q=s=>document.querySelector(s),node=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;return n;};
 const api=async(path,data)=>{const r=await fetch(path,{method:data?'POST':'GET',headers:{'Content-Type':'application/json','X-Workspace-Token':window.WORKSPACE_TOKEN},...(data?{body:JSON.stringify(data)}:{})});const out=await r.json();if(!r.ok)throw Error(out.error);return out;};
 const bar=node('div');bar.className='team-account';const identity=node('span',user.name+' · '+roles[user.role]+(user.departmentName?' · '+user.departmentName:''));bar.append(identity);if(!user.departmentName&&user.departmentId)api('/api/departments').then(data=>{const department=data.departments.find(d=>d.id===user.departmentId);if(department)identity.textContent=user.name+' · '+roles[user.role]+' · '+department.name;}).catch(()=>{});const pass=node('button','تغيير كلمة المرور'),logout=node('button','تسجيل الخروج');bar.append(pass,logout);const home=node('a','الرئيسية');home.href='/';home.className='workspace-home';bar.prepend(home);q('body>header').append(bar);
 const dialog=node('dialog');dialog.id='teamDialog';document.body.append(dialog);
 function open(title,onClose){dialog.replaceChildren();const head=node('div');head.className='dialog-heading';const close=node('button','×');close.onclick=()=>onClose?onClose():dialog.close();head.append(node('h2',title),close);dialog.append(head);const content=node('div');dialog.append(content);if(!dialog.open)dialog.showModal();return content;}
 const inboxButton=node('button','الإشعارات');
 inboxButton.id='openInbox';
 const inboxBadge=node('span','0');
 inboxBadge.className='inbox-badge';
 inboxBadge.hidden=true;
 inboxButton.append(inboxBadge);
 bar.prepend(inboxButton);
 let inboxContent=null;
 let inboxRequest=0;
 let inboxSnapshot='';

 function updateInboxBadge(unread){
  inboxBadge.textContent=unread.toLocaleString('ar-IQ');
  inboxBadge.hidden=unread===0;
  inboxButton.setAttribute('aria-label',unread?'الإشعارات، '+unread+' غير مقروءة':'الإشعارات');
 }

 async function refreshInbox(){
  const ticket=++inboxRequest;
  try{
   const data=await api('/api/inbox');
   if(ticket!==inboxRequest)return;
   updateInboxBadge(data.unread);
   if(inboxContent?.isConnected&&dialog.open){
    const snapshot=JSON.stringify(data);
    if(snapshot!==inboxSnapshot){drawInbox(inboxContent,data);inboxSnapshot=snapshot;}
   }
  }catch(e){
   if(ticket===inboxRequest&&inboxContent?.isConnected&&dialog.open)error(inboxContent,e.message);
  }
 }

 function drawInbox(content,data){
  content.replaceChildren();
  const tools=node('div');
  tools.className='actions inbox-tools';
  const allRead=node('button','تحديد الكل كمقروء');
  allRead.type='button';
  allRead.disabled=!data.unread;
  allRead.onclick=async()=>{
   allRead.disabled=true;
   try{await api('/api/inbox/read',{all:true});await refreshInbox();}
   catch(e){error(content,e.message);allRead.disabled=false;}
  };
  tools.append(allRead);
  content.append(tools);
  if(!data.items.length){content.append(node('p','لا توجد إشعارات لحسابك.'));return;}
  const list=node('div');
  list.className='inbox-list';
  for(const item of data.items){
   const row=node('article');
   row.className='inbox-item'+(item.read?'':' unread');
   row.dataset.inboxKind=item.kind;
   const title=node('strong',item.title);
   const time=new Date(item.createdAt).toLocaleString('ar-IQ',{timeZone:'Asia/Baghdad'});
   const meta=node('p','طلب '+item.requestNumber+' · '+time+(item.pending?' · بانتظار إجرائك':''));
   meta.className='inbox-meta';
   const message=node('p',item.message);
   const openItem=node('button',item.kind==='preview'?'فتح المعاينة':'فتح الطلب');
   openItem.type='button';
   openItem.onclick=async()=>{
    openItem.disabled=true;
    try{
     if(item.kind==='preview')await ShamaraTracking.openInboxPreview(item.taskId);
     else await ShamaraTracking.openInboxRequest(item.recordId);
     dialog.close();
     if(!item.read){
      try{const read=await api('/api/inbox/read',{id:item.id});updateInboxBadge(read.unread);}
      catch(_){await refreshInbox();}
     }
    }catch(e){error(content,e.message);openItem.disabled=false;}
   };
   row.append(title,meta,message,openItem);
   list.append(row);
  }
  content.append(list);
 }

 inboxButton.onclick=()=>{
  inboxSnapshot='';
  inboxContent=open('إشعاراتي');
  inboxContent.append(node('p','جارٍ تحميل الإشعارات…'));
  refreshInbox();
 };
 window.addEventListener('shamara-ready',refreshInbox,{once:true});
 window.addEventListener('shamara-inbox-changed',refreshInbox);
 window.addEventListener('focus',refreshInbox);
 setInterval(()=>{if(document.visibilityState==='visible')refreshInbox();},10000);
 function input(form,label,name,type='text',value=''){const l=node('label',label),n=node('input');n.name=name;n.type=type;n.value=value;n.autocomplete=type==='password'?'new-password':'off';l.append(n);form.append(l);return n;}
 function error(form,text){let p=form.querySelector('[role=alert]');if(!p){p=node('p');p.setAttribute('role','alert');p.style.color='#aa4433';form.append(p);}p.textContent=text;}
 pass.onclick=()=>{const f=node('form');open('تغيير كلمة المرور').append(f);input(f,'كلمة المرور الحالية','current','password').required=true;const n=input(f,'كلمة المرور الجديدة (12 حرفاً على الأقل)','password','password');n.minLength=12;n.required=true;const b=node('button','حفظ وإعادة تسجيل الدخول');b.className='primary';f.append(b);f.onsubmit=async e=>{e.preventDefault();try{await api('/api/auth/password',Object.fromEntries(new FormData(f)));location.reload();}catch(e){error(f,e.message);}};};
 logout.onclick=async()=>{if(!confirm('تسجيل الخروج؟ تأكد من اكتمال حفظ التعديلات.'))return;try{await api('/api/auth/logout',{});location.reload();}catch(e){alert(e.message);}};
 function restrictArchive(){const records=archiveFor(state.selected).slice().reverse();q('#archiveRows')?.querySelectorAll('tr').forEach((tr,i)=>{if(!records[i])return;const allowed=ShamaraTracking.canEdit(records[i]);tr.querySelectorAll('button').forEach(b=>b.hidden=!allowed);});}
 async function showAudit(record){const content=open(record?'تدقيق الطلب '+record.form.number:'تدقيق الطلبات');content.append(node('p','جارٍ تحميل سجل الإجراءات…'));try{const {events}=await api('/api/audit'+(record?'?record='+encodeURIComponent(record.id):''));if(!content.isConnected)return;content.replaceChildren();content.append(node('p',user.role==='admin'&&!record?'آخر الإجراءات المسجّلة في النظام.':'سجل إجراءات الطلبات ضمن الشركات المخوّلة لحسابك.'));for(const e of events){const row=node('article');row.className='audit-event';const details=typeof e.details==='string'?JSON.parse(e.details):e.details||{};const statuses=window.ShamaraTracking?.statuses||{};const action=details.fromStatus&&details.status&&details.fromStatus!==details.status&&e.action.startsWith('تغيير الحالة')?'تحويل من '+(statuses[details.fromStatus]||details.fromStatus)+' إلى '+(statuses[details.status]||details.status):e.action;row.append(node('strong',action),node('p',new Date(e.at).toLocaleString('ar-IQ',{timeZone:'Asia/Baghdad'})+' · '+e.actor_name+(e.requestNumber?' · طلب '+e.requestNumber:e.record_id?' · '+e.record_id:'')));if(details.reason)row.append(node('p','السبب: '+details.reason));if(details.notes)row.append(node('p','ملاحظات: '+details.notes));content.append(row);}if(!events.length)content.append(node('p','لا توجد إجراءات مسجّلة.'));}catch(e){content.replaceChildren();error(content,e.message);}}
 if(ShamaraTracking.hasPermission('auditRequests')){const audit=node('button','تدقيق الطلبات');audit.id='openRequestAudit';audit.onclick=()=>showAudit();bar.prepend(audit);window.ShamaraAudit=showAudit;}
 const obs=new MutationObserver(restrictArchive);obs.observe(q('#archiveRows'),{childList:true,subtree:true});restrictArchive();
 if(user.role==='admin'){
  const accounts=node('button','إدارة المستخدمين'),departmentsButton=node('button','إدارة الأقسام'),mail=node('button','إشعارات Outlook');bar.prepend(accounts,departmentsButton,mail);mail.onclick=async()=>{const content=open('إشعارات Microsoft 365 / Outlook');try{const data=await api('/api/mail/status');content.append(node('p',data.configured?'متغيرات إعداد البريد مكتملة. تظهر نتيجة محاولات الإرسال أدناه.':'البريد بانتظار إعداد Microsoft 365 على الخادم المركزي. تُحفظ الإشعارات في طابور الإرسال.'));if(data.invalid?.length)content.append(node('p','إعدادات تحتاج تصحيحًا: '+data.invalid.join('، ')));if(data.missing?.length)content.append(node('p','الإعدادات المطلوبة: '+data.missing.join('، ')));content.append(node('p','راجع README-M365.md داخل مجلد المشروع لخطوات الإعداد. قبول Microsoft للرسالة لا يضمن وصولها إلى صندوق الوارد.'));const counts=data.counts||{};content.append(node('p',Object.entries(counts).map(([k,v])=>k+': '+v).join(' · ')));const {items}=await api('/api/notifications');for(const item of items.filter(x=>['failed','skipped'].includes(x.status))){const row=node('div');row.className='team-user-row';row.append(node('span',item.recipientName+' · '+item.recordId+' · '+(item.lastError||item.status)));const retry=node('button','إعادة المحاولة');retry.onclick=async()=>{if(!confirm('قد تكون الرسالة قُبلت سابقًا. تحقّق من البريد المرسل أولًا. هل تريد إعادة المحاولة؟'))return;retry.disabled=true;try{await api('/api/mail/retry',{id:item.id});row.replaceChildren(node('span','أُعيد الإشعار إلى طابور الإرسال.'));}catch(e){error(content,e.message);retry.disabled=false;}};row.append(retry);content.append(row);}}catch(e){error(content,e.message);}};
  const administration=window.createShamaraAdmin({user,templates,api,open,workflowStages:ShamaraTracking.workflowStages,refreshRouting:()=>ShamaraTracking.refreshDirectory()});
  accounts.onclick=()=>location.assign('/users');
  departmentsButton.onclick=()=>location.assign('/departments');
  const plan=node('button','خطة طلبات الشراء');plan.type='button';plan.id='editWorkflowPlan';plan.className='workflow-plan-button';plan.onclick=administration.showWorkflowPlan;
  q('.pro-tabs').after(plan);

 }

 // A visible library makes all authorized Word formats discoverable in every browser.
 const formats=templates.filter(t=>user.role==='admin'||user.scopes.includes(t.id));
 const tab=node('button','النماذج ('+formats.length.toLocaleString('ar-IQ')+')');tab.id='tabTemplates';tab.setAttribute('role','tab');q('.pro-tabs').append(tab);
 const library=node('main');library.id='templateLibrary';library.innerHTML='<section class="library-heading"><div><p class="eyebrow">SHAMARA / WORD TEMPLATES</p><h2>مكتبة نماذج طلبات الشراء</h2><p id="librarySummary"></p></div><label for="librarySearch">ابحث عن شركة أو موقع<input id="librarySearch" type="search" placeholder="اسم الشركة أو الموقع…"></label></section><div id="libraryGroups"></div><p id="libraryEmpty" hidden>لا توجد نماذج مطابقة للبحث.</p>';
 q('#trackingHub').after(library);
 const libraryKey='shamara-template-library-'+user.id;
 let libraryPrefs={favorites:[],recent:[],mode:'all',group:''};
 try{const saved=JSON.parse(localStorage.getItem(libraryKey)||'null');if(saved&&typeof saved==='object')libraryPrefs={...libraryPrefs,...saved};}catch(_){}
 const allowedIds=new Set(formats.map(t=>t.id));
 for(const key of ['favorites','recent'])libraryPrefs[key]=Array.isArray(libraryPrefs[key])?[...new Set(libraryPrefs[key].filter(id=>allowedIds.has(id)))].slice(0,38):[];
 if(!['all','favorites','recent'].includes(libraryPrefs.mode))libraryPrefs.mode='all';
 const searchText=value=>String(value||'').normalize('NFKC').toLocaleLowerCase().replace(/[\u064B-\u065F\u0670\u0640]/g,'').replace(/[أإآٱ]/g,'ا').replace(/ى/g,'ي').replace(/ة/g,'ه').replace(/\s+/g,' ').trim();
 function storeLibrary(){try{localStorage.setItem(libraryKey,JSON.stringify(libraryPrefs));}catch(_){} }
 const tools=node('div');tools.className='library-controls';const modes=node('div');modes.className='library-modes';modes.setAttribute('aria-label','عرض النماذج');
 const modeButtons={};for(const [mode,label]of [['all','جميع النماذج'],['favorites','المفضلة'],['recent','آخر استخدام']]){const b=node('button',label);b.type='button';b.dataset.libraryMode=mode;b.onclick=()=>{libraryPrefs.mode=mode;storeLibrary();drawLibrary();};modeButtons[mode]=b;modes.append(b);}
 const groupLabel=node('label','المجموعة'),groupSelect=node('select');groupSelect.id='libraryGroup';const allGroups=node('option','جميع المجموعات');allGroups.value='';groupSelect.append(allGroups);for(const group of [...new Set(formats.map(t=>t.group))]){const o=node('option',group);o.value=group;groupSelect.append(o);}groupSelect.value=libraryPrefs.group;if(groupSelect.selectedIndex<0){groupSelect.value='';libraryPrefs.group='';}groupSelect.onchange=()=>{libraryPrefs.group=groupSelect.value;storeLibrary();drawLibrary();};groupLabel.append(groupSelect);tools.append(modes,groupLabel);q('.library-heading').after(tools);
 function showLibrary(){document.body.dataset.view='templates';for(const t of q('.pro-tabs').children)t.setAttribute('aria-selected',String(t===tab));drawLibrary();window.scrollTo({top:0,behavior:'smooth'});}
 function openFormat(id){ShamaraTracking.openTemplate(id);if(state.selected===id&&document.body.dataset.view==='editor'){libraryPrefs.recent=[id,...libraryPrefs.recent.filter(v=>v!==id)].slice(0,8);storeLibrary();}}
 function drawLibrary(){const query=searchText(q('#librarySearch').value);let filtered=formats.filter(t=>(!libraryPrefs.group||t.group===libraryPrefs.group)&&searchText(t.name+' '+t.site+' '+t.group).includes(query)&&(libraryPrefs.mode==='all'||libraryPrefs[libraryPrefs.mode==='favorites'?'favorites':'recent'].includes(t.id)));
 if(libraryPrefs.mode==='recent')filtered.sort((a,b)=>libraryPrefs.recent.indexOf(a.id)-libraryPrefs.recent.indexOf(b.id));
 for(const [mode,b]of Object.entries(modeButtons)){b.setAttribute('aria-pressed',String(libraryPrefs.mode===mode));b.textContent=({all:'جميع النماذج',favorites:'المفضلة',recent:'آخر استخدام'}[mode])+' ('+(mode==='all'?formats.length:libraryPrefs[mode==='favorites'?'favorites':'recent'].length).toLocaleString('ar-IQ')+')';}
 q('#librarySummary').textContent=filtered.length.toLocaleString('ar-IQ')+' من '+formats.length.toLocaleString('ar-IQ')+' نموذج متاح لحسابك. ثبّت النماذج التي تستخدمها كثيرًا في المفضلة.';const groups=q('#libraryGroups');groups.replaceChildren();
 const groupNames=libraryPrefs.mode==='recent'?['آخر النماذج التي فتحتها']:[...new Set(filtered.map(t=>t.group))];
 for(const group of groupNames){const members=libraryPrefs.mode==='recent'?filtered:filtered.filter(t=>t.group===group);if(!members.length)continue;const section=node('section');section.className='library-group';section.append(node('h3',group));const grid=node('div');grid.className='template-library-grid';
 for(const t of members){const card=node('article');card.className='template-library-card';card.dataset.templateCard=t.id;const top=node('div');top.className='template-card-top';const number=node('span',String(templates.findIndex(v=>v.id===t.id)+1).padStart(2,'0'));number.className='template-index';const favorite=node('button',libraryPrefs.favorites.includes(t.id)?'★ مفضّل':'☆ أضف للمفضلة');favorite.className='template-favorite';favorite.type='button';favorite.dataset.favorite=t.id;favorite.setAttribute('aria-pressed',String(libraryPrefs.favorites.includes(t.id)));favorite.setAttribute('aria-label',(libraryPrefs.favorites.includes(t.id)?'إزالة من المفضلة: ':'إضافة إلى المفضلة: ')+t.name);favorite.onclick=()=>{libraryPrefs.favorites=libraryPrefs.favorites.includes(t.id)?libraryPrefs.favorites.filter(id=>id!==t.id):[...libraryPrefs.favorites,t.id];storeLibrary();drawLibrary();q('[data-favorite="'+t.id+'"]')?.focus();};top.append(number,favorite);card.append(top,node('h4',t.name),node('p',t.site));const actions=node('div');actions.className='actions';const open=node('button',ShamaraTracking.canCreate()?'فتح النموذج وإعداد الطلب':'عرض النموذج');open.className='primary';open.dataset.template=t.id;open.onclick=()=>openFormat(t.id);const download=node('button','تنزيل قالب Word');download.onclick=()=>downloadBytes(zipFiles(Object.entries(originalWord[t.id].entries).map(([name,index])=>[name,bytesFrom64(wordBlobs[index])])),companyFolder(t.id)+'_Original.docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document');if(ShamaraTracking.canCreate()||ShamaraTracking.hasPermission('previewRequest'))actions.append(open);actions.append(download);card.append(actions);grid.append(card);}section.append(grid);groups.append(section);}
 q('#libraryEmpty').hidden=filtered.length>0;q('#libraryEmpty').textContent=libraryPrefs.mode==='favorites'&&!libraryPrefs.favorites.length?'لم تضف نماذج للمفضلة بعد. اختر «جميع النماذج» ثم اضغط ☆ بجانب النموذج.':libraryPrefs.mode==='recent'&&!libraryPrefs.recent.length?'ستظهر هنا آخر النماذج التي تفتحها.':'لا توجد نماذج مطابقة. غيّر البحث أو المجموعة.';if(!formats.length)q('#librarySummary').textContent='لم يحدد مدير النظام شركات لحسابك بعد. اطلب منه تعيين الشركات المسموحة من إدارة المستخدمين.';}
 tab.onclick=showLibrary;q('#librarySearch').oninput=drawLibrary;
 for(const id of ['tabTracking','tabEditor'])q('#'+id).addEventListener('click',()=>tab.setAttribute('aria-selected','false'));
 window.addEventListener('shamara-ready',showLibrary,{once:true});drawLibrary();
})();
