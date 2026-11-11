import unittest,json,copy,sqlite3,tempfile,pathlib,threading
from test_workflow import Fixture,m,PASSWORD
class Departments(Fixture,unittest.TestCase):
 def create_dept(self,name,kind='general',members=None,manager=''):
  return self.s.manage_department(self.admin,{'name':name,'kind':kind,'members':members or [],'managerId':manager})
 def test_manager_of_creator_department_only(self):
  requester=self.add('secondrequester','requester');head=self.add('secondhead','requester');dep=self.create_dept('الهندسة',members=[requester['id'],head['id']],manager=head['id']);r=self.draft(who=self.fresh(requester));r=self.action(r,self.fresh(requester),'submit');self.assertEqual(r['tracking']['requestDepartmentId'],dep['id']);self.assertEqual(r['tracking']['assigneeId'],head['id'])
  with self.assertRaises(m.Denied):self.action(r,self.approver,'approve')
  r=self.action(r,self.fresh(head),'approve');self.assertEqual(r['tracking']['assigneeName'],'قسم المشتريات')
 def test_all_purchasing_and_finance_members_notified(self):
  r=self.advance('approved')
  with self.s.connect() as db:ids={x[0] for x in db.execute('SELECT recipient_id FROM email_outbox WHERE event_key LIKE ?',(r['id']+':'+str(r['revision'])+':%',))};self.assertEqual(ids,{self.requester['id'],self.buyer['id'],self.buyer2['id']})
  r=self.action(r,self.buyer2,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
  with self.s.connect() as db:ids={x[0] for x in db.execute('SELECT recipient_id FROM email_outbox WHERE event_key LIKE ?',(r['id']+':'+str(r['revision'])+':%',))};self.assertEqual(ids,{self.requester['id'],self.finance['id'],self.finance2['id']})
  warehouse=self.add('warehouse','warehouse')
  r=self.action(r,self.finance2,'finance_approve')
  with self.s.connect() as db:ids={x[0] for x in db.execute('SELECT recipient_id FROM email_outbox WHERE event_key LIKE ?',(r['id']+':'+str(r['revision'])+':%',))};self.assertEqual(ids,{self.requester['id'],warehouse['id']})
 def test_concurrent_first_queue_action_wins(self):
  r=self.advance('approved');barrier=threading.Barrier(2);results=[]
  def attempt(user):
   barrier.wait()
   try:results.append(self.action(r,user,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})['tracking']['status'])
   except m.Conflict:results.append('conflict')
  threads=[threading.Thread(target=attempt,args=(u,)) for u in [self.buyer,self.buyer2]]
  for t in threads:t.start()
  for t in threads:t.join(10)
  self.assertCountEqual(results,['finance_pending','conflict'])
 def test_per_person_deny_overrides_department_and_role(self):
  self.update(self.buyer,permissions={'priceRequest':False});r=self.advance('submitted');r=self.action(r,self.approver,'approve');out=self.s.load(self.buyer);self.assertFalse(out['state']['archives']['a'][0]['routing']['canAct'])
  with self.assertRaises(m.Denied):self.action(r,self.buyer,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
  self.action(r,self.buyer2,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
 def test_role_viewer_custom_grant_can_act_in_department(self):
  viewer=self.add('viewer','viewer',department='dept-purchasing',permissions={'priceRequest':True});r=self.advance('approved');self.action(r,viewer,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
 def test_default_viewer_no_business_rights(self):
  viewer=self.add('viewer','viewer',department='dept-purchasing');r=self.advance('approved')
  with self.assertRaises(m.Denied):self.action(r,viewer,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
 def test_disabled_outscope_and_nonmember_excluded(self):
  outsider=self.add('outsider','buyer',['b']);nonmember=self.add('nonmember','buyer',department='dept-general');self.update(self.buyer,active=False);r=self.advance('submitted');r=self.action(r,self.approver,'approve')
  with self.s.connect() as db:ids=self.s.recipient_ids(db,r)
  self.assertEqual(ids,{self.buyer2['id']})
  for user in [outsider,nonmember,self.buyer]:
   with self.assertRaises(m.Denied):self.action(r,user,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
 def test_manager_change_effective_without_record_rewrite(self):
  r=self.advance('submitted');self.department('dept-general',managerId=self.approver2['id'])
  with self.assertRaises(m.Denied):self.action(r,self.approver,'approve')
  self.action(r,self.approver2,'approve')
 def test_membership_promotion_effective(self):
  r=self.advance('approved');self.update(self.buyer,departmentId='dept-general');new=self.add('newbuyer','requester',department='dept-purchasing')
  with self.assertRaises(m.Denied):self.action(r,self.buyer,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
  self.action(r,new,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
 def test_department_members_replace_atomic_version_and_manager(self):
  dep=next(d for d in self.s.departments(self.admin) if d['id']=='dept-purchasing');bad={**dep,'members':[self.buyer['id']],'managerId':self.buyer2['id']}
  with self.assertRaises(ValueError):self.s.manage_department(self.admin,bad)
  self.assertEqual(next(d for d in self.s.departments(self.admin) if d['id']==dep['id'])['members'],dep['members']);updated=self.s.manage_department(self.admin,{**dep,'members':[self.buyer['id']],'managerId':self.buyer['id']});self.assertEqual(self.fresh(self.buyer2)['departmentId'],'')
  with self.assertRaises(m.Conflict):self.s.manage_department(self.admin,dep)
 def test_manager_explicit_deny_wins_and_create_assignment_denied(self):
  self.update(self.approver,permissions={'approveDepartment':False});r=self.draft()
  with self.assertRaises(ValueError):self.action(r,self.requester,'submit')
  with self.assertRaises(ValueError):self.department('dept-general',managerId=self.approver['id'])
 def test_missing_finance_does_not_block_head_but_pricing_rolls_back(self):
  self.update(self.finance,active=False);self.update(self.finance2,active=False);r=self.advance('approved')
  with self.s.connect() as db:before=tuple(db.execute('SELECT payload,version FROM records WHERE id=?',(r['id'],)).fetchone());count=db.execute('SELECT count(*) FROM email_outbox').fetchone()[0]
  with self.assertRaisesRegex(ValueError,'قسم المالية'):self.action(r,self.buyer,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
  with self.s.connect() as db:self.assertEqual(before,tuple(db.execute('SELECT payload,version FROM records WHERE id=?',(r['id'],)).fetchone()));self.assertEqual(count,db.execute('SELECT count(*) FROM email_outbox').fetchone()[0])
 def test_finance_added_later_resumes_queue(self):
  self.update(self.finance,active=False);self.update(self.finance2,active=False);r=self.advance('approved');finance=self.add('laterfinance','requester',department='dept-finance');self.add('warehouse','warehouse');r=self.action(r,self.buyer,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'});self.action(r,finance,'finance_approve')
 def test_self_approval_blocked_for_manager_and_finance(self):
  r=self.draft(who=self.fresh(self.approver)) if self.fresh(self.approver)['permissions']['createRequest'] else None
  head=self.update(self.approver,permissions={'createRequest':True,'submitRequest':True});r=self.draft('PR-head',who=head)
  with self.assertRaises(m.Denied):self.action(r,head,'submit')
  fin=self.update(self.finance,permissions={'createRequest':True,'submitRequest':True});self.department('dept-finance',managerId=self.finance2['id']);r=self.draft('PR-fin',who=fin);r=self.action(r,fin,'submit');r=self.action(r,self.finance2,'approve');r=self.action(r,self.buyer,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
  with self.assertRaises(m.Denied):self.action(r,fin,'finance_approve')
 def test_warehouse_group_pinned_for_delivery(self):
  warehouse=self.add('warehouse','warehouse');warehouse2=self.add('warehouse2','requester',department='dept-warehouse');r=self.advance('stock_check');r=self.action(r,warehouse,'stock_available');self.assertEqual(r['tracking']['fulfillmentQueue'],'warehouse');r=self.action(r,warehouse,'ready')
  with self.assertRaises(m.Denied):self.action(r,self.buyer,'deliver')
  r=self.action(r,warehouse2,'deliver')
  self.assertEqual(r['tracking']['status'],'awaiting_receipt')
  with self.s.connect() as db:ids={x[0] for x in db.execute('SELECT recipient_id FROM email_outbox WHERE event_key LIKE ?',(r['id']+':'+str(r['revision'])+':%',))};self.assertEqual(ids,{self.requester['id']})
  self.action(r,self.requester,'confirm_receipt')
 def test_request_department_cannot_be_forged(self):
  with self.assertRaises(m.Denied):self.draft(extra={'requestDepartmentId':'dept-finance'})
 def test_custom_create_edit_delete_and_submit_permissions(self):
  self.update(self.requester,permissions={'createRequest':False})
  with self.assertRaises(m.Denied):self.draft()
  self.update(self.requester,permissions={});r=self.draft();self.update(self.requester,permissions={'submitRequest':False})
  with self.assertRaises(m.Denied):self.action(r,self.requester,'submit')
  self.update(self.requester,permissions={'deleteRequest':False});view=self.s.load(self.requester);view['state']['archives']['a']=[]
  with self.assertRaises(m.Denied):self.s.save(self.requester,view['state'],view['view'])
 def test_directory_catalog_no_secrets_and_effective_permissions(self):
  rows=self.s.directory(self.requester);self.assertTrue(all('permissions' in r and 'departmentId' in r for r in rows));self.assertTrue(all('email' not in r and 'password' not in r for r in rows));self.assertEqual(set(self.s.permission_catalog()['roleDefaults']['requester']),set(m.PERMISSIONS))
 def test_migration_preserves_records_and_maps_roles(self):
  with tempfile.TemporaryDirectory() as folder:
   dbpath=pathlib.Path(folder)/'team.sqlite3'
   with sqlite3.connect(dbpath) as db:
    db.execute('CREATE TABLE users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,name TEXT NOT NULL,role TEXT NOT NULL,scopes TEXT NOT NULL,password TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created TEXT NOT NULL)')
    for ident,role in [('head','approver'),('buyer','buyer'),('finance','finance'),('req','requester')]:db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?)',(ident,ident,ident,role,'["a"]','fake',1,'2026'))
    db.execute('CREATE TABLE records(id TEXT PRIMARY KEY,company TEXT NOT NULL,creator TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL)');payload=m.dumps({'id':'PR-old','company':'a','createdBy':'req','form':{'number':'1','date':'2026-11-11','rows':[['x','','','','','']]},'tracking':{'status':'submitted'}});db.execute('INSERT INTO records VALUES(?,?,?,?,?)',('PR-old','a','req',1,payload))
   store=m.Store(folder,{'a':'Alpha'})
   with store.connect() as db:
    self.assertEqual(db.execute('SELECT payload FROM records').fetchone()[0],payload);self.assertEqual(db.execute("SELECT manager_id FROM departments WHERE id='dept-general'").fetchone()[0],'head');self.assertEqual(db.execute("SELECT department_id FROM users WHERE id='buyer'").fetchone()[0],'dept-purchasing');record=json.loads(payload);self.assertEqual(store.routing(db,record)['memberIds'],['head'])
 def test_legacy_department_without_manager_stays_in_its_department(self):
  r=self.advance('submitted');r['tracking'].pop('requestDepartmentId',None);self.update(self.requester,departmentId='dept-finance')
  with self.s.connect() as db:db.execute('UPDATE records SET payload=? WHERE id=?',(m.dumps(r),r['id']))
  with self.assertRaisesRegex(ValueError,'قسم المالية'):self.action(r,self.approver,'approve')
  self.department('dept-finance',managerId=self.finance['id']);self.action(r,self.finance,'approve')
 def test_exact_nine_seed_order_and_independent_commercial(self):
  rows=self.s.departments(self.admin);self.assertEqual([r['name'] for r in rows],['قسم تكنولوجيا المعلومات','القسم التجاري','قسم المالية','قسم المخازن','قسم المحاسبة','أرض الأسود','القسم القانوني','قسم العلاقات','قسم المشتريات']);self.assertEqual([r['sortOrder'] for r in rows],list(range(1,10)));self.assertEqual(rows[1]['kind'],'general');self.assertEqual(rows[-1]['kind'],'purchasing');self.assertEqual(self.fresh(self.buyer)['departmentId'],'dept-purchasing')
 def test_rename_and_custom_add_persist_across_restart(self):
  self.department('dept-commercial',name='تجاري جديد');custom=self.create_dept('قسم مضاف');self.assertEqual(custom['sortOrder'],10);reopened=m.Store(self.tmp.name,{'a':'Alpha','b':'Beta'});self.assertEqual(next(d for d in reopened.departments(self.admin) if d['id']=='dept-commercial')['name'],'تجاري جديد')
 def test_delete_linked_requires_replacement_and_preserves_history(self):
  r=self.advance('submitted');source=next(d for d in self.s.departments(self.admin) if d['id']=='dept-general')
  with self.assertRaises(ValueError):self.s.delete_department(self.admin,source['id'],source['version'])
  nexthead=self.add('newhead','requester');target=self.create_dept('القسم البديل',members=[nexthead['id']],manager=nexthead['id']);source=next(d for d in self.s.departments(self.admin) if d['id']=='dept-general')
  with self.s.connect() as db:payload=db.execute('SELECT payload FROM records WHERE id=?',(r['id'],)).fetchone()[0]
  result=self.s.delete_department(self.admin,source['id'],source['version'],target['id']);self.assertTrue(result['deleted']);self.assertEqual(result['linkedRequests'],1);self.assertEqual(self.fresh(self.requester)['departmentId'],target['id']);self.assertNotIn('dept-general',[d['id'] for d in self.s.departments(self.admin)])
  with self.s.connect() as db:self.assertEqual(db.execute('SELECT payload FROM records WHERE id=?',(r['id'],)).fetchone()[0],payload)
  self.action(r,self.fresh(nexthead),'approve')
 def test_delete_unlinked_no_replacement_and_no_reseed(self):
  row=next(d for d in self.s.departments(self.admin) if d['id']=='dept-commercial');self.s.delete_department(self.admin,row['id'],row['version']);reopened=m.Store(self.tmp.name,{'a':'Alpha','b':'Beta'});self.assertNotIn(row['id'],[d['id'] for d in reopened.departments(self.admin)])
 def test_delete_permissions_stale_self_and_inactive_target(self):
  row=next(d for d in self.s.departments(self.admin) if d['id']=='dept-commercial')
  with self.assertRaises(m.Denied):self.s.delete_department(self.requester,row['id'],row['version'])
  with self.assertRaises(ValueError):self.s.delete_department(self.admin,row['id'],row['version'],row['id'])
  self.department(row['id'],name='renamed')
  with self.assertRaises(m.Conflict):self.s.delete_department(self.admin,row['id'],row['version'])
 def test_delete_and_edit_permissions_are_independent(self):
  r=self.draft();user=self.update(self.requester,permissions={'editOwnRequest':False,'deleteRequest':True});self.assertFalse(self.s.editable(user,r));self.assertTrue(self.s.deletable(user,r));view=self.s.load(user);view['state']['archives']['a']=[];self.assertFalse(self.s.save(user,view['state'],view['view'])['state']['archives'])
if __name__=='__main__':unittest.main()
