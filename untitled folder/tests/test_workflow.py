import importlib.util,pathlib,tempfile,unittest,copy,json,sqlite3
spec=importlib.util.spec_from_file_location('team_store',pathlib.Path(__file__).resolve().parent.parent/'team_store.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
PASSWORD='test-password-123'
class Fixture:
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=m.Store(self.tmp.name,{'a':'Alpha','b':'Beta'});self.admin=self.s.setup({'username':'admin','name':'Admin','password':PASSWORD});self.requester=self.add('requester','requester');self.approver=self.add('approver','approver');self.buyer=self.add('buyer','buyer');self.finance=self.add('finance','finance');self.buyer2=self.add('buyer2','buyer');self.approver2=self.add('approver2','approver');self.finance2=self.add('finance2','finance');self.department('dept-general',managerId=self.approver['id'])
 def tearDown(self):self.tmp.cleanup()
 def add(self,name,role,scopes=None,department=None,permissions=None):
  d={'username':name,'name':name,'role':role,'scopes':scopes if scopes is not None else ['a'],'password':PASSWORD,'email':name+'@example.com','departmentId':department or {'buyer':'dept-purchasing','finance':'dept-finance','warehouse':'dept-warehouse'}.get(role,'dept-general')}
  if permissions is not None:d['permissions']=permissions
  return self.s.manage_user(self.admin,d)
 def department(self,ident,**changes):
  old=next(x for x in self.s.departments(self.admin) if x['id']==ident);return self.s.manage_department(self.admin,{**old,**changes})
 def fresh(self,u):
  with self.s.connect() as db:return self.s.public(db.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone(),db)
 def update(self,u,**patch):
  d={**self.fresh(u),**patch};d['permissions']=patch.get('permissions',d['permissionOverrides']);return self.s.manage_user(self.admin,d)
 def draft(self,ident='PR-one',who=None,extra=None,status='draft'):
  u=who or self.requester;view=self.s.load(u);r={'id':ident,'company':'a','form':{'number':ident,'date':'2026-11-11','rows':[['Laptop','','','2','','']]},'tracking':{'status':status,'priority':'normal'}}
  if extra:r['tracking'].update(extra)
  view['state']['archives'].setdefault('a',[]).append(r);out=self.s.save(u,view['state'],view['view']);return next(x for x in out['state']['archives']['a'] if x['id']==ident)
 def action(self,r,u,action,patch=None):return self.s.action(u,r['id'],r['revision'],action,patch)['record']
 def advance(self,stage='approved'):
  r=self.draft();r=self.action(r,self.requester,'submit')
  if stage=='submitted':return r
  r=self.action(r,self.approver,'approve')
  if stage=='approved':return r
  r=self.action(r,self.buyer,'priced',{'quoteAmount':'100','currency':'IQD','supplier':'Supplier'})
  if stage=='finance_pending':return r
  warehouse=self.add('stock_clerk','warehouse')
  r=self.action(r,self.finance,'finance_approve')
  if stage=='stock_check':return r
  r=self.action(r,warehouse,'stock_unavailable')
  if stage=='fulfillment':return r
  return self.action(r,self.buyer,'ready')
class Workflow(Fixture,unittest.TestCase):
 def test_complete_flow_shared_departments(self):
  r=self.advance('ordered')
  self.assertEqual(r['tracking']['assigneeName'],'قسم المشتريات')
  self.assertEqual(r['tracking']['fulfillmentQueue'],'purchasing')
  with self.assertRaises(m.Denied):self.action(r,self.requester,'confirm_receipt')
  r=self.action(r,self.buyer2,'deliver')
  self.assertEqual(r['tracking']['status'],'awaiting_receipt')
  self.assertEqual(r['tracking']['assigneeId'],self.requester['id'])
  task=next(item for item in self.s.inbox(self.requester)['items'] if item['pending'])
  self.assertEqual(task['title'],'مطلوب تأكيد استلام طلبك')
  for actor in (self.buyer2,self.admin):
   with self.assertRaises(m.Denied):self.action(r,actor,'confirm_receipt')
  r=self.action(r,self.requester,'confirm_receipt')
  self.assertEqual(r['tracking']['status'],'received')
  self.assertEqual(r['history'][-1]['actorId'],self.requester['id'])
  self.assertFalse(any(item['pending'] for item in self.s.inbox(self.requester)['items']))
  self.assertEqual(len(r['history']),9)
 def test_finance_routes_only_to_warehouse_with_stock_permission(self):
  r=self.advance('finance_pending')
  with self.assertRaisesRegex(ValueError,'قسم المخازن'):
   self.action(r,self.finance,'finance_approve')
  denied=self.add('denied_stock','warehouse',permissions={'checkStock':False})
  warehouse=self.add('stock_clerk','warehouse')
  r=self.action(r,self.finance,'finance_approve')
  self.assertEqual(r['tracking']['status'],'stock_check')
  self.assertEqual(r['tracking']['assigneeName'],'قسم المخازن')
  self.assertEqual(self.s.inbox(warehouse)['items'][0]['title'],'مطلوب التحقق من توفر المواد')
  self.assertFalse(any(item['pending'] for item in self.s.inbox(denied)['items']))
  for actor in (self.buyer,self.finance,denied):
   with self.assertRaises(m.Denied):self.action(r,actor,'stock_available')
 def test_stock_branch_requires_available_destination_and_records_decision_once(self):
  r=self.advance('stock_check')
  clerk=self.add('stock_only','warehouse',permissions={'prepareRequest':False})
  self.update(self.buyer,active=False)
  self.update(self.buyer2,active=False)
  with self.assertRaisesRegex(ValueError,'قسم المشتريات'):
   self.action(r,clerk,'stock_unavailable')
  changed=self.action(r,clerk,'stock_available')
  self.assertEqual(changed['tracking']['fulfillmentQueue'],'warehouse')
  self.assertEqual(changed['history'][-1]['workflowAction'],'stock_available')
  with self.assertRaises(m.Conflict):self.action(r,clerk,'stock_available')
  with self.assertRaises(m.Denied):self.action(changed,clerk,'ready')

 def test_legacy_ordered_keeps_delivery_team_and_waits_for_receipt(self):
  r=self.advance('finance_pending')
  r=self.s.admin_update(self.admin,r['id'],r['revision'],'ordered','',reason='Existing handover pending')['record']
  self.assertEqual(r['tracking']['fulfillmentQueue'],'purchasing')
  r=self.action(r,self.buyer,'deliver')
  self.assertEqual(r['tracking']['status'],'awaiting_receipt')
  r=self.action(r,self.requester,'confirm_receipt')
  self.assertEqual(r['tracking']['status'],'received')
 def test_only_manager_approves(self):
  r=self.advance('submitted')
  for u in [self.admin,self.approver2,self.buyer,self.requester]:
   with self.assertRaises(m.Denied):self.action(r,u,'approve')
 def test_stages_cannot_be_skipped(self):
  r=self.draft()
  for action in ['approve','priced','finance_approve','stock_available','stock_unavailable','ready','deliver','confirm_receipt']:
   with self.assertRaises(m.Denied):self.action(r,self.admin,action)
 def test_quote_required(self):
  r=self.advance('approved')
  for patch in [{},{'quoteAmount':'0','currency':'IQD','supplier':'S'},{'quoteAmount':'NaN','currency':'IQD','supplier':'S'},{'quoteAmount':'10','currency':'EUR','supplier':'S'}]:
   with self.assertRaises(ValueError):self.action(r,self.buyer,'priced',patch)
 def test_reject_reason_and_resubmit(self):
  r=self.advance('submitted')
  with self.assertRaises(ValueError):self.action(r,self.approver,'reject')
  r=self.action(r,self.approver,'reject',{'notes':'Need specs'});r=self.action(r,self.requester,'submit');self.assertEqual(r['tracking']['assigneeId'],self.approver['id'])
 def test_stale_revision(self):
  r=self.advance('approved');self.action(r,self.buyer,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
  with self.assertRaises(m.Conflict):self.action(r,self.buyer2,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
 def test_save_cannot_approve_or_forge_server_fields(self):
  r=self.advance('submitted')
  for key,value in [('status','approved'),('assigneeId',self.admin['id']),('requestDepartmentId','dept-finance')]:
   view=self.s.load(self.admin);view['state']['archives']['a'][0]['tracking'][key]=value
   with self.assertRaises(m.Denied):self.s.save(self.admin,view['state'],view['view'])
 def test_server_history_cannot_be_forged(self):
  r=self.advance('submitted');view=self.s.load(self.admin);record=view['state']['archives']['a'][0];record['history']=[{'action':'FORGED'}];record['form']['recipient']='edited';self.s.save(self.admin,view['state'],view['view'])
  saved=self.s.load(self.admin)['state']['archives']['a'][0];self.assertNotIn('FORGED',str(saved['history']))
 def test_disabled_actor_refreshed(self):
  r=self.advance('submitted');self.update(self.approver,active=False)
  with self.assertRaises(m.Denied):self.action(r,self.approver,'approve')
 def test_auth_password_and_last_admin(self):
  token,csrf,u=self.s.login('requester',PASSWORD,'127.0.0.1');self.assertEqual(self.s.session(token)[0]['id'],self.requester['id']);self.s.logout(token);self.assertIsNone(self.s.session(token))
  with self.assertRaises(m.Denied):self.update(self.admin,role='requester')
 def test_internal_or_routing_evidence_untrusted(self):
  r=self.draft();view=self.s.load(self.admin);record=view['state']['archives']['a'][0];record['_autoAssigned']=[{'actor':'fake'}]
  with self.assertRaises(m.Denied):self.s.save(self.admin,view['state'],view['view'])
if __name__=='__main__':unittest.main()
