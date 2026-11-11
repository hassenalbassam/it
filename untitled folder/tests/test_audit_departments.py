"""Independent reviewer checks for effective denial and shared queue authority."""
import copy,importlib.util,json,pathlib,tempfile,unittest
_spec=importlib.util.spec_from_file_location('audit_store',pathlib.Path(__file__).resolve().parents[1]/'team_store.py')
m=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(m)

class AuditDepartments(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=m.Store(self.tmp.name,{'a':'A','b':'B'});self.admin=self.s.setup({'username':'admin','name':'Admin','password':'long-password-123'})
  self.req=self.add('requester','requester');self.head=self.add('head','approver');self.buyer1=self.add('buyer1','buyer','dept-purchasing');self.buyer2=self.add('buyer2','buyer','dept-purchasing');self.finance=self.add('finance','finance','dept-finance')
  with self.s.connect() as db:dep=self.s.department_public(db,db.execute("SELECT * FROM departments WHERE id='dept-general'").fetchone())
  self.s.manage_department(self.admin,{**dep,'managerId':self.head['id']})
 def tearDown(self):self.tmp.cleanup()
 def add(self,name,role,dept='dept-general',permissions=None):return self.s.manage_user(self.admin,{'username':name,'name':name,'role':role,'scopes':['a'],'password':'long-password-123','departmentId':dept,'permissions':permissions or {}})
 def fresh(self,u):
  with self.s.connect() as db:return self.s.public(db.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone(),db)
 def record(self):
  view=self.s.load(self.req);r={'id':'PR-audit-1','company':'a','savedAt':m.now(),'form':{'number':'Audit-1','date':'2026-11-11','recipient':'A','rows':[['Item','','','1','','']]},'tracking':{'status':'draft','priority':'normal'}};view['state']['archives']={'a':[r]};return self.s.save(self.req,view['state'],view['view'])['state']['archives']['a'][0]
 def action(self,r,u,action,patch=None):return self.s.action(u,r['id'],r['revision'],action,patch)['record']
 def submitted(self):return self.action(self.record(),self.req,'submit')
 def test_manager_explicit_deny_wins_over_inheritance(self):
  self.s.manage_user(self.admin,{**self.head,'permissions':{'approveDepartment':False}});person=self.fresh(self.head);self.assertFalse(person['permissions']['approveDepartment']);r=self.record()
  with self.assertRaises((m.Denied,ValueError)):self.action(r,self.req,'submit')
 def test_purchasing_explicit_deny_wins_over_department_defaults(self):
  self.s.manage_user(self.admin,{**self.buyer2,'permissions':{'priceRequest':False}});r=self.action(self.submitted(),self.head,'approve')
  with self.s.connect() as db:self.assertEqual(self.s.recipient_ids(db,r),{self.buyer1['id']})
  with self.assertRaises(m.Denied):self.action(r,self.buyer2,'priced',{'supplier':'S','quoteAmount':'1','currency':'IQD'})
 def test_queue_two_members_one_transition(self):
  r=self.action(self.submitted(),self.head,'approve')
  with self.s.connect() as db:self.assertEqual(self.s.recipient_ids(db,r),{self.buyer1['id'],self.buyer2['id']})
  self.action(r,self.buyer1,'priced',{'supplier':'S','quoteAmount':'1','currency':'IQD'})
  with self.assertRaises(m.Conflict):self.action(r,self.buyer2,'priced',{'supplier':'S','quoteAmount':'2','currency':'IQD'})
  with self.s.connect() as db:
   saved=json.loads(db.execute('SELECT payload FROM records WHERE id=?',(r['id'],)).fetchone()[0]);self.assertEqual(sum(h.get('toStatus')=='finance_pending' for h in saved['history']),1)
 def test_forged_department_rejected_without_history(self):
  r=self.record();view=self.s.load(self.req);view['state']['archives']['a'][0]['tracking']['requestDepartmentId']='dept-finance'
  with self.assertRaises(m.Denied):self.s.save(self.req,view['state'],view['view'])
 def test_wrong_head_with_explicit_permission_cannot_approve(self):
  other=self.add('otherhead','approver',permissions={'approveDepartment':True});r=self.submitted()
  with self.assertRaises(m.Denied):self.action(r,other,'approve')
 def test_removed_member_stale_object_cannot_act(self):
  r=self.action(self.submitted(),self.head,'approve');self.s.manage_user(self.admin,{**self.buyer2,'departmentId':'dept-general','permissions':{'priceRequest':True}})
  with self.assertRaises(m.Denied):self.action(r,self.buyer2,'priced',{'supplier':'S','quoteAmount':'1','currency':'IQD'})
 def test_permission_schema_rejects_administrative_grant_and_strings(self):
  for permissions in [{'manageUsers':True},{'priceRequest':'false'}]:
   with self.assertRaises(ValueError):self.s.manage_user(self.admin,{**self.buyer2,'permissions':permissions})
 def test_concurrent_queue_decisions_one_commit(self):
  from concurrent.futures import ThreadPoolExecutor
  from threading import Barrier
  r=self.action(self.submitted(),self.head,'approve');barrier=Barrier(2)
  def attempt(user):
   barrier.wait()
   try:self.action(r,user,'priced',{'supplier':'S','quoteAmount':'1','currency':'IQD'});return 'ok'
   except m.Conflict:return 'conflict'
  with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,[self.buyer1,self.buyer2]))
  self.assertEqual(sorted(results),['conflict','ok'])
  with self.s.connect() as db:
   saved=json.loads(db.execute('SELECT payload FROM records WHERE id=?',(r['id'],)).fetchone()[0]);self.assertEqual(sum(h.get('toStatus')=='finance_pending' for h in saved['history']),1)
   recipients={x[0] for x in db.execute('SELECT recipient_id FROM email_outbox WHERE event_key LIKE ?',(r['id']+':'+str(saved['revision'])+':%',))};self.assertEqual(recipients,{self.req['id'],self.finance['id']})
 def test_deleted_department_preserves_reference_and_uses_replacement_manager(self):
  r=self.submitted();newhead=self.add('replacementhead','approver')
  replacement=self.s.manage_department(self.admin,{'name':'Replacement','kind':'general','members':[newhead['id']],'managerId':newhead['id']})
  with self.s.connect() as db:
   source=self.s.department_public(db,db.execute("SELECT * FROM departments WHERE id='dept-general'").fetchone());before=db.execute('SELECT payload FROM records WHERE id=?',(r['id'],)).fetchone()[0]
  self.s.delete_department(self.admin,source['id'],source['version'],replacement['id'])
  with self.s.connect() as db:
   after=db.execute('SELECT payload FROM records WHERE id=?',(r['id'],)).fetchone()[0];self.assertEqual(before,after);self.assertEqual(self.s.routing(db,json.loads(after))['id'],newhead['id'])
  with self.assertRaises(m.Denied):self.action(r,self.head,'approve')
  result=self.action(r,newhead,'approve');self.assertEqual(result['tracking']['status'],'approved')
 def test_delete_stale_version_does_not_move_members(self):
  with self.s.connect() as db:source=self.s.department_public(db,db.execute("SELECT * FROM departments WHERE id='dept-general'").fetchone())
  changed=self.s.manage_department(self.admin,{**source,'name':'Renamed'})
  with self.assertRaises(m.Conflict):self.s.delete_department(self.admin,source['id'],source['version'],'dept-commercial')
  self.assertEqual(self.fresh(self.req)['departmentId'],'dept-general')
if __name__=='__main__':unittest.main()
