import base64,copy,sqlite3,threading,unittest,uuid
from unittest.mock import patch
from test_workflow import Fixture,m
import test_correspondence as correspondence_tests

class BookFiles(Fixture,unittest.TestCase):
 worker=correspondence_tests.Correspondence.worker
 entry=correspondence_tests.Correspondence.entry
 def upload(self,name='كتاب.pdf',content=b'%PDF-1.4\nfixture',**changes):
  return {'id':'ATT-'+str(uuid.uuid4()),'name':name,'data':base64.b64encode(content).decode(),**changes}
 def create(self,worker=None,**changes):
  worker=worker or self.worker();files=[self.upload(),self.upload('صورة.png',b'\x89PNG\r\n\x1a\nimage')]
  item=self.s.save_correspondence(worker,self.entry(attachments=files,**changes))['item']
  return worker,item,files
 def test_create_download_metadata_and_retry_are_atomic(self):
  worker,item,files=self.create()
  self.assertEqual((item['version'],item['attachmentCount'],len(item['attachments'])),(1,2,2))
  self.assertEqual(item['attachments'][0]['name'],'كتاب.pdf');self.assertTrue(item['attachments'][0]['canPreview'])
  self.assertEqual(self.s.correspondence_attachment(worker,files[0]['id'])['content'],base64.b64decode(files[0]['data']))
  retry=self.s.save_correspondence(worker,self.entry(attachments=files))
  self.assertFalse(retry['created']);self.assertEqual(retry['item']['version'],1)
  detail=self.s.correspondence_item(worker,item['id']);self.assertEqual(len(detail['history']),1)
  self.assertEqual(len(detail['history'][0]['attachmentsAdded']),2)
  self.assertEqual(self.s.correspondence_next_number(worker,'incoming')['number'],'124/أ')
 def test_attachment_only_edit_removal_and_audit_use_real_editor(self):
  worker,item,files=self.create();editor=self.worker('editor');new=self.upload('بيانات.txt',b'text attachment')
  changed=self.s.save_correspondence(editor,{**item,'attachments':[{'id':files[0]['id']},new]})['item']
  self.assertEqual((changed['version'],changed['attachmentCount'],changed['lastEditedBy']),(2,2,editor['id']))
  with self.assertRaises(ValueError):self.s.correspondence_attachment(worker,files[1]['id'])
  event=self.s.correspondence_item(worker,item['id'])['history'][0]
  self.assertEqual(event['changedFields'],['attachments']);self.assertEqual(event['attachmentsRemoved'][0]['name'],'صورة.png')
  self.assertEqual(event['attachmentsAdded'][0]['name'],'بيانات.txt')
  noop=self.s.save_correspondence(editor,{**changed,'attachments':[{'id':f['id']} for f in changed['attachments']]})
  self.assertTrue(noop['unchanged']);self.assertEqual(noop['item']['version'],2)
 def test_invalid_upload_and_limits_do_not_save_book_or_advance_counter(self):
  worker=self.worker()
  for files in [[self.upload(data='not-base64')],[self.upload(content=b'')],[self.upload(name='bad\r\nname.txt')],[self.upload() for _ in range(11)]]:
   with self.assertRaises(ValueError):self.s.save_correspondence(worker,self.entry(numberMode='auto',attachments=files))
  with patch('correspondence_files.MAX_FILE_BYTES',4):
   with self.assertRaises(ValueError):self.s.save_correspondence(worker,self.entry(numberMode='auto',attachments=[self.upload(content=b'12345')]))
  with patch('correspondence_files.MAX_BOOK_BYTES',10):
   with self.assertRaises(ValueError):self.s.save_correspondence(worker,self.entry(numberMode='auto',attachments=[self.upload(content=b'123456'),self.upload(content=b'654321')]))
  self.assertEqual(self.s.correspondence_list(worker)['total'],0);self.assertEqual(self.s.correspondence_next_number(worker,'incoming')['number'],'1')
  with self.s.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM correspondence_attachments').fetchone()[0],0)
 def test_permissions_revocation_and_deleted_books_protect_files(self):
  worker,item,files=self.create();viewer=self.worker('viewer',createCorrespondence=False,editCorrespondence=False)
  self.assertEqual(self.s.correspondence_attachment(viewer,files[0]['id'])['contentType'],'application/pdf')
  with self.assertRaises(m.Denied):self.s.save_correspondence(viewer,{**item,'attachments':[]})
  with self.assertRaises(m.Denied):self.s.correspondence_attachment(self.requester,files[0]['id'])
  self.update(viewer,permissions={'viewCorrespondence':False})
  with self.assertRaises(m.Denied):self.s.correspondence_attachment(viewer,files[0]['id'])
  self.s.delete_correspondence(worker,item['id'],item['version'])
  with self.assertRaises(ValueError):self.s.correspondence_attachment(worker,files[0]['id'])
 def test_files_are_immutable_and_cannot_move_between_books(self):
  worker,item,files=self.create();other=self.s.save_correspondence(worker,self.entry('COR-other-files',documentNumber='900'))['item']
  with self.assertRaises(m.Denied):self.s.save_correspondence(worker,{**other,'attachments':[{'id':files[0]['id']}]})
  altered={**files[0],'data':base64.b64encode(b'%PDF-modified').decode()}
  with self.assertRaises(m.Conflict):self.s.save_correspondence(worker,{**item,'attachments':[altered,{'id':files[1]['id']}]})
  unchanged=self.s.correspondence_item(worker,item['id'])['item'];self.assertEqual(unchanged['version'],1)
  removed=self.s.save_correspondence(worker,{**item,'attachments':[]})['item']
  with self.assertRaises(m.Conflict):self.s.save_correspondence(worker,{**removed,'attachments':[files[0]]})
 def test_older_clients_preserve_files_and_database_backups_include_bytes(self):
  worker,item,files=self.create();old=copy.deepcopy(item);old.pop('attachments');old['notes']='حفظ من عميل قديم'
  changed=self.s.save_correspondence(worker,old)['item'];self.assertEqual(changed['attachmentCount'],2)
  self.s.backup();backup=next((self.s.folder/'team-backups').glob('team-*.sqlite3'))
  with sqlite3.connect(backup) as db:self.assertEqual(db.execute('SELECT content FROM correspondence_attachments WHERE id=?',(files[0]['id'],)).fetchone()[0],base64.b64decode(files[0]['data']))
 def test_content_signature_controls_preview_and_filenames_are_safe(self):
  worker=self.worker();html=self.upload('../تجربة.html',b'<script>alert(1)</script>',contentType='image/png')
  item=self.s.save_correspondence(worker,self.entry(attachments=[html]))['item'];file=item['attachments'][0]
  self.assertEqual(file['name'],'تجربة.html');self.assertEqual(file['contentType'],'application/octet-stream');self.assertFalse(file['canPreview'])
 def test_concurrent_edits_do_not_leave_orphan_files(self):
  worker,item,files=self.create();barrier=threading.Barrier(2);results=[];errors=[]
  def change(index):
   try:
    barrier.wait();results.append(self.s.save_correspondence(worker,{**item,'attachments':[{'id':f['id']} for f in files]+[self.upload(str(index)+'.txt',b'extra')]}))
   except Exception as error:errors.append(error)
  threads=[threading.Thread(target=change,args=(index,)) for index in range(2)]
  for t in threads:t.start()
  for t in threads:t.join(10)
  self.assertEqual(len(results),1);self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],m.Conflict)
  with self.s.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM correspondence_attachments').fetchone()[0],3)

if __name__=='__main__':unittest.main()
