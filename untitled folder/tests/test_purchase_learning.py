import copy,json,hashlib,unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from test_workflow import Fixture,m
from purchase_learning import material_parts,normalized,purchase_type,request_year,read_reference

class Learning(Fixture,unittest.TestCase):
 def setUp(self):
  super().setUp()
  self.reference={'rows':[dict(key='source-one',year=2026,number='536',company='a',sheet='2026',row=538,date='2026-04-11',requester='Employee',fromDepartment='IT',toDepartment='Alpha',title='طلب شراء',details='حبر طابعة + ورق A4'),dict(key='source-two',year=2026,number='536',company='a',sheet='2026',row=539,date='2026-04-11',requester='Employee 2',fromDepartment='IT',toDepartment='Alpha',title='طلب شراء',details='بطارية'),dict(key='source-beta',year=2026,number='1300',company='b',sheet='2026',row=1302,date='2026-10-11',requester='Beta Employee',fromDepartment='IT',toDepartment='Beta',title='طلب شراء',details='مادة سرية خاصة'),dict(key='source-unknown',year=2026,number='1250',company='',sheet='2026',row=1252,date='2026-09-11',requester='Unmapped',fromDepartment='IT',toDepartment='Unknown',title='طلب شراء',details='مادة غير مرتبطة')],'maxima':{2025:1377,2026:1375},'duplicates':[{'year':2026,'number':536,'count':2}],'ignored':0,'sha256':'fixture-reference-v1'}
  self.s.import_purchase_reference(self.admin,self.reference)
 def create(self,ident,mode='auto',key='',number='1',view=None,who=None,rows=None,date='2026-11-11'):
  user=who or self.requester;view=view or self.s.load(user)
  record={'id':ident,'company':'a','form':{'number':number,'date':date,'rows':rows or [['مضخة ذكية','العراق','قدرة 2 حصان','2','','']]},'tracking':{'status':'draft','priority':'normal','numberMode':mode,'sourceKey':key}}
  view['state']['archives'].setdefault('a',[]).append(record)
  out=self.s.save(user,view['state'],view['view'])
  return next(r for r in out['state']['archives']['a'] if r['id']==ident)
 def test_auto_continues_excel_and_preserves_legacy_numbers(self):
  legacy=self.create('PR-legacy',mode='manual',number='13321')
  first=self.create('PR-first');second=self.create('PR-second')
  self.assertEqual((first['form']['number'],second['form']['number']),('1376','1377'))
  self.assertEqual(first['tracking']['numberMode'],'assigned')
  self.assertEqual(next(r for r in self.s.load(self.requester)['state']['archives']['a'] if r['id']==legacy['id'])['form']['number'],'13321')
  view=self.s.load(self.requester);self.s.save(self.requester,view['state'],view['view'])
  self.assertEqual(self.s.purchase_assistance(self.requester,'a',2026)['nextNumber'],'1378')
  nextyear=self.create('PR-nextyear',date='2027-01-01');self.assertEqual(nextyear['form']['number'],'1')
 def test_existing_number_is_skipped_and_concurrent_saves_are_distinct(self):
  self.create('PR-reserved',mode='manual',number='١٣٧٦')
  views=[self.s.load(self.requester),self.s.load(self.requester)]
  with ThreadPoolExecutor(2) as pool:
   results=list(pool.map(lambda p:self.create('PR-parallel-'+str(p[0]),view=p[1]),enumerate(views)))
  self.assertEqual({r['form']['number'] for r in results},{'1377','1378'})
 def test_excel_number_exact_and_repeated_source_rows_disambiguated(self):
  a=self.create('PR-bound-one',mode='excel',key='source-one',number='999',date='2026-04-11')
  b=self.create('PR-bound-two',mode='excel',key='source-two',number='999',date='2026-04-11')
  self.assertEqual((a['form']['number'],b['form']['number']),('536','536'))
  with self.assertRaises(m.Conflict):self.create('PR-double-source',mode='excel',key='source-one',date='2026-04-11')
  self.assertEqual(self.s.purchase_assistance(self.requester,'a',2026,sources=True)['sources'],[])
  view=self.s.load(self.requester);view['state']['archives']['a'][0]['form']['number']='537'
  with self.assertRaises(m.Denied):self.s.save(self.requester,view['state'],view['view'])
 def test_source_permissions_year_and_rejected_saves_do_not_consume_number(self):
  for key,date,error in [('source-beta','2026-11-11',m.Denied),('source-unknown','2026-11-11',m.Denied),('source-one','2025-11-11',ValueError),('','2026-11-11',ValueError)]:
   with self.assertRaises(error):self.create('PR-invalid-'+str(len(key)),mode='excel',key=key,date=date)
  with self.assertRaises(m.Denied):self.s.import_purchase_reference(self.requester,self.reference)
  self.assertEqual(self.s.purchase_assistance(self.requester,'a',2026)['nextNumber'],'1376')
 def test_material_learning_scopes_updates_retries_and_deletion(self):
  self.assertTrue(self.s.purchase_assistance(self.requester,'a',2026,'حبر')['items'])
  self.assertFalse(self.s.purchase_assistance(self.requester,'a',2026,'سرية')['items'])
  with self.assertRaises(m.Denied):self.s.purchase_assistance(self.requester,'b',2026,'')
  row=self.create('PR-learning')
  item=self.s.purchase_assistance(self.requester,'a',2026,'مضخه')['items'][0]
  self.assertEqual((item['uses'],item['origin'],item['specifications']),(1,'العراق','قدرة 2 حصان'))
  row=self.action(row,self.requester,'submit')
  self.assertEqual(self.s.purchase_assistance(self.requester,'a',2026,'مضخة')['items'][0]['uses'],1)
  self.action(row,self.approver,'reject',{'notes':'تعديل المادة'})
  view=self.s.load(self.requester);view['state']['archives']['a'][0]['form']['rows'][0][0]='مضخة مياه جديدة'
  self.s.save(self.requester,view['state'],view['view'])
  self.assertFalse(any(i['name']=='مضخة ذكية' for i in self.s.purchase_assistance(self.requester,'a',2026,'مضخة')['items']))
  view=self.s.load(self.requester);view['state']['archives']['a']=[];self.s.save(self.requester,view['state'],view['view'])
  self.assertFalse(self.s.purchase_assistance(self.requester,'a',2026,'مضخة')['items'])
 def test_idempotent_reference_updates_keep_assigned_numbers_and_learning(self):
  row=self.create('PR-learning');original=self.s.purchase_reference_status(self.admin)
  self.assertEqual(original,self.s.import_purchase_reference(self.admin,self.reference))
  updated=copy.deepcopy(self.reference);updated['sha256']='changed';updated['maxima'][2026]=1400
  self.s.import_purchase_reference(self.admin,updated)
  self.assertEqual(self.s.purchase_assistance(self.requester,'a',2026)['nextNumber'],'1401')
  self.assertEqual(self.s.purchase_assistance(self.requester,'a',2026,'مضخة')['items'][0]['uses'],1)
  self.assertEqual(self.s.load(self.requester)['state']['archives']['a'][0]['form']['number'],row['form']['number'])
 def test_registry_only_and_readonly_cannot_access_reference(self):
  registry=self.add('registry','viewer',permissions={'accessPurchases':False,'viewCorrespondence':True})
  with self.assertRaises(m.Denied):self.s.purchase_reference_status(registry)
  with self.assertRaises(m.Denied):self.s.purchase_assistance(registry,'a',2026,'')
  viewer=self.add('viewer','viewer')
  with self.assertRaises(m.Denied):self.s.purchase_assistance(viewer,'a',2026,'')

class Parser(unittest.TestCase):
 def test_arabic_purchase_types_and_material_words(self):
  for name in ['طلب شراء','طلب الشراء','طلب شرائ','طلب شرااء','طللب شراء']:self.assertTrue(purchase_type(name))
  self.assertFalse(purchase_type('صرف مبلغ'))
  self.assertEqual(material_parts('حبر طابعة عدد 2 + ورق A4 + حبر طابعة عدد 3'),['حبر طابعة','ورق A4'])
  self.assertEqual(material_parts('سلفة مالية'),[])
  self.assertEqual(normalized('إطارات ١٢'),'اطارات 12')
  self.assertEqual(request_year('11/11/2026'),2026)
 def test_parser_reads_number_column_and_reserves_other_request_types(self):
  class Archive:
   def __init__(self,*args):pass
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def infolist(self):return []
   def namelist(self):return list(self.files)
   def read(self,name):return self.files[name].encode()
   files={
    'xl/workbook.xml':'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="2026" r:id="r1"/></sheets></workbook>',
    'xl/_rels/workbook.xml.rels':'<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>',
    'xl/worksheets/sheet1.xml':'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t> رقم العدد</t></is></c><c r="E1" t="inlineStr"><is><t>عنوان الطلب</t></is></c><c r="F1" t="inlineStr"><is><t>التفاصيل </t></is></c></row><row r="2"><c r="A2"><v>1374</v></c><c r="D2" t="inlineStr"><is><t>Alpha</t></is></c><c r="E2" t="inlineStr"><is><t>طلب شراء</t></is></c><c r="F2" t="inlineStr"><is><t>بطارية</t></is></c><c r="H2" t="inlineStr"><is><t>طلب شراء 99999</t></is></c></row><row r="3"><c r="A3"><v>1375</v></c><c r="E3" t="inlineStr"><is><t>طلب صرف</t></is></c></row></sheetData></worksheet>'}
  with patch('purchase_learning.zipfile.ZipFile',Archive):parsed=read_reference(b'fixture',[{'id':'a','name':'Alpha'}])
  self.assertEqual(parsed['maxima'],{2026:1375})
  self.assertEqual(len(parsed['rows']),1)
  self.assertEqual(parsed['rows'][0]['number'],'1374')
  self.assertEqual(parsed['rows'][0]['company'],'a')

if __name__=='__main__':unittest.main()
