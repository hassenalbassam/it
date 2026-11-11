import itertools,json,unittest
from test_workflow import Fixture,m

class AllWorkflowStages(Fixture,unittest.TestCase):
 def plan(self,**changes):
  return self.s.update_workflow_plan(self.admin,{**self.s.workflow_plan(),**changes})['plan']
 def only(self,*enabled):
  return self.plan(**{key:key in enabled for key in m.WORKFLOW_OPTIONS})

 def test_all_512_combinations_advance_only_to_enabled_stages(self):
  actions={'submitted':'approve','approved':'priced','finance_pending':'finance_approve','stock_check':'stock_unavailable','fulfillment':'ready','ordered':'deliver','awaiting_receipt':'confirm_receipt'}
  with self.s.connect() as db:
   for selected in itertools.product([False,True],repeat=len(m.WORKFLOW_OPTIONS)):
    plan={**m.DEFAULT_WORKFLOW_PLAN,**dict(zip(m.WORKFLOW_OPTIONS,selected))}
    expected=[status for status,key in m.WORKFLOW_STAGE_OPTIONS if plan[key]]
    status=self.s.following_workflow_stage(plan,'draft')
    visited=[]
    while status not in {'received','closed'}:
     visited.append(status)
     record={'tracking':{'status':status,'workflowPlan':m.dumps(plan)}}
     status=self.s.workflow_target(db,record,actions[status])
    self.assertEqual(visited,expected)
    self.assertEqual(status,'received' if plan['completion'] else 'closed')

 def test_finance_without_pricing_and_receipt_without_completion(self):
  self.only('requestCreation','financeApproval','receiptConfirmation')
  record=self.action(self.draft(),self.requester,'submit')
  self.assertEqual(record['tracking']['status'],'finance_pending')
  record=self.action(record,self.finance,'finance_approve')
  self.assertEqual(record['tracking']['status'],'awaiting_receipt')
  record=self.action(record,self.requester,'confirm_receipt')
  self.assertEqual(record['tracking']['status'],'closed')
  self.assertEqual(record['history'][-1]['workflowAction'],'confirm_receipt')

 def test_skip_confirmation_closes_after_delivery_without_receipt_claim(self):
  self.only('requestCreation','readyForDelivery','completion')
  record=self.action(self.draft(),self.requester,'submit')
  self.assertEqual(record['tracking']['status'],'ordered')
  self.assertEqual(record['tracking']['fulfillmentQueue'],'purchasing')
  record=self.action(record,self.buyer,'deliver')
  self.assertEqual(record['tracking']['status'],'received')
  inbox=self.s.inbox(self.requester)
  self.assertFalse(any(item['pending'] for item in inbox['items']))
  self.assertNotIn('تأكيد الاستلام',inbox['items'][0]['message'])
  with self.assertRaises(m.Denied):self.action(record,self.requester,'confirm_receipt')

 def test_skip_creation_autosubmits_and_available_stock_routes_delivery_team(self):
  self.only('warehouseCheck','readyForDelivery')
  warehouse=self.add('warehouse','warehouse')
  record=self.draft()
  self.assertEqual(record['tracking']['status'],'stock_check')
  record=self.action(record,warehouse,'stock_available')
  self.assertEqual(record['tracking']['status'],'ordered')
  self.assertEqual(record['tracking']['fulfillmentQueue'],'warehouse')
  with self.assertRaises(m.Denied):self.action(record,self.buyer,'deliver')
  record=self.action(record,warehouse,'deliver')
  self.assertEqual(record['tracking']['status'],'closed')

 def test_all_skipped_ends_immediately_and_respects_submit_permission(self):
  self.only()
  record=self.draft()
  self.assertEqual(record['tracking']['status'],'closed')
  self.assertFalse(any(item['pending'] for item in self.s.inbox(self.requester)['items']))
  self.update(self.requester,permissions={'submitRequest':False})
  with self.assertRaises(m.Denied):self.draft('PR-denied')
  self.assertEqual(len(self.s.load(self.requester)['state']['archives']['a']),1)

 def test_legacy_plan_fields_are_expanded_without_changing_snapshot(self):
  old={'version':1,'departmentApproval':True,'financeApproval':False,'warehouseCheck':True}
  with self.s.connect() as db:
   db.execute("INSERT INTO meta(key,value) VALUES('purchase_workflow',?)",(m.dumps(old),))
  settings=self.s.workflow_plan()
  self.assertFalse(settings['financeApproval'])
  self.assertTrue(settings['purchasePricing'])
  record=self.draft()
  record=self.action(record,self.requester,'submit')
  with self.s.connect() as db:
   record['tracking']['workflowPlan']=m.dumps(old)
   db.execute('UPDATE records SET payload=? WHERE id=?',(m.dumps(record),record['id']))
  self.plan(purchasePricing=False)
  record=self.action(record,self.approver,'approve')
  self.assertEqual(record['tracking']['status'],'approved')
  self.assertEqual(record['tracking']['workflowPlan'],m.dumps(old))
