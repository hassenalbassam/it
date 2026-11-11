import unittest,json
from test_workflow import Fixture,m
class AdminRoles(Fixture,unittest.TestCase):
 def override(self,r,status,assignee='',patch=None,reason='سبب تعديل إداري موثق'):return self.s.admin_update(self.admin,r['id'],r['revision'],status,assignee,patch,reason)['record']
 def test_admin_override_jump_reopen(self):
  r=self.draft();r=self.override(r,'received');r=self.override(r,'submitted',self.approver2['id']);self.assertEqual(r['tracking']['assigneeId'],self.approver2['id']);self.assertEqual(r['history'][-1]['kind'],'admin_override');r=self.action(r,self.approver2,'approve');self.assertEqual(r['tracking']['assigneeId'],'');self.assertNotIn('manualAssigneeId',r['tracking'])
 def test_admin_own_request_can_override_not_ordinary_selfapprove(self):
  r=self.draft(who=self.admin);r=self.override(r,'finance_pending',self.admin['id']);self.assertEqual(r['tracking']['assigneeId'],self.admin['id'])
  with self.assertRaises(m.Denied):self.action(r,self.admin,'finance_approve')
  r=self.override(r,'received');self.assertEqual(r['tracking']['status'],'received')
 def test_reason_role_and_revision(self):
  r=self.draft()
  with self.assertRaises(ValueError):self.override(r,'received',reason='')
  with self.assertRaises(m.Denied):self.s.admin_update(self.requester,r['id'],r['revision'],'received','',{},'سبب')
  self.override(r,'received')
  with self.assertRaises(m.Conflict):self.override(r,'draft')
 def test_any_status_admin_content_edit_and_delete(self):
  r=self.draft();r=self.override(r,'received');view=self.s.load(self.admin);view['state']['archives']['a'][0]['form']['recipient']='admin';out=self.s.save(self.admin,view['state'],view['view']);self.assertEqual(out['state']['archives']['a'][0]['form']['recipient'],'admin');out['state']['archives']['a']=[];self.assertFalse(self.s.save(self.admin,out['state'],out['view'])['state']['archives'])
 def test_manual_disabled_needs_admin_reassignment(self):
  r=self.advance('submitted');r=self.override(r,'submitted',self.approver2['id']);self.update(self.approver2,active=False)
  with self.assertRaises((ValueError,m.Denied)):self.action(r,self.approver,'approve')
  r=self.override(r,'submitted',self.approver['id']);self.action(r,self.approver,'approve')
 def test_admin_mgmt_cannot_be_granted_as_business_permission(self):
  with self.assertRaises(ValueError):self.update(self.requester,permissions={'manageUsers':True})
  with self.assertRaises(m.Denied):self.s.manage_user(self.buyer,{**self.buyer,'role':'admin'})
 def test_admin_all_permissions_not_denied_by_override(self):
  admin=self.update(self.admin,permissions={'priceRequest':False,'approveFinance':False});self.assertTrue(all(admin['permissions'].values()))
 def test_admin_event_audit_and_transactional_notification(self):
  r=self.draft();r=self.override(r,'approved',self.buyer2['id'])
  with self.s.connect() as db:
   audit=json.loads(db.execute('SELECT details FROM audit WHERE record_id=? ORDER BY seq DESC',(r['id'],)).fetchone()[0]);self.assertEqual(audit['kind'],'admin_override');self.assertTrue(audit['reason']);ids={x[0] for x in db.execute('SELECT recipient_id FROM email_outbox WHERE event_key LIKE ?',(r['id']+':'+str(r['revision'])+':%',))};self.assertEqual(ids,{self.requester['id'],self.buyer2['id']})
if __name__=='__main__':unittest.main()
