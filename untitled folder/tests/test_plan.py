import copy,itertools,json,unittest
import server
from test_workflow import Fixture,m

class PurchasePlan(Fixture,unittest.TestCase):
 def plan(self,**changes):
  return self.s.update_workflow_plan(self.admin,{**self.s.workflow_plan(),**changes})['plan']

 def test_default_and_all_combinations_route_to_enabled_stages(self):
  self.assertEqual(self.s.workflow_plan(),m.DEFAULT_WORKFLOW_PLAN)
  warehouse=self.add('warehouse','warehouse')
  for index,(department,finance,stock) in enumerate(itertools.product([False,True],repeat=3)):
   with self.subTest(department=department,finance=finance,stock=stock):
    plan=self.plan(departmentApproval=department,financeApproval=finance,warehouseCheck=stock)
    record=self.draft('PR-plan-'+str(index))
    record=self.action(record,self.requester,'submit')
    self.assertEqual(json.loads(record['tracking']['workflowPlan']),plan)
    if department:
     self.assertEqual(record['tracking']['status'],'submitted')
     record=self.action(record,self.approver,'approve')
    self.assertEqual(record['tracking']['status'],'approved')
    record=self.action(record,self.buyer,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
    if finance:
     self.assertEqual(record['tracking']['status'],'finance_pending')
     record=self.action(record,self.finance,'finance_approve')
    if stock:
     self.assertEqual(record['tracking']['status'],'stock_check')
     record=self.action(record,warehouse,'stock_unavailable')
    self.assertEqual(record['tracking']['status'],'fulfillment')
    self.assertEqual(record['tracking']['fulfillmentQueue'],'purchasing')
    record=self.action(record,self.buyer,'ready')
    record=self.action(record,self.buyer,'deliver')
    record=self.action(record,self.requester,'confirm_receipt')
    self.assertEqual(record['tracking']['status'],'received')

 def test_disabled_stages_do_not_require_staff_and_preview_matches_actual_route(self):
  self.plan(departmentApproval=False,financeApproval=False,warehouseCheck=False)
  self.department('dept-general',managerId='')
  self.update(self.finance,active=False)
  self.update(self.finance2,active=False)
  record=self.draft()
  self.assertEqual(record['routing']['nextStatus'],'approved')
  self.assertEqual(record['routing']['next']['id'],'queue-purchasing')
  record=self.action(record,self.requester,'submit')
  preview=self.s.load(self.buyer)['state']['archives']['a'][0]['routing']
  self.assertEqual(preview['nextStatus'],'fulfillment')
  record=self.action(record,self.buyer,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
  self.assertEqual(record['tracking']['assigneeName'],'قسم المشتريات')

 def test_running_request_keeps_its_plan_and_legacy_defaults(self):
  record=self.advance('approved')
  self.plan(financeApproval=False,warehouseCheck=False)
  record=self.action(record,self.buyer,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
  self.assertEqual(record['tracking']['status'],'finance_pending')
  with self.s.connect() as db:
   record['tracking'].pop('workflowPlan')
   db.execute('UPDATE records SET payload=? WHERE id=?',(m.dumps(record),record['id']))
  self.add('warehouse','warehouse')
  record=self.action(record,self.finance,'finance_approve')
  self.assertEqual(record['tracking']['status'],'stock_check')

 def test_plan_admin_authorization_version_validation_and_restart(self):
  original=self.s.workflow_plan()
  with self.assertRaises(m.Denied):self.s.update_workflow_plan(self.requester,{**original,'financeApproval':False})
  changed=self.plan(financeApproval=False)
  with self.assertRaises(m.Conflict):self.s.update_workflow_plan(self.admin,{**original,'warehouseCheck':False})
  with self.assertRaises(ValueError):self.plan(financeApproval='false')
  reopened=m.Store(self.tmp.name,{'a':'Alpha','b':'Beta'})
  self.assertEqual(reopened.workflow_plan(),changed)
  with self.s.connect() as db:
   event=db.execute("SELECT details FROM audit WHERE action='تعديل خطة طلبات الشراء' ORDER BY seq DESC").fetchone()
   self.assertEqual(json.loads(event[0])['plan'],changed)

 def test_saved_snapshot_cannot_be_forged_and_excel_roundtrip_preserves_it(self):
  record=self.advance('approved')
  view=self.s.load(self.admin)
  view['state']['archives']['a'][0]['tracking']['workflowPlan']=m.dumps({**m.DEFAULT_WORKFLOW_PLAN,'financeApproval':False})
  with self.assertRaises(m.Denied):self.s.save(self.admin,view['state'],view['view'])
  data=server.export_excel({'records':[record],'companies':{'a':'Alpha'}})
  imported=server.import_excel(data)['records'][0]
  self.assertEqual(m.digest(imported),m.digest(record))
  self.assertEqual(imported['tracking']['workflowPlan'],record['tracking']['workflowPlan'])

 def test_resubmitted_request_uses_current_plan(self):
  record=self.advance('submitted')
  record=self.action(record,self.approver,'reject',{'notes':'مراجعة'})
  self.plan(departmentApproval=False,financeApproval=False,warehouseCheck=False)
  record=self.action(record,self.requester,'submit')
  self.assertEqual(record['tracking']['status'],'approved')
  self.assertFalse(json.loads(record['tracking']['workflowPlan'])['departmentApproval'])
