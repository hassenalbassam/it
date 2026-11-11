import itertools,unittest
from test_workflow import Fixture,m

class StageOrder(Fixture,unittest.TestCase):
 def reorder(self,order):
  return self.s.update_workflow_plan(self.admin,{**self.s.workflow_plan(),'stageOrder':list(order)})['plan']

 def test_every_order_visits_each_enabled_stage_once(self):
  status_by_option={option:status for status,option in m.WORKFLOW_STAGE_OPTIONS}
  with self.s.connect() as db:
   for order in itertools.permutations(m.DEFAULT_STAGE_ORDER):
    plan={**m.DEFAULT_WORKFLOW_PLAN,'stageOrder':list(order)}
    status=self.s.following_workflow_stage(plan,'draft')
    visited=[]
    for _ in range(len(order)):
     visited.append(status)
     status=self.s.following_workflow_stage(plan,status)
    self.assertEqual(visited,[status_by_option[key] for key in order])
    self.assertEqual(status,'received')

 def test_finance_and_warehouse_before_pricing_preserve_available_and_unavailable_routes(self):
  warehouse=self.add('warehouse','warehouse')
  self.reorder(['financeApproval','warehouseCheck','purchasePricing','departmentApproval','preparation','readyForDelivery','receiptConfirmation'])
  for index,available in enumerate([True,False]):
   record=self.action(self.draft('PR-reorder-'+str(index)),self.requester,'submit')
   self.assertEqual(record['tracking']['status'],'finance_pending')
   record=self.action(record,self.finance,'finance_approve')
   self.assertEqual(record['tracking']['status'],'stock_check')
   record=self.action(record,warehouse,'stock_available' if available else 'stock_unavailable')
   self.assertEqual(record['tracking']['status'],'approved')
   queue='warehouse' if available else 'purchasing'
   self.assertEqual(record['tracking']['fulfillmentQueue'],queue)
   record=self.action(record,self.buyer,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
   self.assertEqual(record['tracking']['status'],'submitted')
   record=self.action(record,self.approver,'approve')
   self.assertEqual(record['tracking']['status'],'fulfillment')
   self.assertEqual(record['tracking']['fulfillmentQueue'],queue)
   preparer=warehouse if available else self.buyer
   record=self.action(record,preparer,'ready')
   record=self.action(record,preparer,'deliver')
   record=self.action(record,self.requester,'confirm_receipt')
   self.assertEqual(record['tracking']['status'],'received')

 def test_order_only_changes_are_saved_and_running_request_stays_on_original_order(self):
  record=self.advance('submitted')
  original=self.s.workflow_plan()
  order=list(reversed(m.DEFAULT_STAGE_ORDER))
  saved=self.reorder(order)
  self.assertEqual(saved['version'],original['version']+1)
  reopened=m.Store(self.tmp.name,{'a':'Alpha','b':'Beta'})
  self.assertEqual(reopened.workflow_plan()['stageOrder'],order)
  record=self.action(record,self.approver,'approve')
  self.assertEqual(record['tracking']['status'],'approved')

 def test_invalid_and_duplicate_orders_rejected_and_older_plan_expands(self):
  plan=self.s.workflow_plan()
  for order in [[],list(m.DEFAULT_STAGE_ORDER)[:-1],['financeApproval']*7,list(m.DEFAULT_STAGE_ORDER[:-1])+['unknown'],None]:
   with self.assertRaises(ValueError):self.s.update_workflow_plan(self.admin,{**plan,'stageOrder':order})
  legacy={key:value for key,value in plan.items() if key!='stageOrder'}
  normalized=self.s.valid_workflow_plan(legacy)
  self.assertEqual(normalized['stageOrder'],list(m.DEFAULT_STAGE_ORDER))

 def test_disabled_stages_keep_relative_order(self):
  plan=self.s.workflow_plan()
  plan.update({key:False for key in m.WORKFLOW_OPTIONS})
  plan.update(financeApproval=True,purchasePricing=True,completion=True)
  plan['stageOrder']=['financeApproval','warehouseCheck','purchasePricing','departmentApproval','preparation','readyForDelivery','receiptConfirmation']
  self.s.update_workflow_plan(self.admin,plan)
  record=self.draft()
  self.assertEqual(record['tracking']['status'],'finance_pending')
  record=self.action(record,self.finance,'finance_approve')
  self.assertEqual(record['tracking']['status'],'approved')
  record=self.action(record,self.buyer,'priced',{'quoteAmount':'10','currency':'IQD','supplier':'S'})
  self.assertEqual(record['tracking']['status'],'received')
