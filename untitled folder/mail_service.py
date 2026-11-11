"""Durable Microsoft Graph mail delivery. A 202 confirms acceptance, not delivery.

Workflow transactions enqueue events; this module only consumes committed rows.
Ambiguous sends are held for an administrator instead of automatically duplicated.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager, closing
from datetime import datetime, timezone

PREFIX = 'SHAMARA_M365_'
REQUIRED = tuple(PREFIX + key for key in ('TENANT_ID', 'CLIENT_ID', 'CLIENT_SECRET', 'SENDER'))
LABELS = {'draft':'مسودة', 'submitted':'بانتظار موافقة رئيس القسم', 'approved':'بانتظار تسعير المشتريات',
          'finance_pending':'بانتظار موافقة المالية على الصرف', 'stock_check':'بانتظار فحص المخازن', 'fulfillment':'قيد التجهيز',
          'ordered':'جاهز للتسليم', 'awaiting_receipt':'مطلوب تأكيد الاستلام', 'received':'مكتمل', 'closed':'انتهت الخطة', 'rejected':'مرفوض', 'cancelled':'ملغي'}
EMAIL = re.compile(r'[^\s@<>;,\r\n]+@[^\s@<>;,\r\n]+\.[^\s@<>;,\r\n]+\Z')
GUID = re.compile(r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}\Z')


def configuration_status(environ=None):
    env = os.environ if environ is None else environ
    missing = [key for key in REQUIRED if not env.get(key, '').strip()]
    invalid = []
    for key in ('TENANT_ID', 'CLIENT_ID'):
        value = env.get(PREFIX + key, '').strip()
        if value and not GUID.fullmatch(value): invalid.append(PREFIX + key)
    sender = env.get(PREFIX + 'SENDER', '').strip()
    if sender and not EMAIL.fullmatch(sender): invalid.append(PREFIX + 'SENDER')
    base = env.get('SHAMARA_BASE_URL', '').strip()
    if base:
        try:
            p = urllib.parse.urlsplit(base)
            if p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password or p.query or p.fragment:
                invalid.append('SHAMARA_BASE_URL')
        except ValueError:
            invalid.append('SHAMARA_BASE_URL')
    return {'configured': not missing and not invalid, 'missing': missing, 'invalid': invalid,
            'provider': 'Microsoft 365 / Outlook', 'linkConfigured': bool(base) and 'SHAMARA_BASE_URL' not in invalid,
            'deliveryMeaning': 'قبله Microsoft للإرسال؛ لا يؤكد وصوله إلى صندوق المستلم.'}


@contextmanager
def database(store):
    with closing(store.connect()) as db:
        with db:
            yield db


class DeliveryError(Exception):
    def __init__(self, message, retry=False, ambiguous=False, wait=0):
        super().__init__(message)
        self.retry, self.ambiguous, self.wait = retry, ambiguous, wait


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


class GraphClient:
    def __init__(self, environ=None, opener=None, clock=time.time):
        self.env = dict(os.environ if environ is None else environ)
        self.open = opener or urllib.request.build_opener(NoRedirect()).open
        self.clock, self.token, self.expires = clock, '', 0

    def request(self, request, sending=False):
        try:
            with self.open(request, timeout=15) as response:
                code = response.status
                body = response.read(1_000_001)
                if len(body) > 1_000_000: raise DeliveryError('استجابة خدمة البريد غير صالحة.', ambiguous=sending)
                return code, body
        except urllib.error.HTTPError as error:
            code = error.code
            try: delay = min(3600, max(0, int(error.headers.get('Retry-After', '0'))))
            except (ValueError, TypeError): delay = 0
            error.close()
            # Never retain provider response bodies: they may contain credentials/addresses.
            if sending and code == 401:
                self.token, self.expires = '', 0
                raise DeliveryError('انتهى إذن Microsoft؛ ستعاد المصادقة.', retry=True)
            if code == 429: raise DeliveryError('حد الإرسال مؤقتاً (HTTP 429).', retry=True, wait=delay)
            if not sending and code >= 500: raise DeliveryError('تعذر الاتصال بخدمة الدخول إلى Microsoft.', retry=True)
            if sending and code >= 500:
                raise DeliveryError('استجابة إرسال غير مؤكدة من Microsoft (HTTP '+str(code)+'). تحقّق من البريد قبل إعادة المحاولة.', ambiguous=True)
            raise DeliveryError('رفض Microsoft طلب '+('الإرسال' if sending else 'الدخول')+' (HTTP '+str(code)+').')
        except (urllib.error.URLError, TimeoutError, OSError):
            raise DeliveryError('انقطع اتصال '+('الإرسال؛ قد تكون الرسالة قُبلت. تحقّق قبل إعادة المحاولة.' if sending else 'Microsoft؛ ستعاد المحاولة.'), retry=not sending, ambiguous=sending)

    def access_token(self):
        if self.token and self.clock() < self.expires: return self.token
        tenant = self.env[PREFIX+'TENANT_ID'].strip()
        values = {'client_id':self.env[PREFIX+'CLIENT_ID'].strip(), 'client_secret':self.env[PREFIX+'CLIENT_SECRET'],
                  'grant_type':'client_credentials', 'scope':'https://graph.microsoft.com/.default'}
        request = urllib.request.Request('https://login.microsoftonline.com/'+tenant+'/oauth2/v2.0/token',
                    urllib.parse.urlencode(values).encode(), {'Content-Type':'application/x-www-form-urlencoded'}, method='POST')
        code, raw = self.request(request)
        try:
            data = json.loads(raw)
            token = data['access_token']
            lifetime = min(86400, max(0, int(data.get('expires_in', 3600))-60))
            if code != 200 or not isinstance(token, str) or not token: raise ValueError()
        except (ValueError, KeyError, TypeError): raise DeliveryError('تعذر قراءة إذن الإرسال من Microsoft.')
        self.token, self.expires = token, self.clock()+lifetime
        return token

    def send(self, address, payload, event_key):
        token = self.access_token()
        base = self.env.get('SHAMARA_BASE_URL', '').strip().rstrip('/')
        lines = ['تحديث طلب الشراء رقم '+str(payload.get('requestNumber', '')), 'الشركة / النموذج: '+str(payload.get('companyName', payload.get('company', ''))),
                 'الحالة عند هذا الإجراء: '+LABELS.get(payload.get('status'), str(payload.get('status', ''))),
                 'أجرى الإجراء: '+str(payload.get('actorName', ''))]
        if payload.get('assigneeName'): lines.append('المستلم عند هذا الإجراء: '+str(payload['assigneeName']))
        if payload.get('currentStatus'):
            lines.append('آخر حالة مسجلة: '+LABELS.get(payload['currentStatus'], str(payload['currentStatus'])))
        if payload.get('currentAssigneeName'): lines.append('بانتظار إجراء: '+str(payload['currentAssigneeName']))
        if base: lines.extend(['', 'افتح الطلب بعد تسجيل الدخول:', base+'/?'+urllib.parse.urlencode({'request':payload.get('recordId', '')})])
        lines.extend(['', 'تُجرى الموافقات من الداشبورد بحساب المستخدم.', 'مرجع الإشعار: '+event_key])
        message = {'message':{'subject':'طلب شراء '+str(payload.get('requestNumber', ''))+' — '+LABELS.get(payload.get('status'), 'تحديث'),
                  'body':{'contentType':'Text','content':'\n'.join(lines)},
                  'toRecipients':[{'emailAddress':{'address':address}}]}, 'saveToSentItems':True}
        sender = urllib.parse.quote(self.env[PREFIX+'SENDER'].strip(), safe='')
        request = urllib.request.Request('https://graph.microsoft.com/v1.0/users/'+sender+'/sendMail',
                    json.dumps(message, ensure_ascii=False).encode(), {'Content-Type':'application/json','Authorization':'Bearer '+token}, method='POST')
        code, _ = self.request(request, sending=True)
        if code != 202: raise DeliveryError('لم يؤكد Microsoft قبول الرسالة (HTTP '+str(code)+').', ambiguous=True)


class MailWorker:
    def __init__(self, store, environ=None, client=None, clock=time.time):
        self.store = store
        self.env = dict(os.environ if environ is None else environ)
        self.clock = clock
        self.client = client or GraphClient(self.env, clock=clock)
        self.stopped = threading.Event()
        self.thread = None

    def _finish(self, event, status, error='', delay=0):
        with database(self.store) as db:
            db.execute('UPDATE email_outbox SET status=?,last_error=?,next_attempt_at=?,sent_at=?,locked_at=NULL WHERE id=? AND status=\'sending\' AND locked_at=?',
                (status,error,self.clock()+delay if delay else 0, datetime.now(timezone.utc).isoformat(timespec='seconds') if status=='sent' else None,event['id'],event['locked_at']))

    def tick(self):
        if not configuration_status(self.env)['configured']: return False
        with database(self.store) as db:
            db.execute('BEGIN IMMEDIATE')
            # A server crash may occur after acceptance but before acknowledgement is saved.
            db.execute("UPDATE email_outbox SET status='failed',last_error='توقف الخادم أثناء الإرسال؛ تحقّق من البريد قبل إعادة المحاولة.',next_attempt_at=0,locked_at=NULL WHERE status='sending' AND (locked_at IS NULL OR locked_at<?)", (self.clock()-180,))
            row = db.execute("SELECT * FROM email_outbox WHERE (status='pending' OR (status IN ('failed','skipped') AND next_attempt_at>0)) AND next_attempt_at<=? ORDER BY id LIMIT 1", (self.clock(),)).fetchone()
            if not row: return False
            event = dict(row); event['locked_at'] = self.clock()
            db.execute("UPDATE email_outbox SET status='sending',locked_at=?,attempts=attempts+1 WHERE id=?", (event['locked_at'], event['id']))
            recipient = db.execute('SELECT * FROM users WHERE id=?', (event['recipient_id'],)).fetchone()
            record = db.execute('SELECT payload FROM records WHERE id=?', (event['record_id'],)).fetchone()
        if not recipient or not recipient['active'] or not record or not self.store.visible(self.store.public(recipient), json.loads(record['payload'])):
            self._finish(event, 'skipped', 'المستلم غير نشط أو لم يعد يملك صلاحية عرض الطلب.', 300)
            return True
        address = (recipient['email'] or '').strip()
        if not EMAIL.fullmatch(address):
            self._finish(event, 'skipped', 'أضف بريداً صالحاً إلى حساب المستلم.', 300)
            return True
        try:
            payload = json.loads(event['payload'])
            current = json.loads(record['payload'])
            current_tracking = current.get('tracking', {})
            if event['recipient_id'] != current.get('createdBy'):
                if hasattr(self.store, 'recipient_ids'):
                    with database(self.store) as db:eligible = self.store.recipient_ids(db, current)
                else:eligible = {current_tracking.get('assigneeId')}
                if current_tracking.get('status') != payload.get('status') or event['recipient_id'] not in eligible:
                    self._finish(event, 'skipped', 'تجاوز الطلب هذه المرحلة أو تغيّرت عضوية القسم أو صلاحيات المستلم.')
                    return True
            payload['currentStatus'] = current_tracking.get('status', 'draft')
            payload['currentAssigneeName'] = current_tracking.get('assigneeName', '')
            payload['companyName'] = self.store.companies.get(payload.get('company'), payload.get('company', ''))
            self.client.send(address, payload, event['event_key'])
        except DeliveryError as error:
            attempts = event['attempts']+1
            delay = max(error.wait, min(3600, 30*2**min(attempts-1, 7))) if error.retry and attempts < 6 else 0
            self._finish(event, 'failed', str(error), delay)
        except Exception:
            # The call might already have reached Graph. Do not print any exception or secrets.
            self._finish(event, 'failed', 'تعذر تأكيد الإرسال؛ تحقّق من البريد قبل إعادة المحاولة.')
        else:
            self._finish(event, 'sent')
        return True

    def run(self):
        while not self.stopped.is_set():
            try: busy = self.tick()
            except Exception: busy = False
            self.stopped.wait(1 if busy else 15)

    def start(self):
        if not self.thread:
            self.thread = threading.Thread(target=self.run, name='shamara-mail', daemon=True)
            self.thread.start()
        return self

    def stop(self):
        self.stopped.set()


def start_worker(store, environ=None):
    return MailWorker(store, environ).start()


def retry_notification(store, user, event_id):
    from team_store import Denied
    if user['role'] != 'admin': raise Denied('إعادة إرسال الإشعارات متاحة لمدير النظام فقط.')
    with database(store) as db:
        db.execute('BEGIN IMMEDIATE')
        event = db.execute('SELECT * FROM email_outbox WHERE id=?', (event_id,)).fetchone()
        if not event or event['status'] not in ('failed', 'skipped'): raise ValueError('الإشعار غير متاح لإعادة المحاولة.')
        db.execute("UPDATE email_outbox SET status='pending',attempts=0,next_attempt_at=0,last_error='',locked_at=NULL WHERE id=?", (event_id,))
        store.audit(db, user, 'إعادة محاولة إشعار البريد', event['record_id'], {'eventId':event_id})
    return {'ok':True}
