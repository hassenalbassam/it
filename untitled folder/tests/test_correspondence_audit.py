import json,unittest
from test_workflow import Fixture,m
import test_correspondence as correspondence_tests

class BookAudit(Fixture,unittest.TestCase):
 worker=correspondence_tests.Correspondence.worker
 entry=correspondence_tests.Correspondence.entry
 def test_author_and_every_editor_are_recorded_from_authenticated_account(self):
  author=self.worker('author');editor=self.worker('editor')
  first=self.s.save_correspondence(author,self.entry(createdByName='FORGED',createdBy=self.admin['id']))['item']
  self.assertEqual((first['createdBy'],first['createdByName'],first['createdByUsername']),(author['id'],author['name'],author['username']))
  self.assertEqual(first['lastEditedBy'],'')
  second=self.s.save_correspondence(editor,{**first,'subject':'موضوع معدّل','notes':'ملاحظة جديدة','lastEditedBy':self.admin['id'],'lastEditedByName':'FORGED'})['item']
  self.assertEqual((second['createdBy'],second['lastEditedBy'],second['lastEditedByUsername']),(author['id'],editor['id'],editor['username']))
  third=self.s.save_correspondence(author,{**second,'agency':'دائرة ثانية'})['item']
  detail=self.s.correspondence_item(editor,first['id'])
  self.assertEqual([event['actorId'] for event in detail['history']],[author['id'],editor['id'],author['id']])
  self.assertEqual(detail['history'][0]['changedFields'],['agency'])
  self.assertEqual(set(detail['history'][1]['changedFields']),{'subject','notes'})
  self.assertEqual(third['lastEditedByName'],author['name'])
  for item in (self.s.correspondence_list(editor)['items'][0],self.s.correspondence_list(editor,export=True)[0],self.s.portal_summary(editor)['latest'][0]):
   self.assertEqual(item['createdByName'],author['name']);self.assertEqual(item['lastEditedByName'],author['name'])
 def test_noop_conflict_and_denial_do_not_create_fake_edits(self):
  author=self.worker('author');editor=self.worker('editor');viewer=self.worker('readonly',editCorrespondence=False)
  first=self.s.save_correspondence(author,self.entry())['item']
  result=self.s.save_correspondence(editor,first)
  self.assertTrue(result['unchanged']);self.assertEqual(result['item']['version'],1)
  second=self.s.save_correspondence(editor,{**first,'notes':'تعديل حقيقي'})['item']
  with self.assertRaises(m.Conflict):self.s.save_correspondence(author,{**first,'subject':'نسخة قديمة'})
  with self.assertRaises(m.Denied):self.s.save_correspondence(viewer,{**second,'subject':'تعديل ممنوع'})
  self.assertEqual(len(self.s.correspondence_item(author,first['id'])['history']),2)
  self.assertEqual(self.s.correspondence_item(author,first['id'])['item']['lastEditedBy'],editor['id'])
 def test_pagination_keeps_all_edits_and_is_scoped(self):
  worker=self.worker();item=self.s.save_correspondence(worker,self.entry())['item']
  for index in range(55):item=self.s.save_correspondence(worker,{**item,'subject':'تعديل '+str(index)})['item']
  result=self.s.correspondence_item(worker,item['id']);self.assertEqual(len(result['history']),50);self.assertTrue(result['historyHasMore'])
  older=self.s.correspondence_history(worker,item['id'],result['historyBefore'])
  self.assertEqual(len(older['history']),6);self.assertFalse(older['historyHasMore'])
  events=result['history']+older['history'];self.assertEqual(len({e['seq'] for e in events}),56)
  self.assertTrue(events[-1]['action'].startswith('تسجيل'))
  with self.assertRaises(m.Denied):self.s.correspondence_history(self.requester,item['id'],result['historyBefore'])
  with self.assertRaises(ValueError):self.s.correspondence_history(worker,item['id'],0)
 def test_old_audit_entries_are_used_without_rewriting_history(self):
  worker=self.worker();editor=self.worker('editor')
  first=self.s.save_correspondence(worker,self.entry())['item']
  self.s.save_correspondence(editor,{**first,'notes':'تعديل قديم'})
  with self.s.connect() as db:
   db.execute('UPDATE audit SET details=? WHERE record_id=?',('{}',first['id']))
   before=[tuple(row) for row in db.execute('SELECT * FROM audit WHERE record_id=?',(first['id'],))]
  item=self.s.correspondence_item(worker,first['id'])
  self.assertEqual(item['item']['lastEditedBy'],editor['id']);self.assertEqual(item['history'][0]['username'],editor['username'])
  self.assertIsNone(item['history'][0]['changedFields'])
  with self.s.connect() as db:self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM audit WHERE record_id=?',(first['id'],))],before)
 def test_editor_name_and_username_snapshot_survive_account_changes(self):
  worker=self.worker();editor=self.worker('original_editor')
  first=self.s.save_correspondence(worker,self.entry())['item']
  self.s.save_correspondence(editor,{**first,'notes':'تعديل محفوظ'})
  self.update(editor,name='اسم جديد',username='renamed_editor',active=False)
  detail=self.s.correspondence_item(worker,first['id'])
  self.assertEqual(detail['item']['lastEditedByName'],'original_editor')
  self.assertEqual(detail['item']['lastEditedByUsername'],'original_editor')
  self.assertEqual(detail['history'][0]['actor'],'original_editor')
  self.assertEqual(detail['history'][0]['username'],'original_editor')

if __name__=='__main__':unittest.main()
