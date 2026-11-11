import unittest
from test_workflow import Fixture,m

class Inbox(Fixture,unittest.TestCase):
 def test_workflow_tasks_and_read_markers_are_personal(self):
  record=self.advance('approved')
  first=self.s.inbox(self.buyer)
  second=self.s.inbox(self.buyer2)
  task=first['items'][0]
  self.assertEqual(task['title'],'مطلوب تسعير الطلب')
  self.assertEqual(task['id'],second['items'][0]['id'])
  with self.assertRaises(m.Denied):self.s.read_inbox(self.finance,task['id'])
  self.s.read_inbox(self.buyer,task['id'])
  self.assertEqual(self.s.inbox(self.buyer)['unread'],0)
  self.assertEqual(self.s.inbox(self.buyer2)['unread'],1)
  self.action(record,self.buyer2,'priced',{'supplier':'S','quoteAmount':'10','currency':'IQD'})
  self.assertEqual(self.s.inbox(self.buyer)['items'],[])
  self.assertEqual(self.s.inbox(self.finance)['items'][0]['title'],'مطلوب قرار المالية')

 def test_rejection_is_reported_to_request_owner(self):
  record=self.advance('submitted')
  self.action(record,self.approver,'reject',{'notes':'المواصفات ناقصة'})
  item=self.s.inbox(self.requester)['items'][0]
  self.assertEqual(item['title'],'رُفض طلبك')
  self.assertIn('المواصفات ناقصة',item['message'])
  self.assertEqual(self.s.inbox(self.approver)['items'],[])

 def test_preview_task_grants_only_document_view_and_records_completion(self):
  record=self.draft()
  person=self.add('previewer','requester')
  task=self.s.request_preview(self.requester,record['id'],record['revision'],person['id'],'راجع المواصفات')
  self.assertEqual(self.s.request_preview(self.requester,record['id'],record['revision'],person['id'])['id'],task['id'])
  self.assertEqual(self.s.load(person)['state']['archives'],{})
  self.assertEqual(self.s.inbox(person)['items'][0]['taskId'],task['id'])
  with self.assertRaises(m.Denied):self.s.preview_task(self.approver,task['id'])
  with self.assertRaises(m.Denied):self.s.complete_preview(self.approver,task['id'],record['revision'])
  preview=self.s.preview_task(person,task['id'])['record']
  self.s.complete_preview(person,task['id'],preview['revision'])
  self.assertTrue(self.s.preview_task(person,task['id'])['completed'])
  self.assertEqual(self.s.inbox(person)['unread'],0)
  self.assertEqual(self.s.inbox(self.requester)['items'][0]['title'],'اكتملت معاينة طلبك')

 def test_preview_permission_and_scope_are_rechecked(self):
  record=self.draft()
  denied=self.add('nopreview','viewer',permissions={'previewRequest':False})
  outsider=self.add('outside','viewer',scopes=['b'])
  for person in [denied,outsider]:
   with self.assertRaises(m.Denied):
    self.s.request_preview(self.requester,record['id'],record['revision'],person['id'])
  person=self.add('previewer','viewer')
  task=self.s.request_preview(self.requester,record['id'],record['revision'],person['id'])
  self.update(person,permissions={'previewRequest':False})
  self.assertEqual(self.s.inbox(person)['items'],[])
  with self.assertRaises(m.Denied):self.s.preview_task(person,task['id'])

 def test_preview_completion_requires_current_document_revision(self):
  record=self.draft()
  person=self.add('previewer','viewer')
  task=self.s.request_preview(self.requester,record['id'],record['revision'],person['id'])
  state=self.s.load(self.requester)
  state['state']['archives']['a'][0]['form']['title']='Updated'
  self.s.save(self.requester,state['state'],state['view'])
  with self.assertRaises(m.Conflict):self.s.complete_preview(person,task['id'],record['revision'])
  current=self.s.preview_task(person,task['id'])['record']
  self.s.complete_preview(person,task['id'],current['revision'])
