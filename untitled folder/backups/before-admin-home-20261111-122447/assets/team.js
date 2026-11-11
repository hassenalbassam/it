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
  const departmentKinds={general:'قسم إداري / تشغيلي',purchasing:'المشتريات',finance:'المالية',warehouse:'المخازن'};
  const descriptions={admin:'صلاحيات كاملة لإدارة الحسابات والأقسام وتعديل الطلبات والحالات والتعيين اليدوي.',requester:'ينشئ الطلبات ويتابعها وفق خطة طلبات الشراء المعتمدة.',approver:'يوافق على طلبات القسم الذي يديره وفق الصلاحيات المحددة.',buyer:'يعمل ضمن قائمة المشتريات المشتركة، ويستطيع المخوّل تسعير الطلب وتحويله.',warehouse:'يتابع تجهيز وتسليم الطلبات المخوّلة ضمن قسم المخازن.',finance:'يعمل ضمن قائمة المالية المشتركة، ويستطيع المخوّل الموافقة على الصرف.',viewer:'يعرض الطلبات والنماذج حسب الشركات والصلاحيات المسموحة.'};
  const fallbackLabels={createRequest:'إنشاء طلب شراء',editOwnRequest:'تعديل مسوداته وطلباته المرفوضة',editAnyRequest:'تعديل طلبات الشركة',deleteRequest:'حذف الطلبات المسموحة',submitRequest:'إرسال الطلب للموافقة',approveDepartment:'موافقة مدير القسم',priceRequest:'التسعير واعتماد المشتريات',approveFinance:'الموافقة المالية على الصرف',prepareRequest:'تجهيز الطلب',deliverRequest:'تأكيد التسليم',viewCompanyRequests:'عرض طلبات الشركة',previewRequest:'معاينة المستند وطباعته',auditRequests:'تدقيق الطلبات — عرض سجل الإجراءات',exportExcel:'تصدير Excel',importExcel:'استيراد Excel'};
  let adminData={users:[],departments:[],catalog:{permissions:[],roleDefaults:{}}};
  async function refreshAdminData(){const [usersData,departmentsData,catalog,workflow]=await Promise.all([api('/api/users'),api('/api/departments'),api('/api/permission-catalog'),api('/api/workflow/plan')]);adminData={users:usersData.users,departments:departmentsData.departments,catalog,workflowPlan:workflow.plan};return adminData;}
  function departmentName(id){return adminData.departments.find(d=>d.id===id)?.name||'لم يُحدد قسم';}
  async function refreshRouting(){if(window.ShamaraTracking?.refreshDirectory)await ShamaraTracking.refreshDirectory();window.dispatchEvent(new Event('shamara-accounts-updated'));}
  async function showWorkflowPlan(){
   const content=open('خطة طلبات الشراء');
   content.append(node('p','جارٍ تحميل الخطة…'));
   try{
    const {plan}=await api('/api/workflow/plan');
    if(!content.isConnected)return;
    content.replaceChildren();
    content.append(node('p','قدّم مراحل الأقسام أو أخّرها بالأزرار، ثم احفظ الخطة. إنشاء الطلب في البداية، والإغلاق في النهاية. يُعتمد الترتيب عند تقديم الطلب أو إعادة تقديمه، ويكمل الطلب الجاري بخطته المحفوظة.'));
    const form=node('form');
    form.id='workflowPlanForm';
    const definitions=[
     ['requestCreation','إنشاء الطلب','حفظ الطلب كمسودة قبل تقديمه. عند التخطي يُرسل الطلب مباشرة عند الحفظ.'],
     ['departmentApproval','موافقة مدير القسم','توجيه الطلب إلى مدير قسم مقدم الطلب في موقع هذه المرحلة.'],
     ['purchasePricing','تسعير المشتريات','إدخال المورد وقيمة التسعير من قسم المشتريات.'],
     ['financeApproval','موافقة المالية على الصرف','مراجعة الطلب والموافقة على الصرف في ترتيب هذه المرحلة.'],
     ['warehouseCheck','فحص المخازن','اختيار متوفر أو غير متوفر لتحديد القسم الذي يتولى مراحل التجهيز والتسليم.'],
     ['preparation','التجهيز','تأكيد اكتمال تجهيز المواد من المخازن أو المشتريات.'],
     ['readyForDelivery','جاهز للتسليم','تسجيل التسليم الفعلي من قسم التجهيز إلى مقدم الطلب.'],
     ['receiptConfirmation','تأكيد الاستلام','تأكيد مقدم الطلب أنه استلم المواد.'],
     ['completion','مكتمل','عرض حالة «مكتمل» عند انتهاء المراحل المختارة. عند التخطي تكون الحالة «انتهت الخطة».'],
    ];
    const defaultOrder=definitions.map(([key])=>key).filter(key=>!['requestCreation','completion'].includes(key));
    let order=plan.stageOrder.slice();
    const selections={},rows=new Map(),stageList=node('div');
    stageList.className='plan-stages-editor';
    form.append(stageList);
    for(const [key,label,description]of definitions){
     const row=node('div');
     row.className='plan-option';
     row.dataset.workflowStage=key;
     const choice=node('label'),checkbox=node('input');
     checkbox.type='checkbox';
     checkbox.checked=plan[key];
     checkbox.name=key;
     const text=node('span');
     text.append(node('strong',label),node('small',description));
     choice.append(checkbox,text);
     row.append(choice);
     selections[key]=checkbox;
     const up=node('button','↑ تقديم'),down=node('button','↓ تأخير');
     if(defaultOrder.includes(key)){
      const moves=node('div');
      moves.className='plan-move-controls';
      for(const button of [up,down])button.type='button';
      up.setAttribute('aria-label','تقديم '+label);
      down.setAttribute('aria-label','تأخير '+label);
      up.dataset.move='up';
      down.dataset.move='down';
      up.onclick=()=>{moveStage(key,-1);up.focus();};
      down.onclick=()=>{moveStage(key,1);down.focus();};
      moves.append(up,down);
      row.append(moves);
     }
     rows.set(key,{row,up,down});
    }
    const drawRows=()=>{
     for(const key of ['requestCreation',...order,'completion']){
      const item=rows.get(key),index=order.indexOf(key);
      item.up.disabled=index<=0;
      item.down.disabled=index<0||index===order.length-1;
      stageList.append(item.row);
     }
    };
    const moveStage=(key,step)=>{
     const index=order.indexOf(key),target=index+step;
     if(target<0||target>=order.length)return;
     [order[index],order[target]]=[order[target],order[index]];
     drawRows();
     drawPlan();
    };
    drawRows();
    const preview=node('div');
    preview.className='workflow-plan-preview';
    preview.setAttribute('aria-live','polite');
    const draft=()=>({...plan,stageOrder:order.slice(),...Object.fromEntries(Object.entries(selections).map(([key,checkbox])=>[key,checkbox.checked]))});
    const drawPlan=()=>{
     preview.replaceChildren(node('h3','المسار عند إرسال الطلب'));
     const stages=node('ol');
     stages.className='workflow-stages';
     for(const [,label]of ShamaraTracking.workflowStages(draft()))stages.append(node('li',label));
     preview.append(stages);
     if(!selections.warehouseCheck.checked&&(selections.preparation.checked||selections.readyForDelivery.checked))preview.append(node('p','يتولى قسم المشتريات مراحل التجهيز والتسليم المختارة.'));
     if(!selections.requestCreation.checked)preview.append(node('p','يُرسل الطلب مباشرة عند الحفظ.'));
     if(!selections.completion.checked)preview.append(node('p','ينتهي الطلب بعد آخر مرحلة مختارة بحالة «انتهت الخطة».'));
     if(!Object.values(selections).some(checkbox=>checkbox.checked))preview.append(node('p','لا توجد مراحل مفعّلة. يُغلق الطلب مباشرة عند الحفظ بحالة «انتهت الخطة».'));
    };
    for(const checkbox of Object.values(selections))checkbox.onchange=drawPlan;
    drawPlan();
    form.append(preview);
    const result=node('p');
    result.id='workflowPlanResult';
    result.setAttribute('role','status');
    const actions=node('div');
    actions.className='actions';
    const save=node('button','حفظ الخطة');
    save.type='submit';
    save.className='primary';
    save.id='saveWorkflowPlan';
    const reset=node('button','اختيار الخطة الكاملة');
    reset.type='button';
    reset.onclick=()=>{
     for(const checkbox of Object.values(selections))checkbox.checked=true;
     drawPlan();
     result.textContent='اختيرت جميع المراحل. اضغط «حفظ الخطة» لاعتمادها.';
    };
    const resetOrder=node('button','إعادة الترتيب الافتراضي');
    resetOrder.type='button';
    resetOrder.id='resetWorkflowOrder';
    resetOrder.onclick=()=>{
     order=defaultOrder.slice();
     drawRows();
     drawPlan();
     result.textContent='أُعيد ترتيب المراحل. اضغط «حفظ الخطة» لاعتماده.';
    };
    actions.append(save,reset,resetOrder);
    form.append(actions,result);
    content.append(form);
    form.onsubmit=async event=>{
     event.preventDefault();
     save.disabled=true;
     try{
      const response=await api('/api/workflow/plan',draft());
      Object.assign(plan,response.plan);
      await refreshRouting();
      result.textContent=response.changed?'حُفظت الخطة. تُطبق عند إرسال الطلبات أو إعادة تقديمها.':'هذه الخطة معتمدة بالفعل.';
     }catch(e){error(form,e.message);}
     finally{save.disabled=false;}
    };
   }catch(e){content.replaceChildren();error(content,e.message);}
  }

  async function showUsers(){const content=open('المستخدمون والأقسام والصلاحيات');content.append(node('p','جارٍ تحميل الحسابات…'));try{const data=await refreshAdminData();if(!content.isConnected)return;content.replaceChildren();const tools=node('div');tools.className='actions';const add=node('button','+ مستخدم جديد');add.className='primary';add.id='addUser';add.onclick=()=>editUser();const departments=node('button','إدارة الأقسام');departments.onclick=showDepartments;const plan=node('button','خطة طلبات الشراء');plan.type='button';plan.id='editWorkflowPlan';plan.onclick=showWorkflowPlan;tools.append(add,departments,plan);content.append(tools,node('p','حدّد أقسام الموظفين وصلاحياتهم، وعدّل مراحل الطلب من «خطة طلبات الشراء».'));
   for(const u of data.users){const row=node('div');row.className='team-user-row';row.dataset.userId=u.id;const info=node('div');info.append(node('strong',u.name+' ('+u.username+')'),node('p',(roles[u.role]||u.role)+' · '+departmentName(u.departmentId)+' · '+(u.active?'نشط':'معطّل')));const edit=node('button','تعديل الحساب والصلاحيات');edit.onclick=()=>editUser(u);row.append(info,edit);content.append(row);}if(!data.users.length)content.append(node('p','لا توجد حسابات.'));
  }catch(e){content.replaceChildren();error(content,e.message);}}
  async function editUser(u={role:'requester',active:true,scopes:[]}){const content=open(u.id?'تعديل المستخدم وصلاحياته':'إنشاء مستخدم');content.append(node('p','جارٍ تحميل الأقسام والصلاحيات…'));try{await refreshAdminData();if(!content.isConnected)return;content.replaceChildren();const form=node('form');form.id='userAccountForm';content.append(form);
   const name=input(form,'الاسم الكامل','name','text',u.name||'');name.required=true;const username=input(form,'اسم المستخدم الإنجليزي','username','text',u.username||'');username.required=true;username.pattern='[a-z0-9._-]{3,64}';const email=input(form,'البريد الإلكتروني لإشعارات الموافقة','email','email',u.email||'');
   const role=node('select');role.name='role';Object.entries(roles).forEach(([value,label])=>{const option=node('option',label);option.value=value;role.append(option);});role.value=u.role||'requester';const roleLabel=node('label','الوظيفة الأساسية');roleLabel.append(role);form.append(roleLabel);
   const departmentLabel=node('label','القسم'),department=node('select');department.name='departmentId';department.id='userDepartmentId';const none=node('option','اختر القسم');none.value='';department.append(none);for(const d of adminData.departments.filter(d=>d.active||d.id===u.departmentId)){const option=node('option',d.name+(d.active?'':' — غير نشط'));option.value=d.id;department.append(option);}department.value=u.departmentId||adminData.departments.find(d=>d.kind==='general'&&d.active)?.id||'';department.required=true;departmentLabel.append(department);form.append(departmentLabel);
   const inline=node('button','+ إضافة قسم جديد');inline.type='button';inline.id='addDepartmentInline';form.append(inline);const help=node('p');help.className='role-description';help.id='userRoleDescription';form.append(help);
   const password=input(form,u.id?'كلمة مرور جديدة (اختياري؛ تُنهي جلسات المستخدم)':'كلمة المرور (12 حرفًا على الأقل)','password','password',u._password||'');password.minLength=12;password.required=!u.id;
   const active=input(form,'الحساب نشط','active','checkbox');active.checked=u.active!==false;
   const scopes=node('fieldset');
   scopes.className='user-company-scopes';
   scopes.append(node('legend','النماذج المسموح بها (مدير النظام يصل إلى جميع النماذج)'));
   const scopeControls=node('div');
   scopeControls.className='scope-controls';
   const selectAllLabel=node('label','تحديد جميع النماذج'),selectAll=node('input');
   selectAll.type='checkbox';
   selectAll.id='selectAllUserTemplates';
   selectAllLabel.prepend(selectAll);
   const scopeSummary=node('span');
   scopeSummary.id='userTemplateCount';
   scopeSummary.setAttribute('aria-live','polite');
   scopeControls.append(selectAllLabel,scopeSummary);
   scopes.append(scopeControls);
   const scopeInputs=[];
   const refreshScopeSelection=()=>{
    const selected=scopeInputs.filter(checkbox=>checkbox.checked).length;
    selectAll.checked=selected===scopeInputs.length&&selected>0;
    selectAll.indeterminate=selected>0&&selected<scopeInputs.length;
    selectAll.disabled=!scopeInputs.length;
    scopeSummary.textContent=selected.toLocaleString('ar-IQ')+' من '+scopeInputs.length.toLocaleString('ar-IQ')+' نموذج محدد';
   };
   for(const template of templates){
    const label=node('label',template.name),checkbox=node('input');
    checkbox.type='checkbox';
    checkbox.value=template.id;
    checkbox.name='company';
    checkbox.checked=(u.scopes||[]).includes(template.id);
    checkbox.onchange=refreshScopeSelection;
    label.prepend(checkbox);
    scopeInputs.push(checkbox);
    scopes.append(label);
   }
   selectAll.onchange=()=>{
    for(const checkbox of scopeInputs)checkbox.checked=selectAll.checked;
    refreshScopeSelection();
   };
   refreshScopeSelection();
   form.append(scopes);
   const permissionSection=node('section');permissionSection.className='user-permission-section';permissionSection.append(node('h3','صلاحيات هذا الموظف بالتفصيل'),node('p','صلاحيات طلبات الشراء مستقلة عن الصادر والوارد. فعّل صلاحية الدخول لكل نظام، ثم امنح صلاحيات إجراءاته. اختر الافتراضي أو السماح أو المنع لكل صلاحية.'));const reset=node('button','إعادة الصلاحيات إلى الافتراضي');reset.type='button';reset.id='resetUserPermissions';permissionSection.append(reset);const permissionGroups=new Map();const permissionSummary=node('p');permissionSummary.id='permissionSummary';permissionSummary.setAttribute('aria-live','polite');permissionSection.append(permissionSummary);const overrides=u.permissionOverrides||{};const permissionSelects={};
   const catalog=adminData.catalog.permissions?.length?adminData.catalog.permissions:Object.keys(fallbackLabels).map(key=>({key,label:fallbackLabels[key],group:'الطلبات'}));
   for(const permission of catalog){const label=node('label',permission.label||fallbackLabels[permission.key]||permission.key);label.className='permission-choice';const select=node('select');select.dataset.permission=permission.key;select.name='permission-'+permission.key;for(const [value,text]of [['inherit','الافتراضي حسب الوظيفة والقسم'],['allow','مسموح لهذا الموظف'],['deny','ممنوع لهذا الموظف']]){const option=node('option',text);option.value=value;select.append(option);}select.value=Object.hasOwn(overrides,permission.key)?overrides[permission.key]?'allow':'deny':'inherit';const current=node('small');current.className='permission-current';label.append(select,current);const group=permission.group||'طلبات الشراء';if(!permissionGroups.has(group)){const section=node('div');section.className='permission-group';const grid=node('div');grid.className='permission-grid';section.append(node('h4',group),grid);permissionSection.append(section);permissionGroups.set(group,grid);}permissionGroups.get(group).append(label);permissionSelects[permission.key]=select;}
   form.append(permissionSection);const updateSummary=()=>{const selections=Object.values(permissionSelects);permissionSummary.textContent=role.value==='admin'?'جميع الصلاحيات مفعّلة لمدير النظام.':'ممنوحة صراحة: '+selections.filter(s=>s.value==='allow').length.toLocaleString('ar-IQ')+' · ممنوعة صراحة: '+selections.filter(s=>s.value==='deny').length.toLocaleString('ar-IQ');};for(const select of Object.values(permissionSelects))select.onchange=updateSummary;
   const updateRole=()=>{help.textContent=descriptions[role.value]||'';const selected=adminData.departments.find(d=>d.id===department.value);if(selected&&adminData.workflowPlan?.departmentApproval!==false){const manager=adminData.users.find(person=>person.id===selected.managerId&&person.active);help.textContent+=manager?' تُرسل طلبات الموظف أولًا إلى مدير القسم: '+manager.name+'.':' لم يُعيّن مدير لهذا القسم بعد.';}if(['purchasing','finance'].includes(selected?.kind))help.textContent+=' أعضاء هذا القسم يتلقّون الطلب ضمن قائمة مشتركة، ويكفي إجراء أحد الأعضاء المخوّلين.';for(const [key,select]of Object.entries(permissionSelects)){select.disabled=role.value==='admin';const current=select.nextElementSibling;if(role.value==='admin')current.textContent='صلاحية كاملة لمدير النظام';else if(role.value===u.role&&department.value===u.departmentId&&typeof u.permissions?.[key]==='boolean')current.textContent=u.permissions[key]?'الوضع المحفوظ حاليًا: مسموح':'الوضع المحفوظ حاليًا: ممنوع';else current.textContent='يُحسب الافتراضي من الوظيفة والقسم عند الحفظ';}reset.disabled=role.value==='admin';updateSummary();};role.onchange=updateRole;department.onchange=updateRole;reset.onclick=()=>{Object.values(permissionSelects).forEach(select=>select.value='inherit');updateRole();};updateRole();
   const readOverrides=()=>Object.fromEntries(Object.entries(permissionSelects).filter(([,select])=>select.value!=='inherit').map(([key,select])=>[key,select.value==='allow']));
   const draft=()=>({...u,name:name.value,username:username.value,email:email.value,role:role.value,departmentId:department.value,active:active.checked,scopes:scopeInputs.filter(checkbox=>checkbox.checked).map(checkbox=>checkbox.value),permissionOverrides:readOverrides(),_password:password.value});
   inline.onclick=()=>{const snapshot=draft();editDepartment({kind:'general',active:true,members:[]},saved=>editUser({...snapshot,departmentId:saved.id}),()=>editUser(snapshot));};
   const save=node('button','حفظ المستخدم');save.className='primary';save.id='saveUser';form.append(save);form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{const data=draft();await api('/api/users',{id:u.id,name:data.name,username:data.username,email:data.email,role:data.role,departmentId:data.departmentId,password:data._password,active:data.active,scopes:data.scopes,permissions:role.value==='admin'?{}:data.permissionOverrides});if(u.id===user.id)location.reload();else{await refreshRouting();await showUsers();}}catch(e){error(form,e.message);}finally{save.disabled=false;}};
  }catch(e){content.replaceChildren();error(content,e.message);}}
  async function showDepartments(){const content=open('إدارة الأقسام ومديريها وأعضائها');content.append(node('p','جارٍ تحميل الأقسام…'));try{await refreshAdminData();if(!content.isConnected)return;content.replaceChildren();const add=node('button','+ قسم جديد');add.className='primary';add.id='addDepartment';add.onclick=()=>editDepartment({kind:'general',active:true,members:[]});content.append(add,node('p','يرتبط الموظف بقسم أساسي واحد. يوافق مدير القسم على طلبات أعضائه تلقائيًا. أما المشتريات والمالية فتعملان بقائمة مشتركة يستطيع أي عضو مخوّل تنفيذ إجراءها.'));
   for(const [index,d]of [...adminData.departments].sort((a,b)=>(a.sortOrder??Number.MAX_SAFE_INTEGER)-(b.sortOrder??Number.MAX_SAFE_INTEGER)).entries()){const row=node('div');row.className='team-user-row department-row';row.dataset.departmentId=d.id;const manager=adminData.users.find(u=>u.id===d.managerId);const info=node('div'),title=node('div');title.className='department-title';const order=node('span',(index+1).toLocaleString('ar-IQ'));order.className='department-order';title.append(order,node('strong',d.name));info.append(title,node('p',(departmentKinds[d.kind]||d.kind)+' · '+(d.active?'نشط':'غير نشط')+' · '+(d.members||[]).length.toLocaleString('ar-IQ')+' عضو'),node('p','مدير القسم: '+(manager?.name||'لم يُحدد')));const edit=node('button','تعديل القسم والأعضاء');edit.onclick=()=>editDepartment(d);row.append(info,edit);content.append(row);}if(!adminData.departments.length)content.append(node('p','أضف القسم الأول.'));
  }catch(e){content.replaceChildren();error(content,e.message);}}
  async function editDepartment(d={kind:'general',active:true,members:[]},onSaved,onCancel){const content=open(d.id?'تعديل القسم ومديره وأعضائه':'إضافة قسم جديد',onCancel);content.append(node('p','جارٍ تحميل الموظفين…'));try{await refreshAdminData();if(!content.isConnected)return;content.replaceChildren();const form=node('form');form.id='departmentForm';content.append(form);const name=input(form,'اسم القسم','name','text',d.name||'');name.id='departmentName';name.required=true;name.maxLength=120;
   const kindLabel=node('label','نوع القسم'),kind=node('select');kind.name='kind';kind.id='departmentKind';for(const [value,text]of Object.entries(departmentKinds)){const option=node('option',text);option.value=value;kind.append(option);}kind.value=d.kind||'general';kindLabel.append(kind);form.append(kindLabel);const explain=node('p');explain.className='role-description';form.append(explain);kind.onchange=()=>{explain.textContent=kind.value==='general'?'طلبات أعضاء هذا القسم تُعرض تلقائيًا على مديره للموافقة. حدّد المدير قبل إرسال الطلبات.':['purchasing','finance'].includes(kind.value)?'تصل الطلبات إلى قائمة مشتركة لكل أعضاء القسم المخوّلين. يكفي تنفيذ الإجراء من عضو واحد، ويُسجّل اسمه.':'يشارك الأعضاء المخوّلون في تجهيز الطلبات وتسليمها.';};kind.onchange();
   const managerLabel=node('label','مدير القسم — اختر من الأعضاء المحددين'),manager=node('select');manager.name='managerId';manager.id='departmentManager';managerLabel.append(manager);form.append(managerLabel);
   const active=input(form,'القسم نشط','active','checkbox');active.checked=d.active!==false;
   const members=node('fieldset');members.id='departmentMembers';members.className='department-members';members.append(node('legend','أعضاء القسم'));form.append(node('p','حدّد الأعضاء أولًا، ثم اختر مديرًا نشطًا منهم. تصل إليه طلبات هذا القسم تلقائيًا. تحديد موظف من قسم آخر ينقل عضويته عند الحفظ.'));const selected=new Set(d.members||[]);const syncManagers=(preferred=manager.value)=>{manager.replaceChildren();const empty=node('option','لم يُحدد مدير بعد');empty.value='';manager.append(empty);const ids=new Set([...members.querySelectorAll('input:checked')].map(input=>input.value));for(const u of adminData.users.filter(u=>ids.has(u.id)&&u.active&&(u.role==='admin'||u.permissionOverrides?.approveDepartment!==false))){const o=node('option',u.name+' · '+roles[u.role]);o.value=u.id;manager.append(o);}if(preferred&&![...manager.options].some(o=>o.value===preferred)){const o=node('option','المدير الحالي غير مؤهل — اختر بديلًا');o.value=preferred;o.disabled=true;manager.append(o);}manager.value=preferred;};for(const u of adminData.users){const label=node('label'),checkbox=node('input');checkbox.type='checkbox';checkbox.name='member';checkbox.value=u.id;checkbox.checked=selected.has(u.id);const text=node('span',u.name+' · '+departmentName(u.departmentId)+(u.active?'':' · معطّل'));label.append(checkbox,text);members.append(label);checkbox.onchange=()=>syncManagers(!checkbox.checked&&manager.value===u.id?'':manager.value);}form.append(members);syncManagers(d.managerId||'');
   const actions=node('div');actions.className='actions';const save=node('button','حفظ القسم');save.id='saveDepartment';save.className='primary';actions.append(save);if(onCancel){const back=node('button','العودة إلى الحساب');back.type='button';back.onclick=onCancel;actions.append(back);}form.append(actions);form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{const result=await api('/api/departments',{id:d.id,version:d.version,name:name.value,kind:kind.value,managerId:manager.value,active:active.checked,members:[...members.querySelectorAll('input:checked')].map(checkbox=>checkbox.value)});await refreshRouting();if(onSaved)await onSaved(result.department);else await showDepartments();}catch(e){error(form,e.message);}finally{save.disabled=false;}};
   if(d.id){const deletion=node('details');deletion.className='department-delete-panel';deletion.id='departmentDeletePanel';deletion.append(node('summary','حذف هذا القسم'));deletion.append(node('p','عند حذف قسم مرتبط بحسابات أو طلبات، تُنقل الحسابات والطلبات المرتبطة إلى القسم البديل. يحتفظ النظام بسجل الإجراءات السابقة.'));const replacementLabel=node('label','القسم البديل للارتباطات'),replacement=node('select');replacement.id='deleteDepartmentReplacement';const empty=node('option','بدون بديل — للقسم غير المرتبط فقط');empty.value='';replacement.append(empty);for(const department of adminData.departments.filter(department=>department.id!==d.id&&department.active)){const option=node('option',department.name);option.value=department.id;replacement.append(option);}replacementLabel.append(replacement);deletion.append(replacementLabel);const remove=node('button','حذف القسم');remove.type='button';remove.className='danger';remove.id='deleteDepartmentButton';const feedback=node('p');feedback.setAttribute('role','status');deletion.append(feedback,remove);content.append(deletion);
    remove.onclick=async()=>{if((d.members||[]).length&&!replacement.value){feedback.textContent='اختر قسمًا بديلًا لنقل أعضاء القسم إليه.';replacement.focus();return;}const selected=adminData.departments.find(department=>department.id===replacement.value);const prompt=selected?'حذف «'+d.name+'» ونقل الحسابات والطلبات المرتبطة إلى «'+selected.name+'»؟':'حذف «'+d.name+'»؟ إذا كان مرتبطًا بحسابات أو طلبات فسيطلب النظام قسمًا بديلًا.';if(!confirm(prompt))return;remove.disabled=true;feedback.textContent='جارٍ حذف القسم وتحديث الارتباطات…';try{await api('/api/departments/delete',{id:d.id,version:d.version,replacementId:replacement.value});await refreshRouting();await showDepartments();}catch(e){feedback.textContent=e.message;remove.disabled=false;}};
   }
  }catch(e){content.replaceChildren();error(content,e.message);}}
  departmentsButton.onclick=showDepartments;
  accounts.onclick=showUsers;
  if(new URLSearchParams(location.search).get('accounts')==='1')setTimeout(showUsers,0);
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
