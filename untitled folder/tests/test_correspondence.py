import io,threading,unittest,zipfile
import server
from test_workflow import Fixture,m

class Correspondence(Fixture,unittest.TestCase):
 def worker(self,name='registry',**overrides):
  return self.add(name,'viewer',scopes=[],permissions={
   'accessPurchases':False,'viewCorrespondence':True,'createCorrespondence':True,
   'editCorrespondence':True,'deleteCorrespondence':True,'exportCorrespondence':True,**overrides,
  })
 def entry(self,ident='COR-entry-001',direction='incoming',**changes):
  return {'id':ident,'version':0,'direction':direction,'agency':'دائرة الإدارة','documentNumber':'123/أ','documentDate':'2026-11-10','subject':'طلب معلومات','notes':'ملاحظة',**changes}
 def test_modules_are_independent_and_defaults_preserve_purchases(self):
  self.assertTrue(self.requester['permissions']['accessPurchases'])
  with self.assertRaises(m.Denied):self.s.correspondence_list(self.requester)
  worker=self.worker()
  with self.assertRaises(m.Denied):self.s.load(worker)
  self.assertFalse(self.s.scope(worker,'a'))
  self.s.save_correspondence(worker,self.entry())
  summary=self.s.portal_summary(worker)
  self.assertIsNone(summary['purchaseCount'])
  self.assertEqual(summary['correspondenceCounts']['incoming'],1)
  self.assertEqual(self.s.portal_summary(self.requester)['latest'],[])

 def test_independent_serials_retry_edit_delete_and_no_reuse(self):
  worker=self.worker()
  first=self.s.save_correspondence(worker,self.entry())['item']
  retry=self.s.save_correspondence(worker,self.entry())['item']
  self.assertEqual(first['id'],retry['id'])
  self.assertEqual(first['serial'],1)
  second=self.s.save_correspondence(worker,self.entry('COR-entry-002'))['item']
  outgoing=self.s.save_correspondence(worker,self.entry('COR-outgo-001','outgoing'))['item']
  self.assertEqual((second['serial'],outgoing['serial']),(2,1))
  changed=self.s.save_correspondence(worker,{**first,'subject':'تحديث الموضوع'})['item']
  self.assertEqual(changed['version'],2)
  with self.assertRaises(m.Conflict):self.s.save_correspondence(worker,{**first,'subject':'نسخة قديمة'})
  with self.assertRaises(m.Conflict):self.s.delete_correspondence(worker,changed['id'],1)
  self.s.delete_correspondence(worker,changed['id'],2)
  third=self.s.save_correspondence(worker,self.entry('COR-entry-003'))['item']
  self.assertEqual(third['serial'],3)
  with self.assertRaises(ValueError):self.s.correspondence_item(worker,changed['id'])
  self.assertEqual(self.s.correspondence_list(worker)['total'],3)

 def test_view_only_and_revocation_are_enforced_at_store(self):
  worker=self.worker()
  item=self.s.save_correspondence(worker,self.entry())['item']
  viewer=self.worker('viewonly',createCorrespondence=False,editCorrespondence=False,deleteCorrespondence=False,exportCorrespondence=False)
  self.assertEqual(self.s.correspondence_item(viewer,item['id'])['item']['serial'],1)
  for callback in [
   lambda:self.s.save_correspondence(viewer,self.entry('COR-denied-001')),
   lambda:self.s.save_correspondence(viewer,{**item,'subject':'ممنوع'}),
   lambda:self.s.delete_correspondence(viewer,item['id'],1),
   lambda:self.s.correspondence_list(viewer,export=True),
  ]:
   with self.assertRaises(m.Denied):callback()
  self.update(worker,permissions={'accessPurchases':False,'viewCorrespondence':False})
  with self.assertRaises(m.Denied):self.s.correspondence_list(worker)

 def test_search_direction_filters_history_and_excel(self):
  worker=self.worker()
  item=self.s.save_correspondence(worker,self.entry(subject='=1+1'))['item']
  self.s.save_correspondence(worker,self.entry('COR-outgo-001','outgoing',agency='الشركة'))
  self.assertEqual(self.s.correspondence_list(worker,{'q':'123/أ'})['total'],2)
  self.assertEqual(self.s.correspondence_list(worker,{'direction':'outgoing','q':'دائرة'})['total'],0)
  self.assertEqual(self.s.correspondence_list(worker,{'from':'2026-11-12'})['total'],0)
  self.assertEqual(len(self.s.correspondence_item(worker,item['id'])['history']),1)
  rows=self.s.correspondence_list(worker,export=True)
  workbook=server.export_correspondence(rows,'all')
  with zipfile.ZipFile(io.BytesIO(workbook)) as archive:
   sheet=server.ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
   self.assertEqual(sheet.find('.//'+server.q('sheetView')).get('rightToLeft'),'1')
   self.assertEqual(sheet.findall('.//'+server.q('f')),[])
   self.assertIn('=1+1',archive.read('xl/worksheets/sheet1.xml').decode())

 def test_concurrent_creates_get_unique_serials(self):
  worker=self.worker()
  barrier=threading.Barrier(2)
  serials=[]
  errors=[]
  def create(ident):
   try:
    barrier.wait()
    serials.append(self.s.save_correspondence(worker,self.entry(ident))['item']['serial'])
   except Exception as error:errors.append(error)
  threads=[threading.Thread(target=create,args=('COR-thread-00'+str(i),)) for i in range(2)]
  for thread in threads:thread.start()
  for thread in threads:thread.join(10)
  self.assertEqual(errors,[])
  self.assertCountEqual(serials,[1,2])

 def test_invalid_records_and_filters_are_rejected(self):
  worker=self.worker()
  for changes in [{'documentDate':'2026-1-1'},{'documentDate':'2026-02-30'},{'agency':''},{'subject':''},{'direction':'other'}]:
   with self.assertRaises(ValueError):self.s.save_correspondence(worker,self.entry(**changes))
  with self.assertRaises(ValueError):self.s.correspondence_list(worker,{'from':'2026-1-1'})
  with self.assertRaises(ValueError):self.s.delete_correspondence(worker,{},1)

 def test_unified_register_uses_book_date_and_has_one_export_date(self):
  worker=self.worker()
  item=self.s.save_correspondence(worker,self.entry())['item']
  self.s.save_correspondence(worker,self.entry('COR-combine-002','outgoing',documentDate='2026-11-12'))
  with self.s.connect() as db:
   db.execute('UPDATE correspondence SET registered_on=? WHERE id=?',('2020-01-01',item['id']))
  result=self.s.correspondence_list(worker)
  self.assertEqual({row['direction'] for row in result['items']},{'incoming','outgoing'})
  self.assertNotIn('registeredOn',result['items'][0])
  self.assertEqual(result['items'][0]['direction'],'outgoing')
  self.assertEqual(self.s.correspondence_list(worker,{'from':'2026-11-11'})['total'],1)
  self.assertEqual(self.s.correspondence_list(worker,{'direction':'incoming'})['total'],1)
  self.s.save_correspondence(worker,{**item,'notes':'تحديث'})
  with self.s.connect() as db:
   self.assertEqual(db.execute('SELECT registered_on FROM correspondence WHERE id=?',(item['id'],)).fetchone()[0],'2020-01-01')
  data=server.export_correspondence(self.s.correspondence_list(worker,export=True),'all')
  with zipfile.ZipFile(io.BytesIO(data)) as archive:
   root=server.ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
   headers=[''.join(cell.itertext()) for cell in root.find('.//'+server.q('row'))]
   self.assertEqual(headers[0],'نوع القيد')
   self.assertNotIn('رقم التسلسل',headers)
   self.assertEqual(len(headers),8)
   self.assertIn('أنشأه',headers)
   self.assertIn('آخر من عدّله',headers)
   self.assertIn('رقم الكتاب',headers)
   self.assertIn('تاريخ الكتاب',headers)
   self.assertNotIn('التاريخ',headers)
