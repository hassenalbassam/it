"""Central SQLite store, authentication, and server-enforced purchase approvals."""
import sqlite3, json, secrets, hashlib, hmac, time, re, copy
from decimal import Decimal, InvalidOperation
from pathlib import Path
from datetime import datetime, timezone

ROLES = {'admin','requester','approver','buyer','warehouse','finance','viewer'}
STATUSES = {'draft','submitted','approved','finance_pending','stock_check','fulfillment','ordered','awaiting_receipt','received','closed','closed','rejected','cancelled'}
ROUTE_ROLES={'deptApproverId':{'approver','admin'},'buyerId':{'buyer','admin'},'financeApproverId':{'finance','admin'},'warehouseId':{'warehouse','admin'}}
SERVER_TRACKING={'assigneeId','assigneeName','manualAssigneeId','requestDepartmentId','fulfillmentQueue','workflowPlan'}
CORRESPONDENCE_PERMISSIONS={'viewCorrespondence':'الدخول وعرض سجل الصادر والوارد','createCorrespondence':'إضافة قيود الصادر والوارد','editCorrespondence':'تعديل قيود الصادر والوارد','deleteCorrespondence':'حذف قيود الصادر والوارد','exportCorrespondence':'تصدير سجلات الصادر والوارد إلى Excel'}
PERMISSIONS={'accessPurchases':'الدخول إلى طلبات الشراء','createRequest':'إنشاء طلب','editOwnRequest':'تعديل طلباتي','editAnyRequest':'تعديل جميع الطلبات','deleteRequest':'حذف الطلب','submitRequest':'تقديم الطلب','approveDepartment':'موافقة رئيس القسم','priceRequest':'تسعير المشتريات','approveFinance':'الموافقة المالية','checkStock':'التحقق من توفر المواد في المخازن','prepareRequest':'تجهيز المواد','deliverRequest':'تسليم المواد','viewCompanyRequests':'عرض طلبات الشركات','previewRequest':'معاينة المستند وطباعته','auditRequests':'تدقيق الطلبات — عرض سجل الإجراءات','exportExcel':'تصدير Excel','importExcel':'استيراد Excel'}
PERMISSIONS.update(CORRESPONDENCE_PERMISSIONS)
ROLE_GRANTS={'admin':set(PERMISSIONS),'requester':{'createRequest','editOwnRequest','deleteRequest','submitRequest','exportExcel','importExcel'},'approver':{'approveDepartment','viewCompanyRequests','exportExcel','importExcel'},'buyer':{'priceRequest','prepareRequest','deliverRequest','viewCompanyRequests','exportExcel','importExcel'},'finance':{'approveFinance','viewCompanyRequests','exportExcel','importExcel'},'warehouse':{'checkStock','prepareRequest','deliverRequest','viewCompanyRequests','exportExcel','importExcel'},'viewer':{'viewCompanyRequests','exportExcel'}}
for grants in ROLE_GRANTS.values():grants.update({'previewRequest','accessPurchases'})
DEPARTMENT_GRANTS={'general':set(),'purchasing':{'priceRequest','prepareRequest','deliverRequest','viewCompanyRequests','exportExcel','importExcel'},'finance':{'approveFinance','viewCompanyRequests','exportExcel','importExcel'},'warehouse':{'checkStock','prepareRequest','deliverRequest','viewCompanyRequests','exportExcel','importExcel'}}
STAGE_PERMISSION={'submitted':'approveDepartment','approved':'priceRequest','finance_pending':'approveFinance','stock_check':'checkStock','fulfillment':'prepareRequest','ordered':'deliverRequest'}
WORKFLOW_ACTIONS={
 'submit':({'draft','rejected'},'submitted'),
 'approve':({'submitted'},'approved'),
 'reject':({'submitted','finance_pending'},'rejected'),
 'priced':({'approved'},'finance_pending'),
 'finance_approve':({'finance_pending'},'stock_check'),
 'stock_available':({'stock_check'},'fulfillment'),
 'stock_unavailable':({'stock_check'},'fulfillment'),
 'ready':({'fulfillment'},'ordered'),
 'deliver':({'ordered'},'awaiting_receipt'),
 'confirm_receipt':({'awaiting_receipt'},'received'),
 'cancel':({'draft','rejected','submitted'},'cancelled'),
}
DEFAULT_STAGE_ORDER=('departmentApproval','purchasePricing','financeApproval','warehouseCheck','preparation','readyForDelivery','receiptConfirmation')
DEFAULT_WORKFLOW_PLAN={
 'version':1,'requestCreation':True,'departmentApproval':True,'purchasePricing':True,
 'financeApproval':True,'warehouseCheck':True,'preparation':True,'readyForDelivery':True,
 'receiptConfirmation':True,'completion':True,'stageOrder':list(DEFAULT_STAGE_ORDER),
}
WORKFLOW_OPTIONS=tuple(key for key in DEFAULT_WORKFLOW_PLAN if key not in {'version','stageOrder'})
WORKFLOW_STAGE_OPTIONS=(
 ('submitted','departmentApproval'),('approved','purchasePricing'),
 ('finance_pending','financeApproval'),('stock_check','warehouseCheck'),
 ('fulfillment','preparation'),('ordered','readyForDelivery'),
 ('awaiting_receipt','receiptConfirmation'),
)
STOCK_DESTINATIONS={'stock_available':'warehouse','stock_unavailable':'purchasing'}
WORKFLOW_ACTION_LABELS={
 'stock_available':'أكدت المخازن توفر المواد',
 'stock_unavailable':'المواد غير متوفرة في المخازن · تحويل إلى المشتريات',
 'deliver':'تسجيل تسليم المواد إلى مقدم الطلب',
 'confirm_receipt':'تأكيد الاستلام من مقدم الطلب',
}
INBOX_ACTIONS={
 'submitted':('مطلوب قرار مدير القسم','راجع الطلب واختر الموافقة أو الرفض.'),
 'approved':('مطلوب تسعير الطلب','أدخل المورد والسعر ثم اعتمد التسعير للانتقال إلى المرحلة التالية.'),
 'finance_pending':('مطلوب قرار المالية','راجع التسعير واختر الموافقة على الصرف أو الرفض.'),
 'stock_check':('مطلوب التحقق من توفر المواد','اختر «متوفر في المخازن» للتجهيز أو «غير متوفر في المخازن» للتحويل إلى المشتريات.'),
 'fulfillment':('مطلوب تجهيز الطلب','جهّز المواد ثم أكّد اكتمال التجهيز للانتقال إلى المرحلة التالية.'),
 'ordered':('مطلوب تسليم الطلب','سلّم المواد إلى مقدم الطلب ثم سجّل التسليم.'),
 'awaiting_receipt':('مطلوب تأكيد استلام طلبك','بعد استلام المواد فعليًا، افتح الطلب واضغط «استلمت الطلب» لإغلاقه.'),
}
INBOX_RESULTS={
 'approved':('تمت الموافقة على طلبك','انتقل الطلب إلى المشتريات للتسعير.'),
 'finance_pending':('اكتمل تسعير طلبك','انتقل الطلب إلى المالية لاتخاذ قرار الصرف.'),
 'stock_check':('وافقت المالية على طلبك','انتقل الطلب إلى المخازن للتحقق من توفر المواد.'),
 'fulfillment':('بدأ تجهيز طلبك','انتقل الطلب إلى قسم التجهيز.'),
 'ordered':('طلبك جاهز للتسليم','اكتمل تجهيز المواد. سيُشعرك الداشبورد بعد تسجيل التسليم لتأكيد الاستلام.'),
 'received':('اكتمل طلبك','اكتملت المراحل المختارة في خطة الطلب.'),
 'closed':('انتهت خطة طلبك','انتهت المراحل المختارة وأُغلق الطلب.'),
 'rejected':('رُفض طلبك','راجع الملاحظات وعدّل الطلب قبل إعادة تقديمه.'),
 'cancelled':('أُلغي طلبك','يمكنك فتح الطلب لمراجعة حالته.'),
}
class Denied(ValueError): pass
class Conflict(ValueError): pass
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def dumps(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def semantic(r): return {'company':r['company'],'form':r['form'],'tracking':r.get('tracking',{})}
def digest(r): return hashlib.sha256(dumps(semantic(r)).encode()).hexdigest()

class Store:
 def __init__(self,folder,companies):
  self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True);self.path=self.folder/'team.sqlite3';self.companies=companies
  with self.connect() as db:
   db.executescript('''
    CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,name TEXT NOT NULL,role TEXT NOT NULL,scopes TEXT NOT NULL,password TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS departments(id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,manager_id TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1,created TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL,csrf TEXT NOT NULL,expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,company TEXT NOT NULL,creator TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS prefs(user_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS views(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,created REAL NOT NULL,payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT NOT NULL,actor TEXT NOT NULL,actor_name TEXT NOT NULL,action TEXT NOT NULL,record_id TEXT,details TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS audit_record_sequence ON audit(record_id,seq);
    CREATE TABLE IF NOT EXISTS email_outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT UNIQUE NOT NULL,record_id TEXT NOT NULL,recipient_id TEXT NOT NULL,recipient_name TEXT NOT NULL,event TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,next_attempt_at REAL NOT NULL DEFAULT 0,last_error TEXT NOT NULL DEFAULT '',sent_at TEXT,locked_at REAL);
    CREATE INDEX IF NOT EXISTS outbox_pending ON email_outbox(status,next_attempt_at);
    CREATE INDEX IF NOT EXISTS outbox_recipient ON email_outbox(recipient_id,id);
    CREATE TABLE IF NOT EXISTS inbox_reads(user_id TEXT NOT NULL,item_id TEXT NOT NULL,PRIMARY KEY(user_id,item_id));
    CREATE TABLE IF NOT EXISTS preview_tasks(id TEXT PRIMARY KEY,record_id TEXT NOT NULL,recipient_id TEXT NOT NULL,sender_id TEXT NOT NULL,message TEXT NOT NULL,created_at TEXT NOT NULL,completed_at TEXT);
    CREATE UNIQUE INDEX IF NOT EXISTS preview_pending ON preview_tasks(record_id,recipient_id) WHERE completed_at IS NULL;
    CREATE INDEX IF NOT EXISTS preview_recipient ON preview_tasks(recipient_id);
    CREATE INDEX IF NOT EXISTS preview_sender ON preview_tasks(sender_id);
    CREATE TABLE IF NOT EXISTS purchase_reference_rows(source_key TEXT PRIMARY KEY,year INTEGER NOT NULL,number TEXT NOT NULL,company TEXT NOT NULL,payload TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX IF NOT EXISTS purchase_reference_company ON purchase_reference_rows(year,company,active);
    CREATE TABLE IF NOT EXISTS purchase_number_counters(year INTEGER PRIMARY KEY,value INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS purchase_source_bindings(record_id TEXT PRIMARY KEY,source_key TEXT UNIQUE NOT NULL);
    CREATE TABLE IF NOT EXISTS purchase_material_examples(source TEXT NOT NULL,source_id TEXT NOT NULL,position INTEGER NOT NULL,company TEXT NOT NULL,name TEXT NOT NULL,normalized TEXT NOT NULL,origin TEXT NOT NULL,specifications TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(source,source_id,position));
    CREATE INDEX IF NOT EXISTS purchase_material_company ON purchase_material_examples(company);
    CREATE TABLE IF NOT EXISTS correspondence(
     id TEXT PRIMARY KEY,direction TEXT NOT NULL,serial INTEGER NOT NULL,registered_on TEXT NOT NULL,
     agency TEXT NOT NULL,document_number TEXT NOT NULL,document_date TEXT NOT NULL,subject TEXT NOT NULL,notes TEXT NOT NULL,
     version INTEGER NOT NULL,created_by TEXT NOT NULL,created_by_name TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
     deleted INTEGER NOT NULL DEFAULT 0,UNIQUE(direction,serial)
    );
    CREATE INDEX IF NOT EXISTS correspondence_date ON correspondence(direction,deleted,registered_on);
    CREATE TABLE IF NOT EXISTS correspondence_counters(direction TEXT PRIMARY KEY,value INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS correspondence_number_sequences(direction TEXT PRIMARY KEY,number TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY,count INTEGER NOT NULL,since REAL NOT NULL);
   ''')
   if 'email' not in [row[1] for row in db.execute('PRAGMA table_info(users)')]:db.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''")
   for column,default in [('department_id',"''"),('permissions',"'{}'")]:
    if column not in [row[1] for row in db.execute('PRAGMA table_info(users)')]:db.execute('ALTER TABLE users ADD COLUMN '+column+' TEXT NOT NULL DEFAULT '+default)
   for column,definition in [('sort_order','INTEGER NOT NULL DEFAULT 0'),('deleted','INTEGER NOT NULL DEFAULT 0'),('redirect_id',"TEXT NOT NULL DEFAULT ''")]:
    if column not in [row[1] for row in db.execute('PRAGMA table_info(departments)')]:db.execute('ALTER TABLE departments ADD COLUMN '+column+' '+definition)
   self.seed_departments(db)
   self.seed_correspondence_numbers(db)
  self.path.chmod(0o600)
 def connect(self):
  db=sqlite3.connect(self.path,timeout=15);db.row_factory=sqlite3.Row;db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA foreign_keys=ON');return db
 def seed_departments(self,db):
  defaults=[('dept-general','قسم تكنولوجيا المعلومات','general'),('dept-commercial','القسم التجاري','general'),('dept-finance','قسم المالية','finance'),('dept-warehouse','قسم المخازن','warehouse'),('dept-accounting','قسم المحاسبة','general'),('dept-ard-alosod','أرض الأسود','general'),('dept-legal','القسم القانوني','general'),('dept-relations','قسم العلاقات','general'),('dept-purchasing','قسم المشتريات','purchasing')]
  if not db.execute("SELECT 1 FROM meta WHERE key='departments_catalog_v2'").fetchone():
   for order,(ident,name,kind) in enumerate(defaults,1):
    db.execute('INSERT OR IGNORE INTO departments(id,name,kind,sort_order,created) VALUES(?,?,?,?,?)',(ident,name,kind,order,now()))
    db.execute('UPDATE departments SET name=?,kind=?,sort_order=? WHERE id=? AND deleted=0',(name,kind,order,ident))
   db.execute("INSERT INTO meta(key,value) VALUES('departments_catalog_v2','1')")
  if not db.execute("SELECT 1 FROM meta WHERE key='departments_migrated'").fetchone():
   db.execute("UPDATE users SET department_id=CASE role WHEN 'buyer' THEN 'dept-purchasing' WHEN 'finance' THEN 'dept-finance' WHEN 'warehouse' THEN 'dept-warehouse' ELSE 'dept-general' END WHERE department_id=''")
   heads=db.execute("SELECT id FROM users WHERE role='approver' AND active=1 AND department_id='dept-general' ORDER BY created,id").fetchall()
   if len(heads)==1:db.execute("UPDATE departments SET manager_id=? WHERE id='dept-general' AND manager_id=''",(heads[0]['id'],))
   db.execute("INSERT INTO meta(key,value) VALUES('departments_migrated','1')")
 def resolve_department(self,db,ident):
  seen=set()
  while ident and ident not in seen:
   seen.add(ident);row=db.execute('SELECT * FROM departments WHERE id=?',(ident,)).fetchone()
   if not row:return None
   if not row['deleted']:return row
   ident=row['redirect_id']
  return None
 def permission_catalog(self):return {'permissions':[{'key':key,'label':label,'group':'سجل الصادر والوارد' if key in CORRESPONDENCE_PERMISSIONS else 'طلبات الشراء'} for key,label in PERMISSIONS.items()],'roleDefaults':{role:{key:key in grants for key in PERMISSIONS} for role,grants in ROLE_GRANTS.items()}}
 def has_permission(self,u,key):return u.get('role')=='admin' or bool(u.get('permissions',{}).get(key,False))
 def permission_overrides(self,value):
  if not isinstance(value,dict) or set(value)-set(PERMISSIONS) or any(not isinstance(v,bool) for v in value.values()):raise ValueError('الصلاحيات يجب أن تكون حقولاً معروفة بقيم نعم أو لا.')
  return value
 def public(self,u,db=None):
  if db is None:
   with self.connect() as db:return self.public(u,db)
  department=db.execute('SELECT * FROM departments WHERE id=?',(u['department_id'],)).fetchone();overrides=json.loads(u['permissions']);grants=set(ROLE_GRANTS.get(u['role'],set()))
  if department and department['active'] and not department['deleted']:
   if u['role']!='viewer':grants|=DEPARTMENT_GRANTS[department['kind']]
   if department['manager_id']==u['id']:grants.add('approveDepartment')
  effective={key:bool(overrides.get(key,key in grants)) for key in PERMISSIONS}
  if u['role']=='admin':effective={key:True for key in PERMISSIONS}
  return {k:u[k] for k in ['id','username','name','role','email']}|{'scopes':json.loads(u['scopes']),'active':bool(u['active']),'departmentId':u['department_id'],'departmentName':department['name'] if department else '', 'permissions':effective,'permissionOverrides':overrides}
 def audit(self,db,u,action,ident=None,details=None):db.execute('INSERT INTO audit(at,actor,actor_name,action,record_id,details) VALUES(?,?,?,?,?,?)',(now(),u['id'],u['name'],action,ident,dumps(details or {})))
 def configured(self):
  with self.connect() as db:return bool(db.execute('SELECT 1 FROM users LIMIT 1').fetchone())
 def touch_departments(self,db,idents):
  for ident in set(filter(None,idents)):
   db.execute('UPDATE departments SET version=version+1 WHERE id=?',(ident,))
   db.execute("UPDATE departments SET manager_id='' WHERE id=? AND manager_id<>'' AND NOT EXISTS(SELECT 1 FROM users WHERE users.id=departments.manager_id AND users.department_id=departments.id)",(ident,))
 def manage_department(self,u,data):
  if u['role']!='admin':raise Denied('إدارة الأقسام متاحة للمدير فقط.')
  if not isinstance(data,dict):raise ValueError('بيانات القسم غير صالحة.')
  ident=data.get('id') or 'dept-'+secrets.token_hex(10);name=str(data.get('name','')).strip();kind=data.get('kind','general')
  if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]{3,80}',ident) or not 1<=len(name)<=120 or kind not in DEPARTMENT_GRANTS:raise ValueError('تحقق من اسم القسم ونوعه.')
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE');u=self.current_actor(db,u)
   if u['role']!='admin':raise Denied('إدارة الأقسام متاحة للمدير فقط.')
   old=db.execute('SELECT * FROM departments WHERE id=?',(ident,)).fetchone()
   if old and old['deleted']:raise ValueError('القسم محذوف؛ أنشئ قسماً جديداً بدلاً منه.')
   if old and data.get('version')!=old['version']:raise Conflict('عُدّل القسم بواسطة مستخدم آخر. حدّث قائمة الأقسام أولاً.')
   previous=[r['id'] for r in db.execute('SELECT id FROM users WHERE department_id=?',(ident,))]
   members=data.get('members',previous);manager=data.get('managerId',old['manager_id'] if old else '');active=data.get('active',bool(old['active']) if old else True)
   if not isinstance(active,bool) or not isinstance(members,list) or any(not isinstance(x,str) for x in members) or len(set(members))!=len(members) or not isinstance(manager,str):raise ValueError('أعضاء القسم أو مديره غير صالحين.')
   rows={}
   for user_id in members:
    row=db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
    if not row:raise ValueError('أحد أعضاء القسم غير موجود.')
    rows[user_id]=row
   if manager:
    row=rows.get(manager)
    if row is None or not row['active']:raise ValueError('رئيس القسم يجب أن يكون عضواً نشطاً في القسم.')
    if row['role']!='admin' and json.loads(row['permissions']).get('approveDepartment') is False:raise ValueError('صلاحية موافقة رئيس القسم مرفوضة لهذا الموظف. عدّل صلاحياته أولاً.')
   sources={row['department_id'] for row in rows.values()}-{ident}
   order=old['sort_order'] if old else db.execute('SELECT COALESCE(MAX(sort_order),0)+1 FROM departments').fetchone()[0]
   db.execute('INSERT INTO departments(id,name,kind,manager_id,active,version,created) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,kind=excluded.kind,manager_id=excluded.manager_id,active=excluded.active,version=excluded.version',(ident,name,kind,manager,int(active),old['version']+1 if old else 1,old['created'] if old else now()))
   db.execute('UPDATE departments SET sort_order=? WHERE id=?',(order,ident))
   for user_id in set(previous)-set(members):db.execute("UPDATE users SET department_id='' WHERE id=?",(user_id,))
   for user_id in members:db.execute('UPDATE users SET department_id=? WHERE id=?',(ident,user_id))
   self.touch_departments(db,sources)
   for user_id in set(previous)|set(members):db.execute('DELETE FROM views WHERE user_id=?',(user_id,))
   self.audit(db,u,'تعديل قسم' if old else 'إنشاء قسم',details={'departmentId':ident,'name':name,'kind':kind,'managerId':manager,'members':members,'active':active})
   return self.department_public(db,db.execute('SELECT * FROM departments WHERE id=?',(ident,)).fetchone())
 def delete_department(self,u,ident,version,replacementId=''):
  if u['role']!='admin':raise Denied('حذف الأقسام متاح للمدير فقط.')
  if not isinstance(ident,str) or not isinstance(replacementId,str) or replacementId==ident:raise ValueError('القسم البديل غير صالح.')
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE');u=self.current_actor(db,u)
   if u['role']!='admin':raise Denied('حذف الأقسام متاح للمدير فقط.')
   old=db.execute('SELECT * FROM departments WHERE id=? AND deleted=0',(ident,)).fetchone()
   if not old:raise ValueError('القسم غير موجود أو محذوف.')
   if old['version']!=version:raise Conflict('عُدّل القسم؛ حدّث القائمة قبل الحذف.')
   replacement=db.execute('SELECT * FROM departments WHERE id=? AND active=1 AND deleted=0',(replacementId,)).fetchone() if replacementId else None
   if replacementId and replacement is None:raise ValueError('اختر قسماً بديلاً نشطاً.')
   members=[r['id'] for r in db.execute('SELECT id FROM users WHERE department_id=?',(ident,))];linked=0
   for row in db.execute('SELECT payload FROM records'):
    record=json.loads(row[0]);source=self.resolve_department(db,record.get('tracking',{}).get('requestDepartmentId',''))
    if (source and source['id']==ident) or (not record.get('tracking',{}).get('requestDepartmentId') and record.get('createdBy') in members):linked+=1
   if (members or linked) and not replacement:raise ValueError('القسم مرتبط بموظفين أو طلبات. اختر قسماً بديلاً للحفاظ على البيانات وسير الطلبات.')
   db.execute('UPDATE users SET department_id=? WHERE department_id=?',(replacementId,ident));db.execute("UPDATE departments SET active=0,deleted=1,redirect_id=?,manager_id='',version=version+1 WHERE id=?",(replacementId,ident))
   if replacement:self.touch_departments(db,[replacementId])
   for user_id in members:db.execute('DELETE FROM views WHERE user_id=?',(user_id,))
   self.audit(db,u,'حذف قسم مع حفظ المراجع التاريخية',details={'departmentId':ident,'name':old['name'],'replacementId':replacementId,'movedMembers':len(members),'linkedRequests':linked})
   return {'deleted':True,'id':ident,'replacementId':replacementId,'movedMembers':len(members),'linkedRequests':linked}
 def password(self,value):
  if not isinstance(value,str) or not 12<=len(value)<=256:raise ValueError('كلمة المرور يجب أن تكون بين 12 و256 حرفاً.')
  salt=secrets.token_hex(16);hashed=hashlib.scrypt(value.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1,dklen=32).hex();return salt+':'+hashed
 def verify(self,value,stored):
  salt,hashed=stored.split(':');return hmac.compare_digest(hashlib.scrypt(value.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1,dklen=32).hex(),hashed)
 def setup(self,data):
  encoded=self.password(data.get('password',''));username=str(data.get('username','')).strip().lower();name=str(data.get('name','')).strip()
  if not re.fullmatch(r'[a-z0-9._-]{3,64}',username) or not name:raise ValueError('أدخل اسماً واسم مستخدم إنجليزي من 3 أحرف على الأقل.')
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE')
   if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():raise Denied('تم إعداد المدير مسبقاً.')
   ident=secrets.token_hex(12);db.execute('INSERT INTO users(id,username,name,role,scopes,password,active,created,email,department_id,permissions) VALUES(?,?,?,?,?,?,1,?,?,?,?)',(ident,username,name,'admin','[]',encoded,now(),self.email(data.get('email','')),'dept-general','{}'));u=db.execute('SELECT * FROM users WHERE id=?',(ident,)).fetchone();self.audit(db,u,'إنشاء مدير النظام')
   legacy=self.folder/'workspace.json'
   if legacy.exists():
    previous=json.loads(legacy.read_text()).get('state') or {};records=previous.pop('archives',{})
    for company,rows in records.items():
     for record in rows:
      record=copy.deepcopy(record);record.update(createdBy=ident,createdByName=name,revision=1);self.validate(record)
      db.execute('INSERT INTO records VALUES(?,?,?,?,?)',(record['id'],company,ident,1,dumps(record)))
    db.execute('INSERT INTO prefs VALUES(?,?)',(ident,dumps(previous)));self.audit(db,u,'ترحيل البيانات السابقة',details={'count':sum(map(len,records.values()))})
   return self.public(u,db)
 def login(self,username,password,ip):
  username=str(username).strip().lower();key=hashlib.sha256((ip+'|'+username).encode()).hexdigest();ts=time.time()
  with self.connect() as db:
   a=db.execute('SELECT * FROM attempts WHERE key=?',(key,)).fetchone()
   if a and a['count']>=8 and ts-a['since']<900:raise Denied('محاولات كثيرة. حاول بعد 15 دقيقة.')
   u=db.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
   ok=u and u['active'] and isinstance(password,str) and len(password)<=256 and self.verify(password,u['password'])
   if not ok:
    if not a or ts-a['since']>=900:db.execute('INSERT OR REPLACE INTO attempts VALUES(?,1,?)',(key,ts))
    else:db.execute('UPDATE attempts SET count=count+1 WHERE key=?',(key,))
    db.commit();raise Denied('اسم المستخدم أو كلمة المرور غير صحيح.')
   db.execute('DELETE FROM attempts WHERE key=?',(key,));token=secrets.token_urlsafe(40);csrf=secrets.token_urlsafe(32)
   db.execute('DELETE FROM sessions WHERE expires<?',(ts,));db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],csrf,ts+8*3600));self.audit(db,u,'تسجيل الدخول');return token,csrf,self.public(u,db)
 def session(self,token):
  if not token:return None
  with self.connect() as db:
   row=db.execute('SELECT u.*,s.csrf FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.active=1',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
   return (self.public(row,db),row['csrf']) if row else None
 def logout(self,token):
  with self.connect() as db:db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(token.encode()).hexdigest(),))
 def scope(self,u,company):return self.has_permission(u,'accessPurchases') and company in self.companies and (u['role']=='admin' or company in u['scopes'])
 def visible(self,u,r,db=None):
  if not self.scope(u,r['company']):return False
  if r['createdBy']==u['id'] or self.has_permission(u,'viewCompanyRequests') or self.has_permission(u,'editAnyRequest'):return True
  if db is None:
   with self.connect() as db:return u['id'] in self.recipient_ids(db,r)
  return u['id'] in self.recipient_ids(db,r)
 def editable(self,u,r):return u['role']=='admin' or self.has_permission(u,'editAnyRequest') or (self.has_permission(u,'editOwnRequest') and r['createdBy']==u['id'] and r['tracking']['status'] in {'draft','rejected'})
 def deletable(self,u,r):return self.has_permission(u,'deleteRequest') and (u['role']=='admin' or self.has_permission(u,'editAnyRequest') or (r['createdBy']==u['id'] and r['tracking']['status'] in {'draft','rejected'}))
 def validate(self,r):
  if not isinstance(r,dict) or not re.fullmatch(r'PR-[A-Za-z0-9-]+',r.get('id','')) or r.get('company') not in self.companies:raise ValueError('معرف الطلب أو الشركة غير صالح.')
  if any(str(k).startswith('_') for k in r):raise Denied('حقول سجل القرارات الداخلية يصدرها الخادم فقط.')
  f=r.get('form');t=r.setdefault('tracking',{})
  if not isinstance(t,dict) or any(not isinstance(v,str) for v in t.values()):raise ValueError('حقول المتابعة يجب أن تكون نصوصاً.')
  allowed={'status','priority','owner','supplier','dueDate','notes','quoteAmount','currency','numberMode','sourceKey',*ROUTE_ROLES,*SERVER_TRACKING}
  if set(t)-allowed:raise Denied('حقول سير العمل غير مدعومة؛ سجل القرارات يصدر من الخادم فقط.')
  t.setdefault('status','draft');t.setdefault('priority','normal')
  if t.get('workflowPlan'):self.valid_workflow_plan(json.loads(t['workflowPlan']))
  if not isinstance(f,dict) or not isinstance(f.get('number'),str) or not f['number'].strip():raise ValueError('رقم الطلب مطلوب.')
  try:datetime.strptime(f['date'],'%Y-%m-%d')
  except (ValueError,KeyError):
   try:datetime.strptime(f['date'],'%d/%m/%Y')
   except (ValueError,KeyError):raise ValueError('تاريخ الطلب غير صالح.')
  rows=f.get('rows');
  if not isinstance(rows,list) or not 1<=len(rows)<=200 or any(not isinstance(row,list) or len(row)!=6 or any(not isinstance(v,str) for v in row) for row in rows):raise ValueError('مواد الطلب غير صالحة.')
  used=[row for row in rows if any(v.strip() for v in row)]
  if not used or any(not row[0].strip() for row in used):raise ValueError('أدخل اسم كل مادة مستخدمة.')
  for row in used:
   if row[3].strip():
    try:
     n=float(row[3].translate(str.maketrans('٠١٢٣٤٥٦٧٨٩٫٬','0123456789.,')).replace(',',''))
     if not 0<n<1e15:raise ValueError()
    except ValueError:raise ValueError('الكمية يجب أن تكون رقماً موجباً.')
  if t['status'] not in STATUSES or t['priority'] not in {'low','normal','high','urgent'}:raise ValueError('حالة أو أولوية غير صالحة.')
  if t.get('dueDate'):
   try:datetime.strptime(t['dueDate'],'%Y-%m-%d')
   except ValueError:raise ValueError('موعد المتابعة غير صالح.')
 def email(self,value):
  value=str(value or '').strip()
  if value and (len(value)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value)):raise ValueError('عنوان البريد الإلكتروني غير صالح.')
  return value
 def directory(self,u):
  with self.connect() as db:
   result=[]
   for row in db.execute('SELECT * FROM users WHERE active=1 ORDER BY name'):
    v=self.public(row,db);scopes=[c for c in self.companies if self.scope(u,c) and self.scope(v,c)]
    if scopes:result.append({k:v[k] for k in ['id','name','role','departmentId','departmentName','permissions']}|{'scopes':scopes})
   return result
 def department_public(self,db,row):
  return {'id':row['id'],'name':row['name'],'kind':row['kind'],'managerId':row['manager_id'],'active':bool(row['active']),'version':row['version'],'sortOrder':row['sort_order'],'members':[x['id'] for x in db.execute('SELECT id FROM users WHERE department_id=? ORDER BY name,id',(row['id'],))]}
 def departments(self,u):
  with self.connect() as db:return [self.department_public(db,row) for row in db.execute('SELECT * FROM departments WHERE deleted=0 ORDER BY sort_order,created,id')]
 def creator_department(self,db,creator_id):
  creator=db.execute('SELECT department_id FROM users WHERE id=?',(creator_id,)).fetchone()
  return self.resolve_department(db,creator['department_id']) if creator else None
 def department_for(self,db,r):
  t=r.get('tracking',{});ident=t.get('requestDepartmentId','')
  if ident and t.get('status') not in {'draft','rejected'}:return self.resolve_department(db,ident)
  return self.creator_department(db,r.get('createdBy'))
 def submission_department(self,db,r):
  department=self.creator_department(db,r['createdBy'])
  if not department or not department['active']:raise ValueError('مقدم الطلب غير مرتبط بقسم نشط. حدّد قسم حسابه من إدارة المستخدمين.')
  r['tracking']['requestDepartmentId']=department['id']
 def person_assignment(self,person):return {'id':person['id'],'name':person['name'],'type':'person','memberIds':[person['id']]}
 def candidate(self,db,ident,company,roles=None):
  row=db.execute('SELECT * FROM users WHERE id=?',(ident,)).fetchone()
  if not row or not row['active']:raise ValueError('اختر موظفاً نشطاً لمسؤولية المرحلة.')
  candidate=self.public(row,db)
  if not self.scope(candidate,company):raise Denied('الموظف خارج صلاحية الشركة.')
  return candidate
 def queue(self,db,r,kind,permission):
  people=[]
  for row in db.execute('SELECT u.* FROM users u JOIN departments d ON d.id=u.department_id WHERE u.active=1 AND d.active=1 AND d.deleted=0 AND d.kind=? ORDER BY u.created,u.id',(kind,)):
   person=self.public(row,db)
   if self.scope(person,r['company']) and self.has_permission(person,permission) and not (permission=='approveFinance' and person['id']==r['createdBy']):people.append(person)
  return people
 def valid_workflow_plan(self,plan):
  legacy={'version','departmentApproval','financeApproval','warehouseCheck'}
  if not isinstance(plan,dict) or set(plan) not in (set(DEFAULT_WORKFLOW_PLAN),set(DEFAULT_WORKFLOW_PLAN)-{'stageOrder'},legacy):
   raise ValueError('خطة الطلب غير صالحة.')
  if type(plan['version']) is not int or plan['version']<1 or any(type(plan[key]) is not bool for key in WORKFLOW_OPTIONS if key in plan):
   raise ValueError('تحقق من إصدار الخطة والمراحل المختارة.')
  order=plan.get('stageOrder',list(DEFAULT_STAGE_ORDER))
  if not isinstance(order,list) or len(order)!=len(DEFAULT_STAGE_ORDER) or any(not isinstance(key,str) for key in order) or set(order)!=set(DEFAULT_STAGE_ORDER):
   raise ValueError('ترتيب المراحل يجب أن يحتوي كل مرحلة مرة واحدة.')
  return {**DEFAULT_WORKFLOW_PLAN,**plan,'stageOrder':list(order)}
 def workflow_settings(self,db):
  row=db.execute("SELECT value FROM meta WHERE key='purchase_workflow'").fetchone()
  return self.valid_workflow_plan(json.loads(row['value'])) if row else copy.deepcopy(DEFAULT_WORKFLOW_PLAN)
 def workflow_plan(self):
  with self.connect() as db:return self.workflow_settings(db)
 def update_workflow_plan(self,user,data):
  if not isinstance(data,dict):raise ValueError('إعدادات الخطة غير صالحة.')
  requested=self.valid_workflow_plan(data)
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE')
   user=self.current_actor(db,user)
   if user['role']!='admin':raise Denied('تعديل خطة الطلبات متاح لمدير النظام فقط.')
   previous=self.workflow_settings(db)
   if requested['version']!=previous['version']:raise Conflict('عُدلت الخطة بواسطة مدير آخر. أعد فتح إعدادات الخطة قبل الحفظ.')
   if requested['stageOrder']==previous['stageOrder'] and all(requested[key]==previous[key] for key in WORKFLOW_OPTIONS):
    return {'plan':previous,'changed':False}
   plan={**requested,'version':previous['version']+1}
   db.execute("INSERT INTO meta(key,value) VALUES('purchase_workflow',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(dumps(plan),))
   self.audit(db,user,'تعديل خطة طلبات الشراء',details={'previous':previous,'plan':plan})
   return {'plan':plan,'changed':True}
 def request_plan(self,db,record):
  if record['tracking']['status'] in {'draft','rejected'}:return self.workflow_settings(db)
  encoded=record['tracking'].get('workflowPlan')
  return self.valid_workflow_plan(json.loads(encoded)) if encoded else copy.deepcopy(DEFAULT_WORKFLOW_PLAN)
 def prepare_submission(self,db,record):
  self.submission_department(db,record)
  plan=self.workflow_settings(db)
  record['tracking']['fulfillmentQueue']=''
  record['tracking']['workflowPlan']=dumps(plan)
  record['tracking']['status']=self.following_workflow_stage(plan,'draft')
  if record['tracking']['status'] in {'fulfillment','ordered'}:
   record['tracking']['fulfillmentQueue']='purchasing'
 def following_workflow_stage(self,plan,status):
  status_by_option={option:key for key,option in WORKFLOW_STAGE_OPTIONS}
  order=plan.get('stageOrder',DEFAULT_STAGE_ORDER)
  stages=[status_by_option[option] for option in order]
  index=-1 if status=='draft' else stages.index(status)
  for option in order[index+1:]:
   if plan[option]:return status_by_option[option]
  return 'received' if plan['completion'] else 'closed'
 def workflow_target(self,db,record,action):
  sources,target=WORKFLOW_ACTIONS.get(action,(set(),None))
  if record['tracking']['status'] not in sources:return None
  if action in {'submit','reject','cancel'}:return target
  return self.following_workflow_stage(self.request_plan(db,record),record['tracking']['status'])

 def routing(self,db,r,manual=True):
  t=r['tracking'];status=t['status'];permission=STAGE_PERMISSION.get(status);manual_id=t.get('manualAssigneeId','') if manual else ''
  if status in {'received','closed','cancelled'}:return None
  if status=='awaiting_receipt':
   try:return self.person_assignment(self.candidate(db,r['createdBy'],r['company']))
   except (ValueError,Denied):raise ValueError('حساب مقدم الطلب غير نشط أو لا يملك صلاحية الشركة. راجع مدير النظام لتحديث الحساب.')
  if manual_id:
   try:person=self.candidate(db,manual_id,r['company'])
   except (ValueError,Denied):raise ValueError('الموظف المعين يدوياً غير نشط أو خارج صلاحية الشركة؛ على المدير إعادة تعيينه.')
   return self.person_assignment(person)
  if status=='submitted':
   department=self.department_for(db,r)
   if not department or not department['active']:raise ValueError('مقدم الطلب غير مرتبط بقسم نشط. حدّد قسم حسابه من إدارة المستخدمين.')
   if not department['manager_id']:raise ValueError('لم يُعيّن مدير لـ «'+department['name']+'». اختر مديرًا من أعضاء القسم في إدارة الأقسام.')
   row=db.execute('SELECT * FROM users WHERE id=?',(department['manager_id'],)).fetchone()
   if not row or not row['active'] or row['department_id']!=department['id']:raise ValueError('رئيس قسم مقدم الطلب غير نشط أو لم يعد عضواً في القسم. حدّث إدارة الأقسام.')
   person=self.public(row,db)
   if not self.scope(person,r['company']) or not self.has_permission(person,'approveDepartment'):raise ValueError('رئيس قسم مقدم الطلب لا يملك صلاحية الموافقة أو صلاحية الشركة. حدّث صلاحياته.')
   if person['id']==r['createdBy']:raise Denied('لا يمكن لرئيس القسم الموافقة على طلبه الشخصي؛ يلزم تعديل إداري موثق أو رئيس قسم آخر.')
   return self.person_assignment(person)
  if not permission:return None
  kind={'approved':'purchasing','finance_pending':'finance','stock_check':'warehouse'}.get(status,t.get('fulfillmentQueue',''))
  if status in {'fulfillment','ordered'} and not kind:kind='warehouse' if self.queue(db,r,'warehouse',permission) else 'purchasing'
  if kind not in {'purchasing','finance','warehouse'}:raise ValueError('قسم المرحلة غير صالح.')
  people=self.queue(db,r,kind,permission)
  labels={'purchasing':'قسم المشتريات','finance':'قسم المالية','warehouse':'قسم المخازن'}
  if not people:raise ValueError('لا يوجد موظف نشط في '+labels[kind]+' يملك صلاحية هذه المرحلة والشركة. أضف أعضاء القسم وراجع صلاحياتهم من إدارة المستخدمين والأقسام.')
  return {'id':'queue-'+kind,'name':labels[kind],'type':'department','memberIds':[p['id'] for p in people]}
 def recipient_ids(self,db,r):
  try:
   assignment=self.routing(db,r)
   if not assignment:return set()
   result=set(assignment['memberIds']);permission=STAGE_PERMISSION.get(r['tracking']['status'])
   if assignment['type']=='person' and permission:
    result={ident for ident in result if self.has_permission(self.candidate(db,ident,r['company']),permission)}
   if r['tracking']['status'] in {'submitted','finance_pending'}:result.discard(r['createdBy'])
   return result
  except (Denied,ValueError):return set()
 def stage_user(self,db,r,manual=True):return self.routing(db,r,manual)
 def route(self,db,r):return self.routing(db,r,manual=False)
 def canonical_assignment(self,db,r):
  t=r['tracking'];status=t['status']
  if status in {'awaiting_receipt','received','closed','cancelled'}:t.pop('manualAssigneeId',None)
  assignment=self.routing(db,r)
  if status in {'fulfillment','ordered'} and assignment and assignment['type']=='department':t['fulfillmentQueue']=assignment['id'].removeprefix('queue-')
  if status in {'draft','rejected','cancelled'}:t.pop('fulfillmentQueue',None)
  t['assigneeId']=assignment['id'] if assignment and assignment['type']=='person' else '';t['assigneeName']=assignment['name'] if assignment else ''
 def routing_preview(self,db,u,r):
  department=self.department_for(db,r)
  result={'departmentName':department['name'] if department else '', 'current':None,'next':None,'currentError':'','nextError':'','currentAvailable':True,'nextAvailable':True,'canAct':False,'canEdit':self.editable(u,r),'canDelete':self.deletable(u,r)}
  try:result['current']=self.routing(db,r);result['canAct']=u['id'] in self.recipient_ids(db,r) if r['tracking']['status'] in INBOX_ACTIONS else False
  except (ValueError,Denied) as e:result.update(currentError=str(e),currentAvailable=False)
  result['plan']=self.request_plan(db,r)
  next_action={'draft':'submit','rejected':'submit','submitted':'approve','approved':'priced','finance_pending':'finance_approve','fulfillment':'ready','ordered':'deliver','awaiting_receipt':'confirm_receipt'}.get(r['tracking']['status'])
  next_status=self.workflow_target(db,r,next_action)
  if next_status:
   future=copy.deepcopy(r);future['tracking']['status']=next_status;future['tracking'].pop('manualAssigneeId',None)
   try:
    if next_action=='submit':self.prepare_submission(db,future)
    if future['tracking']['status'] in {'fulfillment','ordered'} and not future['tracking'].get('fulfillmentQueue'):future['tracking']['fulfillmentQueue']='purchasing'
    result['nextStatus']=future['tracking']['status']
    result['next']=self.routing(db,future)
   except (ValueError,Denied) as e:result.update(nextError=str(e),nextAvailable=False)
  return result
 def quote(self,r):
  t=r['tracking']
  try:
   text=str(t.get('quoteAmount','')).translate(str.maketrans('٠١٢٣٤٥٦٧٨٩٫٬','0123456789.,')).replace(',','').strip();n=Decimal(text)
   if not n.is_finite() or not 0<n<Decimal('1e15'):raise ValueError()
  except (InvalidOperation,ValueError):raise ValueError('أدخل قيمة تسعير موجبة وصالحة.')
  if t.get('currency') not in {'IQD','USD','JOD'}:raise ValueError('اختر عملة IQD أو USD أو JOD.')
  if not str(t.get('supplier','')).strip():raise ValueError('اسم المورد مطلوب لاعتماد التسعير.')
 def assigned(self,db,u,r):
  if r['tracking']['status']=='awaiting_receipt' and u['id']!=r['createdBy']:
   raise Denied('تأكيد الاستلام متاح لمقدم الطلب فقط.')
  assignment=self.routing(db,r)
  if not assignment or u['id'] not in self.recipient_ids(db,r):raise Denied('هذا الإجراء متاح لرئيس القسم أو لأحد أعضاء قسم المرحلة المخولين فقط.')
 def permitted(self,u,old,new,db=None,explicit=None):
  if db is None:
   with self.connect() as db:return self.permitted(u,old,new,db,explicit)
  if old is None:
   if not self.has_permission(u,'createRequest') or new['tracking']['status'] not in {'draft','submitted'}:raise Denied('لا تملك صلاحية إنشاء الطلب أو لا يمكن إنشاؤه بحالة متقدمة.')
   if any(new['tracking'].get(k) for k in SERVER_TRACKING):raise Denied('تعيين القسم ومسؤولي المرحلة يتم بواسطة الخادم.')
   department=db.execute('SELECT * FROM departments WHERE id=?',(u.get('departmentId',''),)).fetchone()
   if not department or not department['active'] or department['deleted']:raise ValueError('الحساب غير مرتبط بقسم نشط. على المدير تحديد قسم الحساب أولاً.')
   new['createdBy']=u['id'];new['tracking']['requestDepartmentId']=department['id']
   if new['tracking']['status']=='submitted' or not self.workflow_settings(db)['requestCreation']:
    if not self.has_permission(u,'submitRequest'):raise Denied('لا تملك صلاحية تقديم الطلب.')
    self.prepare_submission(db,new)
    self.route(db,new)
   return
  if not self.visible(u,old,db):raise Denied('لا تملك صلاحية الوصول إلى الطلب.')
  if new is None:
   if not self.deletable(u,old):raise Denied('لا تملك صلاحية حذف هذا الطلب.')
   return
  if old['company']!=new['company']:raise Denied('لا يمكن تغيير شركة طلب محفوظ.')
  new['createdBy']=old['createdBy']
  if old['tracking'].get('sourceKey','')!=new['tracking'].get('sourceKey','') or old['tracking'].get('sourceKey') and old['form']['number']!=new['form']['number']:raise Denied('مرجع عدد Excel ثابت للطلب المحفوظ.')
  if old['tracking'].get('numberMode')=='assigned' and old['form']['number']!=new['form']['number']:raise Denied('العدد المتسلسل ثابت للطلب المحفوظ.')
  if old['form']!=new['form'] and not self.editable(u,old):raise Denied('لا تملك صلاحية تعديل محتوى هذا الطلب في هذه المرحلة.')
  before=old['tracking']['status'];after=new['tracking']['status'];owner=old['createdBy']==u['id'];admin=u['role']=='admin'
  for field in SERVER_TRACKING:
   if old['tracking'].get(field,'')!=new['tracking'].get(field,''):raise Denied('حقول القسم والتكليف صادرة من الخادم فقط.')
  changed_route=any(old['tracking'].get(k,'')!=new['tracking'].get(k,'') for k in ROUTE_ROLES)
  if changed_route and before not in {'draft','rejected'} and explicit!='assign':raise Denied('تغيير مسار المرحلة متاح من التعديل الإداري فقط.')
  if explicit=='assign':
   if not admin or before!=after:raise Denied('إعادة التعيين متاحة للمدير دون تغيير المرحلة.')
   self.route(db,new);return
  if before!=after:
   if (before,after) in {('draft','submitted'),('rejected','submitted'),('rejected','draft'),('draft','cancelled'),('rejected','cancelled'),('submitted','cancelled')}:
    permission='deleteRequest' if after=='cancelled' else 'submitRequest'
    if not self.has_permission(u,permission) or not (owner or admin or self.has_permission(u,'editAnyRequest')):raise Denied('لا تملك صلاحية تقديم هذا الطلب أو إلغائه.')
    if after=='submitted':self.prepare_submission(db,new);self.route(db,new)
   else:
    if explicit is None:raise Denied('قرارات المراحل تتم من زر الإجراء المخصص، ولا تُستورد من Excel أو حفظ السجل.')
    if after!=self.workflow_target(db,old,explicit):raise Denied('لا يمكن تخطي مراحل سير الطلب.')
    self.assigned(db,u,old)
    if before in {'submitted','finance_pending'} and owner:raise Denied('لا يمكن اعتماد طلب أنشأته بنفسك.')
    if explicit in STOCK_DESTINATIONS:new['tracking']['fulfillmentQueue']=STOCK_DESTINATIONS[explicit]
    elif after in {'fulfillment','ordered'} and not new['tracking'].get('fulfillmentQueue'):new['tracking']['fulfillmentQueue']='purchasing'
    self.route(db,new)
    plan=self.request_plan(db,old)
    pricing_before_finance=plan['purchasePricing'] and plan['stageOrder'].index('purchasePricing')<plan['stageOrder'].index('financeApproval')
    if before=='approved' or before=='finance_pending' and pricing_before_finance:self.quote(new)
   if after=='rejected' and not str(new['tracking'].get('notes','')).strip():raise ValueError('اكتب سبب الرفض في ملاحظات المتابعة.')
  changed={k for k in set(old['tracking'])|set(new['tracking']) if old['tracking'].get(k,'')!=new['tracking'].get(k,'')}-{'status',*SERVER_TRACKING}
  if changed and not self.editable(u,old):
   if before in INBOX_ACTIONS:self.assigned(db,u,old)
   else:raise Denied('لا تملك صلاحية تعديل بيانات متابعة الطلب.')
   if changed & {'quoteAmount','currency','supplier'} and before!='approved':raise Denied('تعديل التسعير متاح لقسم المشتريات في مرحلة التسعير فقط.')
 def enqueue(self,db,u,old,new,event='status_changed'):
  status=new['tracking']['status'];previous=(old or {}).get('tracking',{}).get('status')
  if event=='status_changed' and (status==previous or status=='draft'):return
  recipients={new['createdBy']:new.get('createdByName','')}
  for ident in self.recipient_ids(db,new):
   person=db.execute('SELECT name FROM users WHERE id=?',(ident,)).fetchone()
   if person:recipients[ident]=person['name']
  payload={'fulfillmentQueue':new['tracking'].get('fulfillmentQueue',''),'recordId':new['id'],'requestNumber':new['form']['number'],'company':new['company'],'status':status,'previousStatus':previous,'actorName':u['name'],'assigneeName':new['tracking'].get('assigneeName',''),'notes':new['tracking'].get('notes','') if status=='rejected' else ''}
  for ident,name in recipients.items():
   db.execute('INSERT OR IGNORE INTO email_outbox(event_key,record_id,recipient_id,recipient_name,event,payload,created_at) VALUES(?,?,?,?,?,?,?)',(new['id']+':'+str(new['revision'])+':'+ident,new['id'],ident,name,event,dumps(payload),now()))
 def write_record(self,db,u,old,new,explicit=None,reason=None):
  ident=(new or old)['id']
  if new is not None:new.pop('routing',None)
  if new is None:
   db.execute('DELETE FROM records WHERE id=?',(ident,))
   db.execute('DELETE FROM purchase_source_bindings WHERE record_id=?',(ident,))
   db.execute("DELETE FROM purchase_material_examples WHERE source='request' AND source_id=?",(ident,))
   self.audit(db,u,'حذف طلب',ident)
   return
  before=(old or {}).get('tracking',{}).get('status');after=new['tracking']['status'];at=now();version=(old['revision']+1) if old else 1
  action='إنشاء الطلب' if old is None else ('إعادة تعيين المسار' if explicit=='assign' else 'تعديل الطلب')
  if before and before!=after:action=WORKFLOW_ACTION_LABELS.get(explicit,'تغيير الحالة: '+before+' → '+after)
  new.update(createdBy=old['createdBy'] if old else u['id'],createdByName=old.get('createdByName','') if old else u['name'],savedAt=old.get('savedAt',at) if old else at,updatedAt=at,revision=version,history=[*(old or {}).get('history',[]),{'at':at,'actor':u['name'],'actorId':u['id'],'action':action,'fromStatus':before,'toStatus':after}])
  if explicit in WORKFLOW_ACTION_LABELS:new['history'][-1]['workflowAction']=explicit
  if explicit=='admin_override':
   entry=new['history'][-1];entry.update(kind='admin_override',reason=reason,action='تجاوز إداري موثّق');action=entry['action']
  elif before!=after or explicit=='assign':new['tracking'].pop('manualAssigneeId',None)
  self.canonical_assignment(db,new)
  if explicit=='admin_override':new['history'][-1].update(assigneeId=new['tracking']['assigneeId'],assigneeName=new['tracking']['assigneeName'])
  db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?)',(ident,new['company'],new['createdBy'],version,dumps(new)))
  if old is None or old['form']['rows']!=new['form']['rows']:self.learn_purchase_materials(db,new)
  self.audit(db,u,action,ident,{'status':after,'fromStatus':before,'assigneeId':new['tracking']['assigneeId'],'notes':new['tracking'].get('notes',''),**({'kind':'admin_override','reason':reason} if explicit=='admin_override' else {})})
  self.enqueue(db,u,old,new,'admin_override' if explicit=='admin_override' else ('reassigned' if explicit=='assign' else 'status_changed'))
 def current_actor(self,db,u):
  row=db.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone()
  if not row or not row['active']:raise Denied('الحساب غير نشط. سجّل الدخول مجدداً.')
  return self.public(row,db)
 def action(self,u,ident,revision,action,trackingPatch=None):
  patch=trackingPatch or {}
  if not isinstance(patch,dict) or any(k in SERVER_TRACKING or k=='status' or not isinstance(v,str) for k,v in patch.items()):raise ValueError('حقول الإجراء غير صالحة.')
  allowed={'priority','owner','supplier','dueDate','notes','quoteAmount','currency',*ROUTE_ROLES}
  if set(patch)-allowed:raise ValueError('حقول الإجراء غير مدعومة.')
  if action=='assign' and set(patch)-set(ROUTE_ROLES):raise Denied('إعادة التعيين تعدّل مسؤولي المسار فقط.')
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE');u=self.current_actor(db,u);row=db.execute('SELECT * FROM records WHERE id=?',(ident,)).fetchone()
   if not row:raise ValueError('الطلب غير موجود.')
   old=json.loads(row['payload'])
   if not self.visible(u,old,db):raise Denied('لا تملك صلاحية الوصول إلى الطلب.')
   if revision!=old['revision']:raise Conflict('عُدّل الطلب بواسطة مستخدم آخر. حدّث السجل ثم راجع القرار.')
   new=copy.deepcopy(old);new['tracking'].update(patch)
   if action!='assign':
    if action not in WORKFLOW_ACTIONS or old['tracking']['status'] not in WORKFLOW_ACTIONS[action][0]:raise Denied('الإجراء غير متاح في المرحلة الحالية.')
    new['tracking']['status']=self.workflow_target(db,old,action)
   self.validate(new);self.permitted(u,old,new,db,action);self.write_record(db,u,old,new,action)
   db.execute("INSERT INTO meta VALUES('revision','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")
   out=self.envelope(db,u);out.update(record=new,changed=True);return out
 def admin_update(self,u,ident,revision,status,assigneeId,trackingPatch=None,reason=''):
  reason=str(reason or '').strip()
  if not 3<=len(reason)<=1000:raise ValueError('اكتب سبب التعديل الإداري بين 3 و1000 حرف.')
  if status not in STATUSES:raise ValueError('حالة الطلب غير صالحة.')
  if not isinstance(assigneeId,str):raise ValueError('الموظف المكلف غير صالح.')
  patch=trackingPatch or {}
  allowed={'priority','owner','supplier','dueDate','notes','quoteAmount','currency',*ROUTE_ROLES}
  if not isinstance(patch,dict) or set(patch)-allowed or any(not isinstance(v,str) for v in patch.values()):raise ValueError('حقول التعديل الإداري غير صالحة.')
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE');u=self.current_actor(db,u)
   if u['role']!='admin':raise Denied('التعديل الإداري متاح لمدير النظام فقط.')
   row=db.execute('SELECT * FROM records WHERE id=?',(ident,)).fetchone()
   if not row:raise ValueError('الطلب غير موجود.')
   old=json.loads(row['payload'])
   if revision!=old['revision']:raise Conflict('عُدّل الطلب منذ فتحه. حدّث البيانات قبل التعديل الإداري.')
   new=copy.deepcopy(old);new['tracking'].update(patch);new['tracking']['status']=status
   for field in set(patch)&set(ROUTE_ROLES):
    if patch[field]:self.candidate(db,patch[field],new['company'],ROUTE_ROLES[field])
   new['tracking'].pop('manualAssigneeId',None)
   if status=='submitted' and old['tracking']['status'] in {'draft','rejected'} and not assigneeId:self.submission_department(db,new)
   if status=='awaiting_receipt' and assigneeId:raise ValueError('يُسند تأكيد الاستلام تلقائيًا إلى مقدم الطلب.')
   if status not in {'received','closed','cancelled'}:
    if assigneeId:self.candidate(db,assigneeId,new['company']);new['tracking']['manualAssigneeId']=assigneeId
    elif status in INBOX_ACTIONS:self.stage_user(db,new,manual=False)
   self.validate(new);self.write_record(db,u,old,new,'admin_override',reason)
   db.execute("INSERT INTO meta VALUES('revision','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")
   out=self.envelope(db,u);out.update(record=new,changed=True);return out
 def inbox_entries(self,db,user):
  entries=[]
  placeholders=','.join('?' for _ in INBOX_ACTIONS)
  for row in db.execute("SELECT payload FROM records WHERE json_extract(payload,'$.tracking.status') IN ("+placeholders+")",tuple(INBOX_ACTIONS)):
   record=json.loads(row['payload'])
   if not self.scope(user,record['company']) or user['id'] not in self.recipient_ids(db,record):
    continue
   status=record['tracking']['status']
   title,instruction=INBOX_ACTIONS[status]
   if status=='fulfillment' and record['tracking'].get('fulfillmentQueue')=='purchasing':
    title,instruction='مطلوب شراء وتجهيز المواد','اشترِ المواد وجهّزها للتسليم إلى مقدم الطلب.'
   entries.append({
    'id':f"stage:{record['id']}:{record['revision']}",'kind':'task','pending':True,
    'title':title,'message':instruction,'recordId':record['id'],'requestNumber':record['form']['number'],
    'createdAt':record.get('updatedAt',record['savedAt']),
   })

  # Workflow results already have a durable event in the same transaction as the decision.
  results=db.execute('''
   SELECT e.id,e.record_id,e.event,e.payload,e.created_at,r.company
   FROM email_outbox e JOIN records r ON r.id=e.record_id
   WHERE e.recipient_id=? AND r.creator=? ORDER BY e.id DESC LIMIT 200
  ''',(user['id'],user['id']))
  for row in results:
   if not self.scope(user,row['company']):
    continue
   payload=json.loads(row['payload'])
   status=payload.get('status')
   if status not in INBOX_RESULTS or status==payload.get('previousStatus'):
    continue
   title,message=INBOX_RESULTS[status]
   if status=='approved' and payload.get('previousStatus') not in {'submitted','finance_pending'}:
    title,message='أُرسل طلبك إلى المشتريات','بدأت مرحلة التسعير وفق خطة الطلب.'
   if status=='stock_check' and payload.get('previousStatus')!='finance_pending':
    title,message='وصل طلبك إلى المخازن','بدأ فحص توفر المواد وفق خطة الطلب.'
   if status=='finance_pending' and payload.get('previousStatus')!='approved':
    title,message='وصل طلبك إلى المالية','بدأت مرحلة الموافقة على الصرف وفق خطة الطلب.'
   if status=='ordered' and payload.get('previousStatus')!='fulfillment':
    title,message='طلبك في مرحلة جاهز للتسليم','انتقل الطلب إلى مسؤول التسليم وفق الخطة.'
   if status=='fulfillment' and payload.get('previousStatus')=='stock_check':
    if payload.get('fulfillmentQueue')=='warehouse':
     title,message='مواد طلبك متوفرة في المخازن','بدأ قسم المخازن تجهيز الطلب.'
    else:
     title,message='أُحيل طلبك إلى المشتريات','المواد غير متوفرة في المخازن. سيتولى قسم المشتريات شراءها وتجهيزها.'
   if status=='fulfillment' and payload.get('previousStatus')=='finance_pending':
    title,message='وافقت المالية على طلبك','انتقل الطلب إلى التجهيز.'
   if status in {'received','closed'} and payload.get('previousStatus')=='awaiting_receipt':
    message='سُجّل تأكيد الاستلام من مقدم الطلب وانتهت الخطة.'
   if status=='received' and payload.get('previousStatus')=='ordered':
    title,message='تم تسليم طلبك','سُجّل تسليم المواد وانتهت الخطة.'
   if row['event']=='admin_override' and status!='rejected':
    title='تغيّرت حالة طلبك إداريًا'
    message='افتح الطلب لمراجعة حالته الحالية.'
   if status=='rejected' and payload.get('notes'):
    message+=' السبب: '+payload['notes']
   entries.append({
    'id':f"result:{row['id']}",'kind':'result','pending':False,'title':title,'message':message,
    'recordId':row['record_id'],'requestNumber':payload.get('requestNumber',''),'createdAt':row['created_at'],
   })

  tasks=db.execute('''
   SELECT t.*,r.company,json_extract(r.payload,'$.form.number') AS request_number,u.name AS sender_name
   FROM preview_tasks t JOIN records r ON r.id=t.record_id JOIN users u ON u.id=t.sender_id
   WHERE t.recipient_id=? OR (t.sender_id=? AND t.completed_at IS NOT NULL)
  ''',(user['id'],user['id']))
  for row in tasks:
   if not self.scope(user,row['company']):
    continue
   assigned=row['recipient_id']==user['id']
   if assigned and not self.has_permission(user,'previewRequest'):
    continue
   completed=bool(row['completed_at'])
   if assigned:
    title='تمت المعاينة' if completed else 'مطلوب منك معاينة المستند'
    message='أرسلها '+row['sender_name']
    if row['message']:
     message+=' · '+row['message']
   else:
    title='اكتملت معاينة طلبك'
    message='أكمل الموظف المكلّف معاينة المستند.'
   entries.append({
    'id':('preview:' if assigned else 'preview-result:')+row['id'],
    'kind':'preview' if assigned else 'result','taskId':row['id'] if assigned else None,
    'pending':assigned and not completed,'title':title,'message':message,'recordId':row['record_id'],
    'requestNumber':row['request_number'],'createdAt':row['created_at'] if assigned else row['completed_at'],
   })

  reads={row['item_id'] for row in db.execute('SELECT item_id FROM inbox_reads WHERE user_id=?',(user['id'],))}
  for item in entries:
   item['read']=item['id'] in reads
  entries.sort(key=lambda item:(item['pending'],item['createdAt'],item['id']),reverse=True)
  pending=[item for item in entries if item['pending']]
  recent=[item for item in entries if not item['pending']][:100]
  return pending+recent

 def inbox(self,user):
  with self.connect() as db:
   user=self.current_actor(db,user)
   entries=self.inbox_entries(db,user)
   return {'unread':sum(not item['read'] for item in entries),'items':entries}

 def read_inbox(self,user,item_id=None,all_items=False):
  with self.connect() as db:
   user=self.current_actor(db,user)
   entries=self.inbox_entries(db,user)
   keys=[item['id'] for item in entries if not item['read'] and (all_items or item['id']==item_id)]
   if not all_items and not any(item['id']==item_id for item in entries):
    raise Denied('هذا الإشعار غير متاح لحسابك.')
   db.executemany('INSERT OR IGNORE INTO inbox_reads(user_id,item_id) VALUES(?,?)',[(user['id'],key) for key in keys])
   return {'ok':True,'unread':sum(not item['read'] for item in entries)-len(keys)}

 def request_preview(self,user,record_id,revision,recipient_id,message=''):
  if not isinstance(message,str) or len(message)>500:
   raise ValueError('ملاحظة المعاينة يجب أن تكون نصًا بحد أقصى 500 حرف.')
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE')
   user=self.current_actor(db,user)
   row=db.execute('SELECT payload FROM records WHERE id=?',(record_id,)).fetchone()
   if not row:
    raise ValueError('الطلب غير موجود.')
   record=json.loads(row['payload'])
   if not self.visible(user,record,db) or not (
    user['role']=='admin' or record['createdBy']==user['id'] or
    self.editable(user,record) or user['id'] in self.recipient_ids(db,record)
   ):
    raise Denied('لا تملك صلاحية طلب معاينة لهذا الطلب.')
   if record['revision']!=revision:
    raise Conflict('تغيّر الطلب منذ فتحه. افتح أحدث نسخة قبل طلب المعاينة.')
   person=self.candidate(db,recipient_id,record['company'])
   if person['id']==user['id'] or not self.has_permission(person,'previewRequest'):
    raise Denied('اختر موظفًا آخر لديه صلاحية المعاينة لهذه الشركة.')
   existing=db.execute('SELECT id FROM preview_tasks WHERE record_id=? AND recipient_id=? AND completed_at IS NULL',(record_id,recipient_id)).fetchone()
   if existing:
    return {'id':existing['id'],'existing':True}
   task_id=secrets.token_hex(16)
   db.execute('INSERT INTO preview_tasks(id,record_id,recipient_id,sender_id,message,created_at) VALUES(?,?,?,?,?,?)',
              (task_id,record_id,recipient_id,user['id'],message.strip(),now()))
   self.audit(db,user,'إسناد معاينة المستند',record_id,{'recipientName':person['name']})
   return {'id':task_id,'existing':False}

 def preview_task_for(self,db,user,task_id):
  row=db.execute('''
   SELECT t.completed_at,r.payload FROM preview_tasks t JOIN records r ON r.id=t.record_id
   WHERE t.id=? AND t.recipient_id=?
  ''',(task_id,user['id'])).fetchone()
  if not row:
   raise Denied('مهمة المعاينة غير متاحة لحسابك.')
  record=json.loads(row['payload'])
  if not self.scope(user,record['company']) or not self.has_permission(user,'previewRequest'):
   raise Denied('مهمة المعاينة خارج صلاحيات حسابك.')
  return row,record

 def preview_task(self,user,task_id):
  with self.connect() as db:
   user=self.current_actor(db,user)
   task,record=self.preview_task_for(db,user,task_id)
   return {'completed':bool(task['completed_at']),'record':{key:record[key] for key in ('id','company','form','revision')}}

 def complete_preview(self,user,task_id,revision):
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE')
   user=self.current_actor(db,user)
   task,record=self.preview_task_for(db,user,task_id)
   if task['completed_at']:
    return {'ok':True}
   if record['revision']!=revision:
    raise Conflict('تغيّر الطلب بعد فتح المعاينة. افتح المستند مرة أخرى قبل التأكيد.')
   db.execute('UPDATE preview_tasks SET completed_at=? WHERE id=?',(now(),task_id))
   db.execute('INSERT OR IGNORE INTO inbox_reads(user_id,item_id) VALUES(?,?)',(user['id'],'preview:'+task_id))
   self.audit(db,user,'إكمال معاينة المستند',record['id'],{'revision':revision})
   return {'ok':True}
 def notifications(self,u,record_id=None):
  with self.connect() as db:
   visible={r['id'] for r in self.records(db,u)};items=[];counts={}
   for row in db.execute('SELECT * FROM email_outbox ORDER BY id DESC'):
    if row['record_id'] not in visible or (record_id is not None and row['record_id']!=record_id):continue
    counts[row['status']]=counts.get(row['status'],0)+1
    if len(items)<200:
     item={'recordId':row['record_id'],'recipientName':row['recipient_name'],'status':row['status'],'attempts':row['attempts'],'createdAt':row['created_at'],'sentAt':row['sent_at']}
     if u['role']=='admin':item.update(id=row['id'],lastError=row['last_error'])
     items.append(item)
   return {'items':items,'counts':counts}
 def records(self,db,u):
  records=[r for row in db.execute('SELECT payload FROM records') if self.visible(u,r:=json.loads(row[0]),db)]
  for r in records:r['routing']=self.routing_preview(db,u,r)
  return records
 def envelope(self,db,u):
  pref=db.execute('SELECT payload FROM prefs WHERE user_id=?',(u['id'],)).fetchone();state=json.loads(pref[0]) if pref else {'selected':next(iter(self.companies)),'forms':{},'logos':{}}
  records=self.records(db,u);state['archives']={};baseline={}
  for r in records:state['archives'].setdefault(r['company'],[]).append(r);baseline[r['id']]={'revision':r['revision'],'hash':digest(r)}
  token=secrets.token_urlsafe(24);db.execute('INSERT INTO views VALUES(?,?,?,?)',(token,u['id'],time.time(),dumps(baseline)));db.execute('DELETE FROM views WHERE created<?',(time.time()-86400,))
  rev=db.execute("SELECT value FROM meta WHERE key='revision'").fetchone();return {'state':state,'revision':int(rev[0]) if rev else 0,'view':token,'user':u,'workflowPlan':self.workflow_settings(db)}
 def load(self,u):
  with self.connect() as db:
   u=self.current_actor(db,u)
   if not self.has_permission(u,'accessPurchases'):raise Denied('الدخول إلى طلبات الشراء غير مسموح لحسابك.')
   return self.envelope(db,u)
 def save(self,u,state,view):
  if not isinstance(state,dict) or not isinstance(state.get('archives'),dict):raise ValueError('صيغة السجل غير صالحة.')
  forms=state.get('forms',{})
  if not isinstance(forms,dict):raise ValueError('المسودات غير صالحة.')
  for company,form in forms.items():
   if company not in self.companies or not isinstance(form,dict):raise ValueError('شركة المسودة غير صالحة.')
   for key,value in form.items():
    if key=='rows':
     if not isinstance(value,list) or len(value)>200 or any(not isinstance(row,list) or len(row)!=6 or any(not isinstance(v,str) for v in row) for row in value):raise ValueError('مواد المسودة غير صالحة.')
    elif not isinstance(value,str):raise ValueError('حقول المسودة يجب أن تكون نصوصاً.')
  if not isinstance(state.get('logos',{}),dict):raise ValueError('الشعارات غير صالحة.')
  incoming={}
  for company,rows in state['archives'].items():
   if company not in self.companies or not isinstance(rows,list):raise ValueError('شركة غير صالحة.')
   for r in rows:
    r=copy.deepcopy(r);self.validate(r)
    if r['company']!=company or r['id'] in incoming:raise ValueError('معرفات مكررة أو شركة غير متطابقة.')
    incoming[r['id']]=r
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE');u=self.current_actor(db,u);row=db.execute('SELECT payload FROM views WHERE id=? AND user_id=?',(view,u['id'])).fetchone()
   if not row:raise Conflict('انتهت نسخة العرض. حدّث السجل قبل الحفظ.')
   if not self.has_permission(u,'accessPurchases'):raise Denied('الدخول إلى طلبات الشراء غير مسموح لحسابك.')
   base=json.loads(row[0]);changes=[]
   for ident in set(incoming)|set(base):
    new=incoming.get(ident);b=base.get(ident)
    if new and b and digest(new)==b['hash']:continue
    oldrow=db.execute('SELECT * FROM records WHERE id=?',(ident,)).fetchone();old=json.loads(oldrow['payload']) if oldrow else None
    if old and (not b or oldrow['version']!=b['revision']):raise Conflict('عدّل مستخدم آخر الطلب نفسه. حدّث الصفحة لمراجعة أحدث نسخة.')
    if b and not old:raise Conflict('حُذف الطلب بواسطة مستخدم آخر.')
    if new and not self.scope(u,new['company']):raise Denied('الشركة خارج صلاحيات حسابك.')
    self.permitted(u,old,new,db)
    if new is not None and old is None:self.apply_purchase_number(db,u,new)
    changes.append((ident,old,new))
   # Validate final request-number uniqueness in the same transaction.
   final={r['id']:json.loads(r['payload']) for r in db.execute('SELECT * FROM records')}
   for ident,old,new in changes:
    if new:final[ident]=new
    else:final.pop(ident,None)
   seen={}
   for r in final.values():
    f=r['form'];d=f['date'];
    for fmt in ['%d/%m/%Y','%Y-%m-%d']:
     try:d=datetime.strptime(d,fmt).date().isoformat();break
     except ValueError:pass
    k=(r['company'],f['number'].strip(),d)
    source=r['tracking'].get('sourceKey','')
    previous=seen.get(k)
    if previous is not None and (not source or not previous or previous==source):raise ValueError('رقم الطلب والتاريخ مكرران للشركة نفسها.')
    seen[k]=source
   for ident,old,new in changes:self.write_record(db,u,old,new)
   prefs={k:v for k,v in state.items() if k not in {'archives','editSession'}};db.execute('INSERT OR REPLACE INTO prefs VALUES(?,?)',(u['id'],dumps(prefs)))
   if changes:db.execute("INSERT INTO meta VALUES('revision','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")
   out=self.envelope(db,u);out['changed']=bool(changes);return out
 def users(self,u):
  if u['role']!='admin':raise Denied('إدارة المستخدمين متاحة لمدير النظام فقط.')
  with self.connect() as db:return [self.public(row,db) for row in db.execute('SELECT * FROM users ORDER BY created')]
 def manage_user(self,u,data):
  if u['role']!='admin':raise Denied('إدارة المستخدمين متاحة لمدير النظام فقط.')
  role=data.get('role');scopes=data.get('scopes',[]);name=str(data.get('name','')).strip();username=str(data.get('username','')).strip().lower();ident=data.get('id') or secrets.token_hex(12)
  if role not in ROLES or not name or not re.fullmatch('[a-z0-9._-]{3,64}',username) or not isinstance(scopes,list) or any(c not in self.companies for c in scopes):raise ValueError('تحقق من اسم المستخدم والدور والشركات.')
  encoded=self.password(data['password']) if data.get('password') else None
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE');u=self.current_actor(db,u)
   if u['role']!='admin':raise Denied('إدارة المستخدمين متاحة لمدير النظام فقط.')
   old=db.execute('SELECT * FROM users WHERE id=?',(ident,)).fetchone();active=data.get('active',bool(old['active']) if old else True)
   if not isinstance(active,bool):raise ValueError('حالة الحساب غير صالحة.')
   department_id=data.get('departmentId',old['department_id'] if old else (db.execute('SELECT id FROM departments WHERE active=1 AND deleted=0 ORDER BY sort_order,id LIMIT 1').fetchone() or {'id':''})['id'])
   if not isinstance(department_id,str):raise ValueError('قسم الحساب غير صالح.')
   department=db.execute('SELECT * FROM departments WHERE id=?',(department_id,)).fetchone() if department_id else None
   if department_id and (not department or not department['active'] or department['deleted']):raise ValueError('اختر قسماً نشطاً للحساب.')
   overrides=self.permission_overrides(data.get('permissions',json.loads(old['permissions']) if old else {}));email=self.email(data.get('email',old['email'] if old else ''))
   if not old and not encoded:raise ValueError('كلمة المرور مطلوبة للمستخدم الجديد.')
   if old and old['role']=='admin' and old['active'] and (role!='admin' or not active) and db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]<=1:raise Denied('لا يمكن تعطيل آخر مدير للنظام أو تغيير دوره.')
   try:db.execute('INSERT INTO users(id,username,name,role,scopes,password,active,created,email,department_id,permissions) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,name=excluded.name,role=excluded.role,scopes=excluded.scopes,password=excluded.password,active=excluded.active,email=excluded.email,department_id=excluded.department_id,permissions=excluded.permissions',(ident,username,name,role,dumps(scopes),encoded or old['password'],int(active),old['created'] if old else now(),email,department_id,dumps(overrides)))
   except sqlite3.IntegrityError:raise ValueError('اسم المستخدم مستخدم مسبقاً.')
   if not old or old['department_id']!=department_id:self.touch_departments(db,[old['department_id'] if old else '',department_id])
   db.execute('DELETE FROM sessions WHERE user_id=?',(ident,));db.execute('DELETE FROM views WHERE user_id=?',(ident,));self.audit(db,u,'تعديل مستخدم' if old else 'إنشاء مستخدم',details={'user':username,'role':role,'active':active,'departmentId':department_id,'permissions':overrides})
   return self.public(db.execute('SELECT * FROM users WHERE id=?',(ident,)).fetchone(),db)
 def change_password(self,u,old,new):
  encoded=self.password(new)
  with self.connect() as db:
   user=db.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone()
   if not isinstance(old,str) or not self.verify(old,user['password']):raise Denied('كلمة المرور الحالية غير صحيحة.')
   db.execute('UPDATE users SET password=? WHERE id=?',(encoded,u['id']));db.execute('DELETE FROM sessions WHERE user_id=?',(u['id'],));self.audit(db,u,'تغيير كلمة المرور')
 def audit_log(self,u,record_id=None):
  with self.connect() as db:
   u=self.current_actor(db,u)
   if not self.has_permission(u,'auditRequests'):raise Denied('لا تملك صلاحية تدقيق الطلبات.')
   if u['role']=='admin' and record_id is None:
    return [dict(r) for r in db.execute('SELECT * FROM audit ORDER BY seq DESC LIMIT 300')]
   companies=[c for c in self.companies if self.scope(u,c)]
   if not companies:return []
   where='r.company IN ('+','.join('?' for _ in companies)+')'
   if record_id is not None:where+=' AND a.record_id=?';companies.append(record_id)
   query='SELECT a.at,a.actor_name,a.action,a.record_id,a.details,r.company,r.payload FROM audit a JOIN records r ON r.id=a.record_id WHERE '+where+' ORDER BY a.seq DESC LIMIT 300'
   events=[]
   for row in db.execute(query,companies):
    event={key:row[key] for key in ['at','actor_name','action','record_id','company']}
    event['requestNumber']=json.loads(row['payload'])['form']['number']
    details=json.loads(row['details'])
    event['details']={key:details[key] for key in ['status','fromStatus','kind','reason','notes'] if key in details}
    events.append(event)
   return events
 def backup(self):
  dest=self.folder/'team-backups';dest.mkdir(exist_ok=True);p=dest/('team-'+datetime.now().strftime('%Y%m%d-%H%M%S%f')+'.sqlite3')
  with self.connect() as src,sqlite3.connect(p) as dst:src.backup(dst)
  p.chmod(0o600)
  for old in sorted(dest.glob('team-*.sqlite3'))[:-10]:old.unlink()

 def correspondence_number_parts(self,value):
  match=re.search(r'[0-9٠-٩۰-۹]+',value)
  if not match:return None
  digits=match.group();translation=str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹','01234567890123456789')
  return (value[:match.start()],int(digits.translate(translation)),value[match.end():],digits)
 def remember_correspondence_number(self,db,direction,number):
  if not self.correspondence_number_parts(number):return
  # A manually entered book number becomes the start for both types, including a lower number.
  db.execute("INSERT INTO correspondence_number_sequences(direction,number) VALUES('shared',?) ON CONFLICT(direction) DO UPDATE SET number=excluded.number",(number,))
 def seed_correspondence_numbers(self,db):
  # Start the requested shared sequence at one; retain old books and retired per-type counters.
  db.execute("INSERT OR IGNORE INTO correspondence_number_sequences(direction,number) VALUES('shared','0')")
 def next_correspondence_number(self,db,direction):
  previous=db.execute("SELECT number FROM correspondence_number_sequences WHERE direction='shared'").fetchone()
  parts=self.correspondence_number_parts(previous[0]) if previous else ('',0,'','0')
  prefix,number,suffix,digits=parts
  used=set()
  # Include deleted books, so deleting an entry never recycles an issued number.
  for row in db.execute('SELECT document_number FROM correspondence'):
   item=self.correspondence_number_parts(row[0])
   if item and (item[0],item[2])==(prefix,suffix):used.add(item[1])
  number+=1
  while number in used:number+=1
  text=str(number).zfill(len(digits))
  if any(char in '٠١٢٣٤٥٦٧٨٩' for char in digits):text=text.translate(str.maketrans('0123456789','٠١٢٣٤٥٦٧٨٩'))
  elif any(char in '۰۱۲۳۴۵۶۷۸۹' for char in digits):text=text.translate(str.maketrans('0123456789','۰۱۲۳۴۵۶۷۸۹'))
  result=prefix+text+suffix
  if len(result)>100:raise ValueError('رقم الكتاب التالي يتجاوز الطول المسموح. أدخل رقمًا أقصر.')
  return result
 def correspondence_next_number(self,user,direction):
  if not isinstance(direction,str) or direction not in {'incoming','outgoing'}:raise ValueError('اختر الوارد أو الصادر.')
  with self.connect() as db:
   self.correspondence_actor(db,user,'createCorrespondence')
   return {'direction':direction,'number':self.next_correspondence_number(db,direction),'shared':True}
 def correspondence_actor(self,db,user,permission='viewCorrespondence'):
  user=self.current_actor(db,user)
  if not self.has_permission(user,'viewCorrespondence') or not self.has_permission(user,permission):
   raise Denied('لا تملك صلاحية هذا الإجراء في سجل الصادر والوارد.')
  return user
 def correspondence_filters(self,filters):
  if not isinstance(filters,dict):raise ValueError('مرشحات السجل غير صالحة.')
  direction=filters.get('direction','all')
  if direction not in {'all','incoming','outgoing'}:raise ValueError('اختر الوارد أو الصادر أو جميع القيود.')
  query=filters.get('q','').strip()
  if len(query)>200:raise ValueError('نص البحث طويل.')
  clauses=['deleted=0']
  values=[]
  if direction!='all':
   clauses.append('direction=?')
   values.append(direction)
  if query:
   clauses.append("(agency LIKE ? OR subject LIKE ? OR document_number LIKE ?)")
   values.extend(['%'+query+'%']*3)
  for key,operator in [('from','>='),('to','<=')]:
   value=filters.get(key,'')
   if value:
    try:
     if datetime.strptime(value,'%Y-%m-%d').date().isoformat()!=value:raise ValueError()
    except ValueError:raise ValueError('تاريخ البحث غير صالح.')
    clauses.append('document_date'+operator+'?')
    values.append(value)
  if filters.get('from') and filters.get('to') and filters['from']>filters['to']:raise ValueError('بداية الفترة بعد نهايتها.')
  return ' AND '.join(clauses),values
 def correspondence_select(self):
  return """SELECT c.*,creator.username AS creator_username,
   editor_event.actor AS editor_id,editor_event.actor_name AS editor_name,
   editor_event.at AS editor_at,editor_event.details AS editor_details,editor.username AS editor_username
   FROM correspondence c
   LEFT JOIN users creator ON creator.id=c.created_by
   LEFT JOIN audit editor_event ON editor_event.seq=(
    SELECT seq FROM audit WHERE record_id=c.id AND action IN ('تعديل قيد وارد','تعديل قيد صادر') ORDER BY seq DESC LIMIT 1)
   LEFT JOIN users editor ON editor.id=editor_event.actor"""
 def correspondence_enriched(self,db,ident):
  return self.correspondence_public(db.execute(self.correspondence_select()+' WHERE c.id=?',(ident,)).fetchone())
 def correspondence_public(self,row):
  extra=dict(row);details=json.loads(extra.get('editor_details') or '{}')
  return {
   'id':row['id'],'direction':row['direction'],'serial':row['serial'],
   'agency':row['agency'],'documentNumber':row['document_number'],'documentDate':row['document_date'],
   'subject':row['subject'],'notes':row['notes'],'version':row['version'],'createdBy':row['created_by'],
   'createdByName':row['created_by_name'],'createdAt':row['created_at'],'updatedAt':row['updated_at'],
   'createdByUsername':extra.get('creator_username') or '',
   'lastEditedBy':extra.get('editor_id') or '', 'lastEditedByName':extra.get('editor_name') or '',
   'lastEditedByUsername':details.get('username') or extra.get('editor_username') or '',
   'lastEditedAt':extra.get('editor_at') or '',
  }
 def correspondence_list(self,user,filters=None,export=False):
  filters=filters or {}
  where,values=self.correspondence_filters(filters)
  try:page=int(filters.get('page',1))
  except (ValueError,TypeError):raise ValueError('رقم الصفحة غير صالح.')
  if not 1<=page<=1000000:raise ValueError('رقم الصفحة غير صالح.')
  with self.connect() as db:
   self.correspondence_actor(db,user,'exportCorrespondence' if export else 'viewCorrespondence')
   total=db.execute('SELECT COUNT(*) FROM correspondence WHERE '+where,values).fetchone()[0]
   if export:
    if total>20000:raise ValueError('حدد فترة أصغر لتصدير 20,000 قيد كحد أقصى.')
    rows=db.execute(self.correspondence_select()+' WHERE '+where+' ORDER BY c.document_date DESC,c.direction,c.serial DESC',values).fetchall()
    return [self.correspondence_public(row) for row in rows]
   pages=max(1,(total+24)//25)
   page=min(page,pages)
   rows=db.execute(self.correspondence_select()+' WHERE '+where+' ORDER BY c.document_date DESC,c.updated_at DESC,c.id DESC LIMIT 25 OFFSET ?',values+[(page-1)*25]).fetchall()
   counts={row['direction']:row['n'] for row in db.execute('SELECT direction,COUNT(*) n FROM correspondence WHERE deleted=0 GROUP BY direction')}
   return {'items':[self.correspondence_public(row) for row in rows],'total':total,'page':page,'pages':pages,'counts':counts}
 def correspondence_events(self,db,ident,before=None):
  if before is not None and (type(before) is not int or before<1):raise ValueError('مرجع سجل التعديلات غير صالح.')
  rows=db.execute("""SELECT event.*,account.username FROM audit event
   LEFT JOIN users account ON account.id=event.actor WHERE record_id=?"""+(' AND seq<?' if before else '')+' ORDER BY seq DESC LIMIT 51',[ident]+([before] if before else [])).fetchall()
  events=[]
  for event in rows[:50]:
   details=json.loads(event['details'])
   events.append({'seq':event['seq'],'at':event['at'],'actor':event['actor_name'],'actorId':event['actor'],
    'username':details.get('username') or event['username'] or '', 'action':event['action'],
    'changedFields':details.get('changedFields')})
  return {'history':events,'historyHasMore':len(rows)>50,'historyBefore':events[-1]['seq'] if events else None}
 def correspondence_item(self,user,ident):
  with self.connect() as db:
   self.correspondence_actor(db,user)
   row=db.execute(self.correspondence_select()+' WHERE c.id=? AND c.deleted=0',(ident,)).fetchone()
   if not row:raise ValueError('القيد غير موجود.')
   return {'item':self.correspondence_public(row),**self.correspondence_events(db,ident)}
 def correspondence_history(self,user,ident,before):
  with self.connect() as db:
   self.correspondence_actor(db,user)
   if not db.execute('SELECT 1 FROM correspondence WHERE id=? AND deleted=0',(ident,)).fetchone():raise ValueError('القيد غير موجود.')
   return self.correspondence_events(db,ident,before)
 def save_correspondence(self,user,data):
  if not isinstance(data,dict):raise ValueError('بيانات القيد غير صالحة.')
  ident=data.get('id','')
  version=data.get('version',0)
  if not isinstance(ident,str) or not re.fullmatch(r'COR-[a-zA-Z0-9-]{8,80}',ident) or type(version) is not int or version<0:
   raise ValueError('معرف القيد أو نسخته غير صالح.')
  number_mode=data.get('numberMode','manual')
  if not isinstance(number_mode,str) or number_mode not in {'manual','auto'} or number_mode=='auto' and version!=0:raise ValueError('طريقة ترقيم الكتاب غير صالحة.')
  fields={}
  limits={'direction':8,'agency':300,'documentNumber':100,'documentDate':10,'subject':2000,'notes':4000}
  for key,limit in limits.items():
   value=data.get(key,'')
   if not isinstance(value,str) or len(value)>limit:raise ValueError('تحقق من طول حقول القيد وصيغتها.')
   fields[key]=value.strip()
  if fields['direction'] not in {'incoming','outgoing'}:raise ValueError('نوع السجل غير صالح.')
  if not fields['agency'] or not fields['subject']:raise ValueError('اسم الدائرة والموضوع مطلوبان.')
  for key in ('documentDate',):
   if not fields[key]:continue
   try:
    if datetime.strptime(fields[key],'%Y-%m-%d').date().isoformat()!=fields[key]:raise ValueError()
   except ValueError:raise ValueError('أدخل تاريخًا صالحًا للكتاب.')
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE')
   user=self.correspondence_actor(db,user,'createCorrespondence' if version==0 else 'editCorrespondence')
   old=db.execute('SELECT * FROM correspondence WHERE id=?',(ident,)).fetchone()
   if version==0 and old and old['created_by']==user['id'] and old['version']==1 and not old['deleted']:
    compared={**fields,**({'documentNumber':old['document_number']} if number_mode=='auto' else {})}
    if compared=={key:self.correspondence_public(old)[key] for key in fields}:return {'item':self.correspondence_enriched(db,ident),'created':False}
   if old and (old['deleted'] or old['version']!=version):raise Conflict('تغير القيد بواسطة موظف آخر. أعد فتحه قبل الحفظ.')
   if not old and version!=0:raise Conflict('القيد لم يعد متاحًا. حدّث السجل.')
   if old and old['direction']!=fields['direction']:raise Denied('نوع السجل ثابت للقيد المحفوظ.')
   previous=self.correspondence_public(old) if old else {}
   changed_fields=[key for key,value in fields.items() if value!=previous.get(key)]
   if old and not changed_fields:return {'item':self.correspondence_enriched(db,ident),'created':False,'unchanged':True}
   if number_mode=='auto':fields['documentNumber']=self.next_correspondence_number(db,fields['direction'])
   if not old or old['document_number']!=fields['documentNumber']:
    self.remember_correspondence_number(db,fields['direction'],fields['documentNumber'])
   at=now()
   if old:
    db.execute('UPDATE correspondence SET agency=?,document_number=?,document_date=?,subject=?,notes=?,version=version+1,updated_at=? WHERE id=?',
     (fields['agency'],fields['documentNumber'],fields['documentDate'],fields['subject'],fields['notes'],at,ident))
   else:
    db.execute('INSERT OR IGNORE INTO correspondence_counters(direction,value) VALUES(?,0)',(fields['direction'],))
    db.execute('UPDATE correspondence_counters SET value=value+1 WHERE direction=?',(fields['direction'],))
    serial=db.execute('SELECT value FROM correspondence_counters WHERE direction=?',(fields['direction'],)).fetchone()[0]
    db.execute('INSERT INTO correspondence(id,direction,serial,registered_on,agency,document_number,document_date,subject,notes,version,created_by,created_by_name,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,1,?,?,?,?)',
     (ident,fields['direction'],serial,at[:10],fields['agency'],fields['documentNumber'],fields['documentDate'],fields['subject'],fields['notes'],user['id'],user['name'],at,at))
   label='وارد' if fields['direction']=='incoming' else 'صادر'
   self.audit(db,user,('تعديل قيد ' if old else 'تسجيل قيد ')+label,ident,{'username':user['username'],'changedFields':changed_fields,'version':version+1})
   return {'item':self.correspondence_enriched(db,ident),'created':old is None}
 def delete_correspondence(self,user,ident,version):
  if not isinstance(ident,str) or type(version) is not int or version<1:raise ValueError('معرف القيد أو نسخته غير صالح.')
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE')
   user=self.correspondence_actor(db,user,'deleteCorrespondence')
   old=db.execute('SELECT * FROM correspondence WHERE id=?',(ident,)).fetchone()
   if not old or old['deleted']:raise Conflict('القيد محذوف أو غير موجود.')
   if type(version) is not int or old['version']!=version:raise Conflict('تغيّر القيد منذ فتحه. أعد تحميله قبل الحذف.')
   db.execute('UPDATE correspondence SET deleted=1,version=version+1,updated_at=? WHERE id=?',(now(),ident))
   self.audit(db,user,'حذف قيد '+('وارد' if old['direction']=='incoming' else 'صادر'),ident)
   return {'ok':True}
 def portal_summary(self,user):
  with self.connect() as db:
   user=self.current_actor(db,user)
   purchases=self.has_permission(user,'accessPurchases')
   registry=self.has_permission(user,'viewCorrespondence')
   records=self.records(db,user) if purchases else []
   counts={}
   latest=[]
   if registry:
    counts={row['direction']:row['n'] for row in db.execute('SELECT direction,COUNT(*) n FROM correspondence WHERE deleted=0 GROUP BY direction')}
    latest=[self.correspondence_public(row) for row in db.execute(self.correspondence_select()+' WHERE c.deleted=0 ORDER BY c.updated_at DESC,c.id DESC LIMIT 5')]
   return {'user':user,'purchaseCount':len(records) if purchases else None,'purchasePending':sum(bool(record['routing']['canAct']) for record in records),'correspondenceCounts':counts,'latest':latest}

 def purchase_reference_status(self,user):
  with self.connect() as db:
   user=self.current_actor(db,user)
   if not self.has_permission(user,'accessPurchases'):raise Denied('الدخول إلى طلبات الشراء غير مسموح.')
   row=db.execute("SELECT value FROM meta WHERE key='purchase_reference'").fetchone()
   return json.loads(row[0]) if row else {'configured':False}
 def import_purchase_reference(self,user,parsed):
  from purchase_learning import material_parts,normalized
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE')
   user=self.current_actor(db,user)
   if user['role']!='admin':raise Denied('تحديث مرجع الأعداد والمواد متاح لمدير النظام فقط.')
   previous=db.execute("SELECT value FROM meta WHERE key='purchase_reference'").fetchone()
   if previous and json.loads(previous[0]).get('sha256')==parsed['sha256']:return json.loads(previous[0])
   db.execute('UPDATE purchase_reference_rows SET active=0')
   db.execute("DELETE FROM purchase_material_examples WHERE source='excel'")
   for row in parsed['rows']:
    db.execute('INSERT INTO purchase_reference_rows(source_key,year,number,company,payload,active) VALUES(?,?,?,?,?,1) ON CONFLICT(source_key) DO UPDATE SET payload=excluded.payload,company=excluded.company,active=1',(row['key'],row['year'],row['number'],row['company'],dumps(row)))
    for position,name in enumerate(material_parts(row['details'])):
     db.execute("INSERT OR REPLACE INTO purchase_material_examples VALUES('excel',?,?,?,?,?,?,?,?)",(row['key'],position,row['company'],name,normalized(name),'','',now()))
   for year,number in parsed['maxima'].items():
    db.execute('INSERT INTO purchase_number_counters(year,value) VALUES(?,?) ON CONFLICT(year) DO UPDATE SET value=MAX(value,excluded.value)',(int(year),number))
   for old in db.execute('SELECT payload FROM records').fetchall():
    record=json.loads(old[0]);self.learn_purchase_materials(db,record)
   summary={'configured':True,'sha256':parsed['sha256'],'rows':len(parsed['rows']),'materials':db.execute("SELECT COUNT(DISTINCT normalized) FROM purchase_material_examples WHERE source='excel'").fetchone()[0],'maxima':parsed['maxima'],'duplicates':parsed['duplicates'],'ignored':parsed['ignored'],'updatedAt':now()}
   db.execute("INSERT INTO meta(key,value) VALUES('purchase_reference',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(dumps(summary),))
   self.audit(db,user,'تحديث مرجع أعداد الطلبات والمواد',details={'rows':summary['rows'],'materials':summary['materials'],'duplicates':len(summary['duplicates'])})
   return summary
 def apply_purchase_number(self,db,user,record):
  from purchase_learning import request_year
  tracking=record['tracking'];mode=tracking.get('numberMode','manual');key=tracking.get('sourceKey','')
  if mode not in {'manual','auto','excel','assigned'}:raise ValueError('طريقة ترقيم الطلب غير صالحة.')
  if key:
   source=db.execute('SELECT * FROM purchase_reference_rows WHERE source_key=? AND active=1',(key,)).fetchone()
   if not source:raise ValueError('مرجع العدد غير موجود. حدّث قائمة Excel.')
   if source['company']!=record['company'] and user['role']!='admin':raise Denied('مرجع Excel خارج صلاحية النموذج.')
   if source['year']!=request_year(record['form']['date']):raise ValueError('اختر عددًا من سنة تاريخ الطلب.')
   binding=db.execute('SELECT record_id FROM purchase_source_bindings WHERE source_key=?',(key,)).fetchone()
   if binding and binding['record_id']!=record['id']:raise Conflict('هذا السطر من Excel مرتبط بطلب محفوظ.')
   record['form']['number']=source['number']
   db.execute('INSERT OR REPLACE INTO purchase_source_bindings(record_id,source_key) VALUES(?,?)',(record['id'],key))
   tracking['numberMode']='assigned'
  elif mode=='excel':raise ValueError('اختر طلب الشراء من مرجع Excel.')
  elif mode=='auto':
   if not db.execute("SELECT 1 FROM meta WHERE key='purchase_reference'").fetchone():raise ValueError('مرجع Excel غير مهيأ.')
   year=request_year(record['form']['date'])
   db.execute('INSERT OR IGNORE INTO purchase_number_counters(year,value) VALUES(?,0)',(year,))
   # Continue the workbook sequence; unrelated legacy/manual numbers do not move it.
   # Skip any already saved number in that year while holding the write lock.
   reserved=set()
   for old in db.execute('SELECT payload FROM records'):
    form=json.loads(old[0])['form']
    number=form['number'].strip().translate(str.maketrans('٠١٢٣٤٥٦٧٨٩','0123456789'))
    if number.isdecimal() and request_year(form['date'])==year:reserved.add(int(number))
   number=db.execute('SELECT value FROM purchase_number_counters WHERE year=?',(year,)).fetchone()[0]+1
   while number in reserved:number+=1
   db.execute('UPDATE purchase_number_counters SET value=? WHERE year=?',(number,year))
   record['form']['number']=str(number)
   tracking['numberMode']='assigned'
 def learn_purchase_materials(self,db,record):
  from purchase_learning import normalized
  db.execute("DELETE FROM purchase_material_examples WHERE source='request' AND source_id=?",(record['id'],))
  for position,row in enumerate(record['form']['rows']):
   name=row[0].strip()
   if not name or len(name)>300:continue
   db.execute("INSERT INTO purchase_material_examples VALUES('request',?,?,?,?,?,?,?,?)",(record['id'],position,record['company'],name,normalized(name),row[1],row[2],now()))
 def purchase_assistance(self,user,company,year,query='',sources=False):
  from purchase_learning import normalized,material_parts
  from difflib import SequenceMatcher
  if not isinstance(query,str) or len(query)>200 or not isinstance(year,int) or not 1900<=year<=9999:raise ValueError('بيانات البحث غير صالحة.')
  with self.connect() as db:
   user=self.current_actor(db,user)
   if not self.scope(user,company):raise Denied('النموذج خارج صلاحيات حسابك.')
   if not any(self.has_permission(user,key) for key in ('createRequest','editOwnRequest','editAnyRequest')):raise Denied('اقتراحات الطلبات متاحة لمن يملك صلاحية إنشاء الطلب أو تعديله.')
   configured=bool(db.execute("SELECT 1 FROM meta WHERE key='purchase_reference'").fetchone())
   counter=db.execute('SELECT value FROM purchase_number_counters WHERE year=?',(year,)).fetchone()
   next_number=str((counter[0] if counter else 0)+1)
   if sources:
    conditions='active=1 AND year=? AND (company=?'+(" OR company=''" if user['role']=='admin' else '')+')'
    values=[year,company]
    rows=[]
    used={row[0] for row in db.execute('SELECT source_key FROM purchase_source_bindings')}
    for source in db.execute('SELECT * FROM purchase_reference_rows WHERE '+conditions+' ORDER BY CAST(number AS INTEGER) DESC',values):
     row=json.loads(source['payload'])
     if row['key'] in used:continue
     text=normalized(' '.join(str(row[key]) for key in ('number','requester','toDepartment','details')))
     if query and normalized(query) not in text:continue
     rows.append({**{key:row[key] for key in ('key','number','requester','toDepartment','details','date','sheet','row')},'materials':material_parts(row['details'])})
     if len(rows)==30:break
    return {'configured':configured,'nextNumber':next_number,'sources':rows}
   examples={}
   for row in db.execute("SELECT * FROM purchase_material_examples WHERE company=?"+(" OR company=''" if user['role']=='admin' else '')+" ORDER BY CASE source WHEN 'excel' THEN 0 ELSE 1 END,updated_at,source_id,position",(company,)):
    key=row['normalized']
    if key not in examples:examples[key]={'name':row['name'],'origin':row['origin'],'specifications':row['specifications'],'uses':0,'updatedAt':row['updated_at'],'source':row['source']}
    item=examples[key];item['uses']+=1
    if row['source']=='request':
     item.update(name=row['name'],origin=row['origin'] or item['origin'],specifications=row['specifications'] or item['specifications'],source='request')
    item['updatedAt']=max(item['updatedAt'],row['updated_at'])
   needle=normalized(query)
   ranked=[]
   for key,item in examples.items():
    score=3 if not needle or key.startswith(needle) else 2 if needle in key else SequenceMatcher(None,needle,key).ratio()
    if needle and score<.65:continue
    ranked.append((score,item))
   ranked.sort(key=lambda pair:(pair[0],pair[1]['uses'],pair[1]['updatedAt']),reverse=True)
   return {'configured':configured,'nextNumber':next_number,'items':[item for score,item in ranked[:12]]}
