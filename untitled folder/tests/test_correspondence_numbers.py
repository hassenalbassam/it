import threading,unittest
from test_workflow import Fixture,m
import test_correspondence as correspondence_tests

class BookNumbers(Fixture,unittest.TestCase):
 worker=correspondence_tests.Correspondence.worker
 entry=correspondence_tests.Correspondence.entry
 def assert_next(self,worker,number):
  for direction in ('incoming','outgoing'):
   result=self.s.correspondence_next_number(worker,direction)
   self.assertEqual(result['number'],number);self.assertTrue(result['shared'])
 def test_shared_counter_starts_at_one_and_alternates_types(self):
  worker=self.worker();self.assert_next(worker,'1');self.assert_next(worker,'1')
  for index,direction in enumerate(('outgoing','incoming','outgoing'),1):
   item=self.s.save_correspondence(worker,self.entry('COR-shared-00'+str(index),direction,numberMode='auto'))['item']
   self.assertEqual(item['documentNumber'],str(index))
  self.assert_next(worker,'4')
 def test_manual_start_auto_continue_lower_reset_and_restart(self):
  worker=self.worker()
  self.s.save_correspondence(worker,self.entry(documentNumber='250'))
  self.assert_next(worker,'251')
  created=self.s.save_correspondence(worker,self.entry('COR-number-002','outgoing',documentNumber='251',numberMode='auto'))['item']
  self.assertEqual(created['documentNumber'],'251');self.assert_next(worker,'252')
  self.s.save_correspondence(worker,self.entry('COR-number-out','outgoing',documentNumber='900'));self.assert_next(worker,'901')
  self.s.save_correspondence(worker,self.entry('COR-number-low','incoming',documentNumber='7'));self.assert_next(worker,'8')
  reopened=m.Store(self.tmp.name,{'a':'Alpha','b':'Beta'})
  for direction in ('incoming','outgoing'):self.assertEqual(reopened.correspondence_next_number(worker,direction)['number'],'8')
 def test_arabic_digits_padding_prefix_and_suffix(self):
  worker=self.worker()
  for index,(start,expected) in enumerate([('٠٠٩٩','٠١٠٠'),('ص/0099/2026','ص/0100/2026'),('099/أ','100/أ'),('۰۰۰۹','۰۰۱۰')]):
   self.s.save_correspondence(worker,self.entry('COR-format-00'+str(index),'incoming' if index%2 else 'outgoing',documentNumber=start))
   self.assert_next(worker,expected)
 def test_notes_deletion_and_nonnumeric_numbers_do_not_change_counter(self):
  worker=self.worker()
  first=self.s.save_correspondence(worker,self.entry(documentNumber='',numberMode='auto'))['item']
  last=self.s.save_correspondence(worker,self.entry('COR-number-last','outgoing',documentNumber='',numberMode='auto'))['item']
  first=self.s.save_correspondence(worker,{**first,'subject':'تحديث الموضوع'})['item']
  self.s.delete_correspondence(worker,last['id'],last['version'])
  self.s.save_correspondence(worker,self.entry('COR-number-text',documentNumber='بلا رقم'))
  self.assert_next(worker,'3')
  self.s.save_correspondence(worker,{**first,'documentNumber':'100'});self.assert_next(worker,'101')
 def test_concurrent_different_types_and_retry_are_unique(self):
  worker=self.worker();self.s.save_correspondence(worker,self.entry(documentNumber='300'))
  barrier=threading.Barrier(2);results=[];errors=[]
  def save(index):
   try:
    barrier.wait()
    payload=self.entry('COR-number-thread-'+str(index),'incoming' if index else 'outgoing',documentNumber='301',numberMode='auto')
    results.append((payload,self.s.save_correspondence(worker,payload)['item']))
   except Exception as error:errors.append(error)
  threads=[threading.Thread(target=save,args=(index,)) for index in range(2)]
  for thread in threads:thread.start()
  for thread in threads:thread.join(10)
  self.assertEqual(errors,[]);self.assertCountEqual([item['documentNumber'] for payload,item in results],['301','302'])
  for payload,item in results:
   retry=self.s.save_correspondence(worker,payload)
   self.assertFalse(retry['created']);self.assertEqual(retry['item']['id'],item['id'])
  self.assert_next(worker,'303')
 def test_shared_migration_starts_one_and_preserves_books_and_old_counters(self):
  worker=self.worker();old=self.s.save_correspondence(worker,self.entry(documentNumber='1334'))['item']
  self.s.delete_correspondence(worker,old['id'],old['version'])
  with self.s.connect() as db:
   before=[tuple(row) for row in db.execute('SELECT * FROM correspondence')]
   db.execute("DELETE FROM correspondence_number_sequences WHERE direction='shared'")
   db.execute("INSERT INTO correspondence_number_sequences VALUES('incoming','1334')")
   db.execute("INSERT INTO correspondence_number_sequences VALUES('outgoing','900')")
  reopened=m.Store(self.tmp.name,{'a':'Alpha','b':'Beta'})
  for direction in ('incoming','outgoing'):self.assertEqual(reopened.correspondence_next_number(worker,direction)['number'],'1')
  with reopened.connect() as db:
   self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM correspondence')],before)
   self.assertEqual(db.execute("SELECT number FROM correspondence_number_sequences WHERE direction='incoming'").fetchone()[0],'1334')
 def test_permissions_validation_and_failed_saves_preserve_number(self):
  worker=self.worker();viewer=self.worker('readonly',createCorrespondence=False)
  for person in (viewer,self.requester):
   with self.assertRaises(m.Denied):self.s.correspondence_next_number(person,'incoming')
  for direction in ('all','',[]):
   with self.assertRaises(ValueError):self.s.correspondence_next_number(worker,direction)
  for changes in ({'subject':''},{'numberMode':[]},{'numberMode':'other'}):
   with self.assertRaises(ValueError):self.s.save_correspondence(worker,self.entry(numberMode='auto',**changes) if 'numberMode' not in changes else self.entry(**changes))
  self.assert_next(worker,'1')
 def test_auto_skips_used_numbers_in_both_types_and_old_formats(self):
  worker=self.worker()
  self.s.save_correspondence(worker,self.entry('COR-old-format','outgoing',documentNumber='124/أ'))
  self.s.save_correspondence(worker,self.entry('COR-other-format','incoming',documentNumber='10/ب'))
  self.s.save_correspondence(worker,self.entry('COR-back-format','incoming',documentNumber='123/أ'))
  self.assert_next(worker,'125/أ')

if __name__=='__main__':unittest.main()
