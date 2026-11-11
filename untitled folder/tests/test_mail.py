import io
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from mail_service import GraphClient, MailWorker, DeliveryError, configuration_status, database, retry_notification

ENV = {'SHAMARA_M365_TENANT_ID':'11111111-1111-1111-1111-111111111111',
       'SHAMARA_M365_CLIENT_ID':'22222222-2222-2222-2222-222222222222',
       'SHAMARA_M365_CLIENT_SECRET':'TEST-SECRET-NEVER-REAL', 'SHAMARA_M365_SENDER':'purchase@example.com',
       'SHAMARA_BASE_URL':'https://dashboard.example.com:8765'}

class FixtureStore:
    def __init__(self, folder):
        self.path=Path(folder)/'test.sqlite3'; self.companies={'c1':'الشركة التجريبية'}
        with database(self) as db:
            db.executescript('''CREATE TABLE email_outbox(id INTEGER PRIMARY KEY,event_key TEXT UNIQUE,record_id TEXT,recipient_id TEXT,recipient_name TEXT,event TEXT,payload TEXT,created_at TEXT,status TEXT DEFAULT 'pending',attempts INTEGER DEFAULT 0,next_attempt_at REAL DEFAULT 0,last_error TEXT DEFAULT '',sent_at TEXT,locked_at REAL);
CREATE TABLE users(id TEXT,name TEXT,email TEXT,active INTEGER,role TEXT,scopes TEXT);
CREATE TABLE records(id TEXT,payload TEXT);''')
            db.execute('INSERT INTO users VALUES(?,?,?,?,?,?)',('u1','المستلم','old@example.com',1,'approver','["c1"]'))
            db.execute('INSERT INTO records VALUES(?,?)',('PR-1',json.dumps({'id':'PR-1','company':'c1','createdBy':'creator','tracking':{'status':'submitted','assigneeId':'u1','assigneeName':'المستلم'}})))
    def connect(self):
        db=sqlite3.connect(self.path,timeout=5); db.row_factory=sqlite3.Row; return db
    def public(self,row):return dict(row)|{'scopes':json.loads(row['scopes'])}
    def visible(self,u,r):return r['company'] in u['scopes']
    def audit(self,*args):pass
    def enqueue(self):
        payload={'recordId':'PR-1','requestNumber':'001','company':'c1','status':'submitted','previousStatus':'draft','actorName':'مقدم الطلب','assigneeName':'المستلم'}
        with database(self) as db:
            db.execute('INSERT INTO email_outbox(event_key,record_id,recipient_id,recipient_name,event,payload,created_at) VALUES(?,?,?,?,?,?,?)',('PR-1:2:u1','PR-1','u1','المستلم','workflow',json.dumps(payload),'2026-11-10'))
    def event(self):
        with database(self) as db:return dict(db.execute('SELECT * FROM email_outbox').fetchone())

class MockClient:
    def __init__(self, result=None):self.calls=[];self.result=result
    def send(self,*args):
        self.calls.append(args)
        if self.result:raise self.result

class Response:
    def __init__(self,status,body=b''):self.status=status;self.body=body
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,*args):return self.body

class MailTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=FixtureStore(self.temp.name);self.store.enqueue();self.ts=1000
    def tearDown(self):self.temp.cleanup()
    def worker(self,client=None,env=ENV):return MailWorker(self.store,env,client=client or MockClient(),clock=lambda:self.ts)
    def queue_fixture(self):
        self.store.recipient_ids=lambda db,r:set(self.queue_members)
        self.queue_members={'u1','u2'}
        with database(self.store) as db:
            db.execute("INSERT INTO users VALUES(?,?,?,?,?,?)",('u2','المستلم الثاني','second@example.com',1,'finance','["c1"]'))
            current={'id':'PR-1','company':'c1','createdBy':'creator','tracking':{'status':'finance_pending','assigneeId':'','assigneeName':'قسم المالية'}}
            db.execute('UPDATE records SET payload=?',(json.dumps(current),))
            row=db.execute('SELECT payload FROM email_outbox').fetchone();payload=json.loads(row[0]);payload['status']='finance_pending'
            db.execute('UPDATE email_outbox SET payload=?',(json.dumps(payload),))
            db.execute("INSERT INTO email_outbox(event_key,record_id,recipient_id,recipient_name,event,payload,created_at) VALUES(?,?,?,?,?,?,?)",('PR-1:2:u2','PR-1','u2','المستلم الثاني','workflow',json.dumps(payload),'2026-11-10'))
    def test_shared_queue_notifies_every_eligible_member(self):
        self.queue_fixture();client=MockClient();worker=self.worker(client);self.assertTrue(worker.tick());self.assertTrue(worker.tick());self.assertEqual(len(client.calls),2)
        with database(self.store) as db:self.assertEqual(db.execute("SELECT count(*) FROM email_outbox WHERE status='sent'").fetchone()[0],2)
    def test_revoked_queue_member_is_skipped(self):
        self.queue_fixture();self.queue_members={'u2'};client=MockClient();worker=self.worker(client);worker.tick();worker.tick();self.assertEqual([c[0] for c in client.calls],['second@example.com'])
        with database(self.store) as db:self.assertEqual(db.execute('SELECT status FROM email_outbox WHERE recipient_id=?',('u1',)).fetchone()[0],'skipped')
    def test_missing_config_does_not_claim_or_send(self):
        client=MockClient();self.assertFalse(self.worker(client,{}).tick());self.assertEqual('pending',self.store.event()['status']);self.assertFalse(client.calls)
        status=configuration_status({});self.assertFalse(status['configured']);self.assertNotIn('TEST-SECRET',json.dumps(status))
    def test_validates_configuration_without_echoing_credentials(self):
        status=configuration_status(ENV);self.assertTrue(status['configured']);self.assertNotIn(ENV['SHAMARA_M365_CLIENT_SECRET'],json.dumps(status))
        self.assertFalse(configuration_status(ENV|{'SHAMARA_M365_SENDER':'a@example.com\nBcc:bad@example.com'})['configured'])
    def test_success_and_no_resend(self):
        client=MockClient();worker=self.worker(client);self.assertTrue(worker.tick());self.assertEqual('sent',self.store.event()['status']);self.assertFalse(worker.tick());self.assertEqual(1,len(client.calls));self.assertTrue(self.store.event()['sent_at'])
    def test_recipient_email_resolved_when_sending(self):
        with database(self.store) as db:db.execute("UPDATE users SET email='new@example.com'")
        client=MockClient();self.worker(client).tick();self.assertEqual('new@example.com',client.calls[0][0]);self.assertEqual('الشركة التجريبية',client.calls[0][1]['companyName'])
    def test_missing_email_waits_then_retries_when_fixed(self):
        with database(self.store) as db:db.execute("UPDATE users SET email=''")
        client=MockClient();worker=self.worker(client);worker.tick();self.assertEqual('skipped',self.store.event()['status']);self.assertFalse(client.calls)
        with database(self.store) as db:db.execute("UPDATE users SET email='restored@example.com'")
        self.ts+=301;worker.tick();self.assertEqual('sent',self.store.event()['status'])
    def test_revoked_scope_or_disabled_recipient_not_sent(self):
        for query in ["UPDATE users SET scopes='[]'", "UPDATE users SET scopes='[\"c1\"]',active=0"]:
            with database(self.store) as db:
                db.execute(query);db.execute("UPDATE email_outbox SET status='pending',next_attempt_at=0")
            client=MockClient();self.worker(client).tick();self.assertFalse(client.calls);self.assertEqual('skipped',self.store.event()['status'])
    def test_429_retries_with_backoff_and_then_stops(self):
        client=MockClient(DeliveryError('429',retry=True,wait=120));worker=self.worker(client)
        for attempt in range(1,7):
            worker.tick();event=self.store.event();self.assertEqual(attempt,event['attempts'])
            if attempt<6:self.assertGreaterEqual(event['next_attempt_at'],self.ts+120);self.ts=event['next_attempt_at']+1
        self.assertEqual(0,event['next_attempt_at']);self.assertFalse(worker.tick())
    def test_ambiguous_send_waits_for_manual_review(self):
        client=MockClient(DeliveryError('uncertain',ambiguous=True));worker=self.worker(client);worker.tick();event=self.store.event();self.assertEqual('failed',event['status']);self.assertEqual(0,event['next_attempt_at']);self.ts+=10000;self.assertFalse(worker.tick());self.assertEqual(1,len(client.calls))
    def test_crash_during_send_not_automatically_duplicated(self):
        with database(self.store) as db:db.execute("UPDATE email_outbox SET status='sending',locked_at=?,attempts=1",(self.ts-181,))
        client=MockClient();worker=self.worker(client);self.assertFalse(worker.tick());self.assertEqual('failed',self.store.event()['status']);self.assertFalse(client.calls)
    def test_concurrent_workers_only_one_send(self):
        entered=threading.Event();release=threading.Event();calls=[]
        class BlockingClient:
            def send(self,*args):calls.append(args);entered.set();release.wait(5)
        first=self.worker(BlockingClient());second=self.worker(MockClient());thread=threading.Thread(target=first.tick);thread.start();self.assertTrue(entered.wait(5));self.assertFalse(second.tick());release.set();thread.join(5);self.assertEqual(1,len(calls));self.assertEqual('sent',self.store.event()['status'])
    def test_graph_sends_plaintext_with_login_link_and_only_accepts_202(self):
        requests=[];responses=[Response(200,b'{"access_token":"mock-token","expires_in":3600}'),Response(202)]
        def opening(request,timeout):requests.append(request);self.assertEqual(15,timeout);return responses.pop(0)
        client=GraphClient(ENV,opener=opening);client.send('recipient@example.com',json.loads(self.store.event()['payload']),'event')
        self.assertIn('client_credentials',requests[0].data.decode());self.assertIn('https%3A%2F%2Fgraph.microsoft.com%2F.default',requests[0].data.decode())
        message=json.loads(requests[1].data);self.assertEqual('Text',message['message']['body']['contentType']);self.assertIn('/?request=PR-1',message['message']['body']['content']);self.assertEqual('Bearer mock-token',requests[1].get_header('Authorization'))
        self.assertNotIn(ENV['SHAMARA_M365_CLIENT_SECRET'],requests[1].data.decode())
    def test_graph_rejection_no_false_success_and_no_secret_error(self):
        def opening(request,timeout):raise urllib.error.HTTPError(request.full_url,403,'denied',{},io.BytesIO(b'SECRET DATA'))
        client=GraphClient(ENV,opener=opening);client.token='cached';client.expires=1e20
        with self.assertRaises(DeliveryError) as caught:client.send('recipient@example.com',{},'event')
        self.assertFalse(caught.exception.retry);self.assertNotIn('SECRET',str(caught.exception))
    def test_superseded_task_is_not_sent_to_old_assignee(self):
        with database(self.store) as db:
            current=json.loads(db.execute('SELECT payload FROM records').fetchone()[0]);current['tracking']={'status':'finance_pending','assigneeId':'finance'}
            db.execute('UPDATE records SET payload=?',(json.dumps(current),))
        client=MockClient();self.worker(client).tick();self.assertFalse(client.calls);self.assertEqual('skipped',self.store.event()['status']);self.assertEqual(0,self.store.event()['next_attempt_at'])
    def test_admin_retry_only_failed_and_skipped(self):
        from team_store import Denied
        with database(self.store) as db:db.execute("UPDATE email_outbox SET status='failed',attempts=3")
        with self.assertRaises(Denied):retry_notification(self.store,{'role':'buyer'},1)
        audit=[];self.store.audit=lambda *args:audit.append(args)
        retry_notification(self.store,{'role':'admin','id':'admin','name':'مدير'},1)
        self.assertEqual('pending',self.store.event()['status']);self.assertEqual(0,self.store.event()['attempts']);self.assertEqual(1,len(audit))
        with database(self.store) as db:db.execute("UPDATE email_outbox SET status='sent'")
        with self.assertRaises(ValueError):retry_notification(self.store,{'role':'admin'},1)
    def test_expired_token_is_discarded_before_retry(self):
        def opening(request,timeout):raise urllib.error.HTTPError(request.full_url,401,'expired',{},io.BytesIO())
        client=GraphClient(ENV,opener=opening);client.token='old';client.expires=1e20
        with self.assertRaises(DeliveryError) as error:client.send('recipient@example.com',{},'event')
        self.assertTrue(error.exception.retry);self.assertEqual('',client.token)
    def test_transport_failures_token_retry_send_ambiguous(self):
        def opening(request,timeout):raise urllib.error.URLError('TEST-SECRET')
        client=GraphClient(ENV,opener=opening)
        with self.assertRaises(DeliveryError) as token:client.access_token()
        self.assertTrue(token.exception.retry);self.assertNotIn('TEST-SECRET',str(token.exception))
        client.token='cached';client.expires=1e20
        with self.assertRaises(DeliveryError) as sent:client.send('recipient@example.com',{},'event')
        self.assertTrue(sent.exception.ambiguous);self.assertFalse(sent.exception.retry)
    def test_unexpected_non202_never_marked_sent(self):
        client=GraphClient(ENV,opener=lambda request,timeout:Response(200));client.token='cached';client.expires=1e20
        self.worker(client).tick();self.assertEqual('failed',self.store.event()['status']);self.assertIsNone(self.store.event()['sent_at'])

if __name__=='__main__':unittest.main()
