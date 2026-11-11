import unittest
from test_workflow import Fixture,m
class IndividualPermissions(Fixture,unittest.TestCase):
 def test_multiple_grants_and_one_deny_coexist(self):
  u=self.update(self.requester,permissions={'createRequest':True,'auditRequests':True,'previewRequest':False})
  self.assertTrue(u['permissions']['createRequest']);self.assertTrue(u['permissions']['auditRequests']);self.assertFalse(u['permissions']['previewRequest'])
  self.assertFalse(u['permissions']['approveFinance']);self.draft(who=u)
 def test_audit_is_independent_and_company_scoped(self):
  auditor=self.add('auditor','viewer',['a'],permissions={'auditRequests':True,'previewRequest':False,'viewCompanyRequests':False})
  a=self.advance('submitted')
  other=self.add('other','requester',['b'])
  env=self.s.load(other);env['state']['archives']['b']=[{'id':'PR-other','company':'b','form':{'number':'002','date':'2026-11-11','rows':[['Item','','','1','','']]},'tracking':{'status':'draft'}}]
  self.s.save(other,env['state'],env['view'])
  events=self.s.audit_log(auditor);self.assertEqual({e['record_id'] for e in events},{a['id']});self.assertTrue(all(e['company']=='a' for e in events));self.assertEqual(self.s.audit_log(auditor,'PR-other'),[])
  self.assertEqual(self.s.load(auditor)['state']['archives'],{})
  self.assertFalse(self.s.has_permission(auditor,'approveDepartment'))
 def test_audit_denied_and_revocation_applies_to_stale_identity(self):
  with self.assertRaises(m.Denied):self.s.audit_log(self.requester)
  old=self.update(self.requester,permissions={'auditRequests':True});self.s.audit_log(old)
  self.update(old,permissions={'auditRequests':False})
  with self.assertRaises(m.Denied):self.s.audit_log(old)
 def test_moved_employee_routes_draft_to_current_department(self):
  r=self.draft();self.update(self.approver2,departmentId='dept-commercial');self.department('dept-commercial',managerId=self.approver2['id'])
  moved=self.update(self.requester,departmentId='dept-commercial',permissions={'editOwnRequest':False})
  preview=self.s.load(moved)['state']['archives']['a'][0]['routing'];self.assertEqual(preview['next']['id'],self.approver2['id'])
  r=self.action(r,moved,'submit');self.assertEqual(r['tracking']['requestDepartmentId'],'dept-commercial');self.assertEqual(r['tracking']['assigneeId'],self.approver2['id'])
  with self.assertRaises(m.Denied):self.action(r,self.approver,'approve')
  self.action(r,self.approver2,'approve')
 def test_submitted_request_retains_department_after_member_moves(self):
  r=self.advance('submitted');self.update(self.requester,departmentId='dept-commercial')
  self.assertEqual(self.s.load(self.approver)['state']['archives']['a'][0]['routing']['current']['id'],self.approver['id'])
  self.action(r,self.approver,'approve')
