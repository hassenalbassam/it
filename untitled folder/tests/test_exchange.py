import copy, unittest, io, zipfile
import server
from team_store import digest
class Exchange(unittest.TestCase):
 def record(self,status='finance_pending'):
  return dict(id='PR-Excel-1',company='ivi',form=dict(number='001',date='10/11/2026',recipient='الإدارة',title='طلب شراء',purpose='حاجة العمل',rows=[['مضخة','العراق','مواصفات','٢٫٠','اثنان',''],['']*6]),tracking=dict(status=status,priority='normal',deptApproverId='h',buyerId='b',financeApproverId='f',assigneeId='f',assigneeName='نور',supplier='تجهيز',quoteAmount='1200',currency='IQD',dueDate='2026-12-01',notes=''),createdBy='c',createdByName='مقدم',savedAt='2026-11-10T12:00:00Z',updatedAt='2026-11-10T12:00:00Z',revision=4,history=[{'actor':'نور','action':'اعتماد'}])
 def test_locked_roundtrip_preserves_semantics(self):
  for status in server.STATUSES:
   r=self.record(status);data=server.export_excel({'records':[r],'companies':{'ivi':'IVI'}});result=server.import_excel(data)['records'][0];self.assertEqual(digest(r),digest(result),status);self.assertEqual(r['history'],result['history']);self.assertEqual(result['tracking']['assigneeName'],'نور')
 def test_workflow_columns_and_native_quote(self):
  data=server.export_excel({'records':[self.record()],'companies':{'ivi':'IVI'}})
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   root=server.ET.fromstring(z.read('xl/worksheets/sheet2.xml'));cells={c.get('r'):c for c in root.findall('.//'+server.q('c'))};self.assertEqual(cells['W2'].find(server.q('v')).text,'1200');self.assertIn('Pending User',z.read('xl/worksheets/sheet2.xml').decode());self.assertIn('finance_pending',z.read('xl/worksheets/sheet1.xml').decode())
if __name__=='__main__':unittest.main()
