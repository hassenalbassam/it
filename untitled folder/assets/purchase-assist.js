(() => {
 'use strict';
 const q=selector=>document.querySelector(selector);
 const node=(tag,text)=>{
  const element=document.createElement(tag);
  if(text!==undefined)element.textContent=text;
  return element;
 };
 const api=async(path,data,raw=false)=>{
  const response=await fetch(path,{method:data===undefined?'GET':'POST',headers:{'X-Workspace-Token':window.WORKSPACE_TOKEN,...(raw?{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}:data===undefined?{}:{'Content-Type':'application/json'})},...(data===undefined?{}:{body:raw?data:JSON.stringify(data)})});
  if(!response.ok){const result=await response.json();throw Error(result.error||'تعذر قراءة مرجع الطلبات.');}
  return response.json();
 };
 let status={configured:false},ready=false,numberTicket=0;
 const formYear=()=>{
  const date=ShamaraTracking.dateISO(f().date);
  return date?Number(date.slice(0,4)):new Date().getFullYear();
 };
 const draft=()=>{
  state.draftTracking=state.draftTracking||{};
  return state.draftTracking[state.selected]||(state.draftTracking[state.selected]={});
 };
 const assistance=(query='',sources=false)=>api('/api/purchase-assist?'+new URLSearchParams({company:state.selected,year:formYear(),q:query,...(sources?{sources:'1'}:{})}));
 const dialog=node('dialog');
 dialog.id='purchaseReferenceDialog';
 document.body.append(dialog);
 function openDialog(title){
  dialog.replaceChildren();
  const head=node('div'),close=node('button','×');
  head.className='dialog-heading';
  close.type='button';
  close.setAttribute('aria-label','إغلاق');
  close.onclick=()=>dialog.close();
  head.append(node('h2',title),close);
  const content=node('div');
  dialog.append(head,content);
  if(!dialog.open)dialog.showModal();
  return content;
 }
 async function chooseSource(){
  const content=openDialog('اختيار رقم العدد من Excel');
  const search=node('input');
  search.type='search';
  search.placeholder='رقم العدد، التفاصيل أو الجهة';
  search.setAttribute('aria-label','البحث في مرجع Excel');
  const list=node('div'),message=node('p');
  message.className='note';
  content.append(search,message,list);
  let ticket=0,timer;
  const draw=async()=>{
   const current=++ticket;
   message.textContent='جارٍ البحث…';
   try{
    const data=await assistance(search.value,true);
    if(current!==ticket||!content.isConnected)return;
    list.replaceChildren();
    message.textContent=data.sources.length?'الأعداد من سنة '+formYear()+'. يظهر سطر Excel لتمييز الأعداد المكررة.':'لا توجد طلبات شراء متاحة لهذا البحث ضمن النموذج والسنة.';
    for(const source of data.sources){
     const row=node('article');
     row.className='purchase-source-row';
     row.append(node('strong','العدد '+source.number+' · '+source.toDepartment),node('p',source.details||'لا توجد تفاصيل'),node('small',(source.requester||'')+' · '+source.date+' · '+source.sheet+'!A'+source.row));
     const use=node('button','استخدام العدد والتفاصيل');
     use.type='button';
     use.onclick=()=>{
      const tracking=draft();
      tracking.numberMode='excel';
      tracking.sourceKey=source.key;
      f().number=source.number;
      if(f().rows.every(row=>row.every(value=>!value.trim()))&&source.materials.length)f().rows=source.materials.map(name=>[name,'','','','','']);
      save();
      editor();
      preview();
      dialog.close();
     };
     row.append(use);
     list.append(row);
    }
   }catch(error){if(current===ticket)message.textContent=error.message;}
  };
  search.oninput=()=>{clearTimeout(timer);timer=setTimeout(draw,200);};
  await draw();
  search.focus();
 }
 async function manageReference(){
  const content=openDialog('مرجع أعداد الطلبات والمواد');
  const summary=node('p');
  summary.className='note';
  content.append(summary);
  const draw=()=>{
   summary.textContent=status.configured?'طلبات الشراء في المرجع '+status.rows.toLocaleString('ar-IQ')+' · عبارات المواد '+status.materials.toLocaleString('ar-IQ')+' · آخر تحديث '+new Date(status.updatedAt).toLocaleString('ar-IQ',{timeZone:'Asia/Baghdad'}):'اختر ملف Excel الذي يتضمن رقم العدد وعنوان الطلب والتفاصيل.';
   if(status.configured&&status.duplicates?.length)summary.append(' · توجد أعداد مكررة في المصدر، ويُميز الاختيار بسطر Excel.');
  };
  draw();
  const file=node('input');
  file.type='file';
  file.accept='.xlsx';
  file.setAttribute('aria-label','تحديث مرجع Excel');
  const feedback=node('p');
  feedback.setAttribute('role','status');
  content.append(file,feedback);
  file.onchange=async()=>{
   if(!file.files[0])return;
   file.disabled=true;
   feedback.textContent='جارٍ قراءة الأعداد والتفاصيل…';
   try{
    status=await api('/api/purchase-reference/import',await file.files[0].arrayBuffer(),true);
    draw();
    feedback.textContent='تم تحديث المرجع. ستستفيد الطلبات الجديدة من الأعداد والمواد.';
    attachNumbering();
   }catch(error){feedback.textContent=error.message;}
   finally{file.disabled=false;}
  };
 }
 async function attachNumbering(){
  if(!ready||!ShamaraTracking.canCreate()&&!ShamaraTracking.canEdit({createdBy:window.CURRENT_USER.id,tracking:{status:'draft'}}))return;
  let panel=q('#purchaseNumberAssistant');
  if(!panel){
   panel=node('section');
   panel.id='purchaseNumberAssistant';
   panel.className='card purchase-number-assistant';
   q('#requestTrackingCard').before(panel);
  }
  panel.replaceChildren(node('h2','رقم الطلب واقتراحات المواد'));
  const message=node('p');
  message.className='note';
  panel.append(message);
  if(window.CURRENT_USER.role==='admin'){
   const manage=node('button','تحديث مرجع Excel');
   manage.type='button';
   manage.id='managePurchaseReference';
   manage.onclick=manageReference;
   panel.append(manage);
  }
  const number=q('#field-number');
  if(!status.configured){message.textContent='تتعلم اقتراحات المواد من الطلبات المحفوظة. يمكن لمدير النظام تحميل مرجع Excel للأعداد والتفاصيل.';return;}
  const existing=state.editSession&&ShamaraTracking.all().find(item=>item.id===state.editSession.id);
  if(existing){
   message.textContent='العدد المحفوظ '+existing.form.number+' · اقتراحات المواد من مرجع Excel والطلبات المحفوظة.';
   number.readOnly=existing.tracking?.numberMode==='assigned'||Boolean(existing.tracking?.sourceKey);
   return;
  }
  const tracking=draft();
  tracking.numberMode=tracking.numberMode||'auto';
  const mode=node('select');
  mode.id='purchaseNumberMode';
  mode.setAttribute('aria-label','طريقة اختيار رقم الطلب');
  const options=[['auto','رقم جديد متسلسل'],['excel','عدد موجود في Excel'],['manual','إدخال الرقم يدويًا']];
  if(tracking.numberMode==='assigned')options.push(['assigned','العدد المحفوظ']);
  for(const [value,label]of options){
   const option=node('option',label);
   option.value=value;
   if(value==='assigned')option.disabled=true;
   mode.append(option);
  }
  mode.value=tracking.numberMode;
  panel.append(mode);
  const choose=node('button','اختيار طلب شراء من Excel');
  choose.type='button';
  choose.id='choosePurchaseSource';
  choose.hidden=tracking.numberMode!=='excel';
  choose.onclick=chooseSource;
  panel.append(choose);
  mode.onchange=()=>{
   const next=draft();
   next.numberMode=mode.value;
   delete next.sourceKey;
   save();
   attachNumbering();
   if(mode.value==='excel')chooseSource();
  };
  number.readOnly=tracking.numberMode!=='manual';
  message.textContent=tracking.numberMode==='assigned'?'هذا عدد الطلب الذي حُفظ. استخدم «طلب جديد» لبدء طلب آخر.':tracking.numberMode==='excel'?'يُستخدم رقم العدد من السطر الذي تختاره. التفاصيل تقترح المواد عند خلو جدول المواد.':'يقترح النظام مواد من تفاصيل Excel ومن إدخالاتك المحفوظة.';
  if(tracking.numberMode==='auto'){
   const ticket=++numberTicket,company=state.selected,year=formYear();
   try{
    const result=await assistance();
    if(ticket!==numberTicket||company!==state.selected||year!==formYear()||draft().numberMode!=='auto'||state.editSession)return;
    f().number=result.nextNumber;
    number.value=result.nextNumber;
    message.textContent='العدد المقترح '+result.nextNumber+' لسنة '+year+'. يُثبت الرقم عند الحفظ حسب تسلسل مرجع Excel.';
    preview();
   }catch(error){message.textContent=error.message;}
  }
  q('#field-date')?.addEventListener('change',attachNumbering,{once:true});
 }
 function attachMaterials(){
  if(!q('#purchaseMaterialHint')){const hint=node('p','اكتب اسم المادة لعرض اقتراحات من Excel والطلبات المحفوظة. تُقترح المواصفات والمنشأ، وتبقى الكمية لكل طلب.');hint.id='purchaseMaterialHint';hint.className='note';q('#step-items .bar')?.after(hint);}
  document.querySelectorAll('datalist[data-purchase-materials]').forEach(list=>list.remove());
  q('#rows')?.querySelectorAll('tr').forEach((row,index)=>{
   const inputs=[...row.querySelectorAll('input')];
   const input=inputs[0];
   if(!input)return;
   const list=node('datalist');
   list.id='purchaseMaterialChoices'+index;
   list.dataset.purchaseMaterials='1';
   document.body.append(list);
   input.setAttribute('list',list.id);
   input.autocomplete='off';
   input.placeholder='اكتب اسم المادة للاقتراحات';
   input.setAttribute('aria-describedby','purchaseMaterialHint');
   let values=[],ticket=0,timer;
   const search=async()=>{
    if(!ready||!input.isConnected)return;
    const current=++ticket;
    try{
     const result=await assistance(input.value);
     if(current!==ticket||!input.isConnected)return;
     values=result.items;
     list.replaceChildren();
     for(const item of values){
      const option=node('option');
      option.value=item.name;
      option.label=(item.source==='excel'?'من تفاصيل Excel':'من الطلبات المحفوظة')+' · '+item.uses.toLocaleString('ar-IQ')+' استخدام';
      list.append(option);
     }
    }catch(_){list.replaceChildren();}
   };
   input.addEventListener('focus',search);
   input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(search,180);});
   input.addEventListener('change',()=>{
    const item=values.find(item=>item.name===input.value);
    if(!item)return;
    for(const [position,value]of [[1,item.origin],[2,item.specifications]]){
     if(value&&!inputs[position].value.trim()){
      inputs[position].value=value;
      inputs[position].dispatchEvent(new Event('input',{bubbles:true}));
     }
    }
   });
  });
 }
 const originalRows=rows;
 rows=function(){originalRows();attachMaterials();};
 const originalEditor=editor;
 editor=function(){originalEditor();attachNumbering();};
 window.addEventListener('shamara-ready',async()=>{
  try{status=await api('/api/purchase-reference/status');}
  catch(_){status={configured:false};}
  ready=true;
  attachNumbering();
  attachMaterials();
 },{once:true});
 window.addEventListener('shamara-request-saved',event=>{
  const {company,id}=event.detail;
  const saved=ShamaraTracking.all().find(item=>item.id===id);
  if(company!==state.selected||saved?.tracking?.numberMode!=='assigned')return;
  f().number=saved.form.number;
  Object.assign(draft(),{numberMode:'assigned',sourceKey:saved.tracking.sourceKey||''});
  q('#field-number').value=saved.form.number;
  save();
  attachNumbering();
  preview();
 });
})();
