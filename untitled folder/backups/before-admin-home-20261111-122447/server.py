#!/usr/bin/env python3
"""Shamara Dashboard local workspace, Excel exchange, and original Word preview."""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from xml.etree import ElementTree as ET
import copy, hashlib, io, json, os, re, secrets, shutil, socket, subprocess, tempfile, threading, webbrowser, zipfile

ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
STATE_LOCK = threading.Lock()
DATA = ROOT / 'data'
MAX_UPLOAD = 50_000_000
BUNDLED = Path('/Users/husseinalbassam/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/soffice')
SOFFICE = str(BUNDLED) if BUNDLED.exists() else shutil.which('soffice') or shutil.which('libreoffice')
STATUSES = ('draft', 'submitted', 'approved', 'finance_pending', 'stock_check', 'fulfillment', 'ordered', 'awaiting_receipt', 'received', 'closed', 'rejected', 'cancelled')
PRIORITIES = ('low', 'normal', 'high', 'urgent')
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
ET.register_namespace('', NS)
ET.register_namespace('r', REL)
HEADERS = ['ID','Company ID','Company','Request No','Date','Recipient','Title','Status','Priority','Owner','Supplier','Due Date','Notes','Saved At','Updated At','Item Count','Age Days','Overdue','Pending User','Department Approver ID','Buyer ID','Finance Approver ID','Quote Amount','Currency','Warehouse ID']
ITEM_HEADERS = ['Request ID','Item No','Item','Origin','Specifications','Quantity','Quantity Written','Notes']


def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def q(tag): return '{'+NS+'}'+tag

class ConflictError(ValueError): pass

def checked_zip(data):
    try: z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as error: raise ValueError('The file is not a valid Excel or Word file.') from error
    infos = z.infolist()
    if len(infos)>5000 or sum(i.file_size for i in infos)>150_000_000: z.close(); raise ValueError('The expanded file is too large.')
    if len({i.filename for i in infos})!=len(infos): z.close(); raise ValueError('Archive contains duplicate paths.')
    if any(i.flag_bits & 1 for i in infos): z.close(); raise ValueError('Password-protected files are not supported.')
    if any('vbaProject' in i.filename for i in infos): z.close(); raise ValueError('Macro-enabled files are not supported.')
    return z

def xml_bytes(element): return ET.tostring(element, encoding='utf-8', xml_declaration=True)
def col_name(index):
    result=''
    while index: index, rem=divmod(index-1,26); result=chr(65+rem)+result
    return result

def safe_string(value):
    value = '' if value is None else str(value)
    return ''.join(c for c in value if c in '\t\n\r' or ord(c)>=32)[:32760]

def normalize_number(value):
    return str(value).translate(str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬','01234567890123456789.,')).strip()

def excel_date(value):
    text=normalize_number(value)
    for fmt in ('%Y-%m-%d','%d/%m/%Y','%d-%m-%Y'):
        try:
            parsed=datetime.strptime(text,fmt).date()
            if parsed>=date(1900,1,1):return parsed
        except ValueError:pass
    return value or ''

def quantity_value(value):
    text=normalize_number(value).replace(',','')
    if re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)',text):
        number=float(text)
        if abs(number)<1e15:return int(number) if number.is_integer() else number
    return value

def cell(row, col, value, style=0, formula=False):
    if isinstance(value,date):value=(value-date(1899,12,30)).days;style=3
    c=ET.Element(q('c'), {'r': col_name(col)+str(row)})
    if style: c.set('s', str(style))
    if formula: ET.SubElement(c,q('f')).text=value
    elif isinstance(value,(int,float)) and not isinstance(value,bool): ET.SubElement(c,q('v')).text=str(value)
    else:
        c.set('t','inlineStr'); t=ET.SubElement(ET.SubElement(c,q('is')),q('t')); t.set('{http://www.w3.org/XML/1998/namespace}space','preserve');t.text=safe_string(value)
    return c

def worksheet(headers, rows, widths=None, formulas=None, validations=None, hidden=False, rtl=False):
    root=ET.Element(q('worksheet')); ET.SubElement(root,q('dimension'),{'ref':'A1:'+col_name(len(headers))+str(len(rows)+1)})
    views=ET.SubElement(root,q('sheetViews')); view=ET.SubElement(views,q('sheetView'),{'workbookViewId':'0','showGridLines':'0',**({'rightToLeft':'1'} if rtl else {})})
    ET.SubElement(view,q('pane'),{'ySplit':'1','topLeftCell':'A2','activePane':'bottomLeft','state':'frozen'})
    cols=ET.SubElement(root,q('cols'))
    for i,w in enumerate(widths or [20]*len(headers),1): ET.SubElement(cols,q('col'),{'min':str(i),'max':str(i),'width':str(w),'customWidth':'1'})
    data=ET.SubElement(root,q('sheetData')); r=ET.SubElement(data,q('row'),{'r':'1','ht':'30','customHeight':'1'})
    for i,h in enumerate(headers,1):r.append(cell(1,i,h,1))
    for idx,values in enumerate(rows,2):
        r=ET.SubElement(data,q('row'),{'r':str(idx),'ht':'30','customHeight':'1'})
        for j,value in enumerate(values,1):r.append(cell(idx,j,value,2,formula=(formulas is not None and j in formulas)))
    ET.SubElement(root,q('autoFilter'),{'ref':'A1:'+col_name(len(headers))+str(max(2,len(rows)+1))})
    if validations:
        group=ET.SubElement(root,q('dataValidations'),{'count':str(len(validations))})
        for column,values in validations:
            v=ET.SubElement(group,q('dataValidation'),{'type':'list','allowBlank':'1','showErrorMessage':'1','errorTitle':'Choose a listed value','error':'Use a value from the dropdown.','sqref':column+'2:'+column+'1048576'})
            ET.SubElement(v,q('formula1')).text='"'+','.join(values)+'"'
    ET.SubElement(root,q('pageMargins'),{'left':'0.3','right':'0.3','top':'0.5','bottom':'0.5','header':'0.3','footer':'0.3'})
    return xml_bytes(root)


def export_excel(payload):
    records=payload.get('records',[]); companies=payload.get('companies',{})
    if not isinstance(records,list) or len(records)>20000: raise ValueError('Export supports up to 20,000 requests at a time.')
    if not isinstance(companies,dict): raise ValueError('companies must be an object')
    requests=[]; items=[]; archive=[]; ids=set()
    for index,record in enumerate(records,2):
        if not isinstance(record,dict): raise ValueError('Each request must be an object.')
        ident=str(record.get('id','')); company=str(record.get('company',''))
        if not ident or not company or ident in ids: raise ValueError('Each request needs a unique ID and Company ID.')
        ids.add(ident);form=record.get('form') or {};track=record.get('tracking') or {}
        rows=[r for r in form.get('rows',[]) if isinstance(r,list) and any(str(v or '').strip() for v in r)]
        saved=record.get('savedAt') or record.get('createdAt') or ''
        status=track.get('status','draft');priority=track.get('priority','normal')
        requests.append([ident,company,companies.get(company,company),form.get('number',''),excel_date(form.get('date','')),form.get('recipient',''),form.get('title',''),status,priority,track.get('owner',''),track.get('supplier',''),excel_date(track.get('dueDate','')),track.get('notes',''),saved,record.get('updatedAt',''),len(rows),f'IF(E{index}="","",IFERROR(MAX(0,TODAY()-E{index}),""))',f'IF(OR(L{index}="",H{index}="received",H{index}="closed",H{index}="cancelled",H{index}="rejected"),"",IFERROR(IF(L{index}<TODAY(),"Overdue","On time"),"Check date"))',track.get('assigneeName',''),track.get('deptApproverId',''),track.get('buyerId',''),track.get('financeApproverId',''),quantity_value(track.get('quoteAmount','')),track.get('currency','IQD'),track.get('warehouseId','')])
        for i,row in enumerate(rows,1):
            values=(row+['']*6)[:6];values[3]=quantity_value(values[3]);items.append([ident,i]+values)
        # JSON chunks preserve template-specific fields and history through an Excel round trip.
        text=json.dumps(record,ensure_ascii=False,separators=(',',':'))
        for part,start in enumerate(range(0,len(text),30000)): archive.append([ident,part,text[start:start+30000]])
    summary=[]
    for i,(code,label) in enumerate([('draft','مسودة'),('submitted','بانتظار رئيس القسم'),('approved','تسعير المشتريات'),('finance_pending','موافقة المالية على الصرف'),('stock_check','فحص المخازن'),('fulfillment','التجهيز'),('ordered','جاهز للتسليم'),('awaiting_receipt','بانتظار تأكيد الاستلام'),('received','مكتمل'),('closed','انتهت الخطة'),('rejected','مرفوض'),('cancelled','ملغى')],2):summary.append([code,label,f'COUNTIF(Requests!H2:H1048576,A{i})'])
    summary.append(['total','إجمالي الطلبات','COUNTA(Requests!A2:A1048576)'])
    instructions=[['Purpose','تتبع طلبات الشراء وتحديثها ثم استيراد الملف إلى الداشبورد.'],['Requests','صف واحد لكل طلب. اترك ID وCompany ID دون تغيير. تخضع التغييرات لصلاحيات حسابك. نفّذ الموافقات والتحويلات من الداشبورد.'],['Items','صف واحد لكل مادة. اربط كل صف بـ Request ID موجود. أضف أو احذف أو عدّل المواد هنا.'],['New requests','لإضافة طلب: ID جديد فريد وCompany ID صحيح، ثم أدخل بياناته ومواده.'],['Dates','استخدم YYYY-MM-DD للتواريخ.'],['Status','draft = مسودة; submitted = رئيس القسم; approved = التسعير; finance_pending = موافقة الصرف; stock_check = فحص المخازن; fulfillment = التجهيز; ordered = جاهز للتسليم; awaiting_receipt = تأكيد الاستلام; received = مكتمل; closed = انتهت الخطة; rejected = مرفوض; cancelled = ملغى'],['Workflow','أعمدة Pending User وما بعدها للقراءة فقط. تُحفظ تعيينات المستخدمين والتسعير مع Archive. استخدم الداشبورد لتعديل المسار والتسعير وللموافقات والتحويلات.'],['Priority','low = منخفضة; normal = عادية; high = عالية; urgent = عاجلة'],['Formula columns','Age Days وOverdue وSummary أعمدة محسوبة؛ لا تعدّلها.'],['Archive','ورقة مخفية تحفظ حقول Word والسجل. لا تحذفها إذا أردت الاحتفاظ بها عند الاستيراد.'],['Import','الاستيراد يعرض المعاينة أولاً. حذف طلب من Excel لا يحذفه من الداشبورد.'],['Source','تم التصدير من بيانات الداشبورد المحلية بتاريخ '+now()]]
    sheets=[('Summary',worksheet(['Status','الحالة','Requests'],summary,[18,30,18],formulas={3})),('Requests',worksheet(HEADERS,requests,[28,24,35,20,16,30,30,24,14,24,28,16,48,27,27,13,13,16,26,28,28,28,22,16,28],formulas={17,18},validations=[('H',STATUSES),('I',PRIORITIES)])),('Items',worksheet(ITEM_HEADERS,items,[28,12,35,20,48,16,24,45])),('Instructions',worksheet(['Field','Guide'],instructions,[22,110])),('Archive',worksheet(['ID','Part','JSON'],archive,[28,10,100]))]
    return excel_workbook(sheets)

def excel_workbook(sheets):
    wb=ET.Element(q('workbook'));sh=ET.SubElement(wb,q('sheets'))
    for i,(name,_) in enumerate(sheets,1):ET.SubElement(sh,q('sheet'),{'name':name,'sheetId':str(i),'{'+REL+'}id':'rId'+str(i),**({'state':'hidden'} if name=='Archive' else {})})
    ET.SubElement(wb,q('calcPr'),{'calcId':'191029','fullCalcOnLoad':'1'})
    rels=ET.Element('Relationships',{'xmlns':'http://schemas.openxmlformats.org/package/2006/relationships'})
    for i in range(1,len(sheets)+1):ET.SubElement(rels,'Relationship',{'Id':'rId'+str(i),'Type':REL+'/worksheet','Target':'worksheets/sheet'+str(i)+'.xml'})
    ET.SubElement(rels,'Relationship',{'Id':'rIdStyles','Type':REL+'/styles','Target':'styles.xml'})
    types=ET.Element('Types',{'xmlns':'http://schemas.openxmlformats.org/package/2006/content-types'})
    for ext,mime in [('rels','application/vnd.openxmlformats-package.relationships+xml'),('xml','application/xml')]:ET.SubElement(types,'Default',{'Extension':ext,'ContentType':mime})
    for part,mime in [('/xl/workbook.xml','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'),('/xl/styles.xml','application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml')]+[('/xl/worksheets/sheet'+str(i)+'.xml','application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml') for i in range(1,len(sheets)+1)]:ET.SubElement(types,'Override',{'PartName':part,'ContentType':mime})
    styles=f'''<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="{NS}"><fonts count="2"><font><sz val="11"/><name val="Arial"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Arial"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF16342E"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment vertical="center"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',xml_bytes(types));z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="'+REL+'/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml',xml_bytes(wb));z.writestr('xl/_rels/workbook.xml.rels',xml_bytes(rels));z.writestr('xl/styles.xml',styles)
        for i,(_,data) in enumerate(sheets,1):z.writestr('xl/worksheets/sheet'+str(i)+'.xml',data)
    return out.getvalue()


def export_correspondence(records,direction):
    headers=['نوع القيد','اسم الدائرة','رقم الكتاب','تاريخ الكتاب','الموضوع','ملاحظات','أنشأه','آخر من عدّله']
    def person(name,username):return name+(' ('+username+')' if username else '')
    rows=[['وارد' if row['direction']=='incoming' else 'صادر',row['agency'],row['documentNumber'],excel_date(row['documentDate']),row['subject'],row['notes'],person(row['createdByName'],row.get('createdByUsername','')),person(row.get('lastEditedByName',''),row.get('lastEditedByUsername',''))] for row in records]
    name={'incoming':'الوارد','outgoing':'الصادر','all':'الصادر والوارد'}[direction]
    return excel_workbook([(name,worksheet(headers,rows,[14,38,22,16,65,45,32,32],rtl=True))])

def import_excel(data):
    warnings=[]
    with checked_zip(data) as z:
        if 'xl/workbook.xml' not in z.namelist():raise ValueError('Choose an .xlsx file exported from the dashboard.')
        workbook=ET.fromstring(z.read('xl/workbook.xml')); relationships=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        targets={r.get('Id'):r.get('Target') for r in relationships if r.get('TargetMode')!='External'}
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            shared=[''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        sheets={}
        for sheet in workbook.find(q('sheets')):
            target=targets.get(sheet.get('{'+REL+'}id'),'')
            if target.startswith('/'):target=target.lstrip('/')
            else:target='xl/'+target
            if '..' in target.split('/') or target not in z.namelist():raise ValueError('Invalid workbook relationship.')
            if sheet.get('name') not in ('Requests','Items','Archive'):continue
            rows=[];root=ET.fromstring(z.read(target))
            for row in root.findall('.//'+q('sheetData')+'/'+q('row')):
                values={};formulas=set()
                for c in row.findall(q('c')):
                    ref=c.get('r','');match=re.fullmatch(r'([A-Z]+)([1-9][0-9]*)',ref)
                    if not match:raise ValueError('Invalid cell reference.')
                    col=0
                    for char in match[1]:col=col*26+ord(char)-64
                    if col>100:raise ValueError('Too many columns.')
                    if c.find(q('f')) is not None:formulas.add(col)
                    typ=c.get('t');v=c.find(q('v'))
                    if typ=='inlineStr':value=''.join(c.find(q('is')).itertext()) if c.find(q('is')) is not None else ''
                    elif typ=='s':value=shared[int(v.text)] if v is not None else ''
                    else:value=v.text if v is not None else ''
                    values[col]=value or ''
                rows.append((values,formulas))
                if len(rows)>100000:raise ValueError('Workbook contains too many rows.')
            sheets[sheet.get('name')]=rows
        if 'Requests' not in sheets or not sheets['Requests']:raise ValueError('The Requests sheet is missing or empty.')
        header=sheets['Requests'][0][0]
        if [header.get(i,'') for i in range(1,17)]!=HEADERS[:16]:raise ValueError('Requests columns were renamed or reordered. Use a dashboard-exported workbook.')
        preserved={}
        if sheets.get('Archive'):
            chunks={}
            for values,formulas in sheets['Archive'][1:]:
                if formulas:raise ValueError('Archive formulas are not supported.')
                if not values.get(1):continue
                ident=values[1]
                try:part=int(values.get(2,'0'))
                except ValueError:raise ValueError('Invalid Archive data.')
                group=chunks.setdefault(ident,{})
                if part in group:raise ValueError('Duplicate Archive chunk.')
                group[part]=values.get(3,'')
            for ident,parts in chunks.items():
                if sorted(parts)!=list(range(len(parts))):raise ValueError('Archive data is incomplete.')
                try:record=json.loads(''.join(parts[i] for i in sorted(parts)))
                except ValueError:raise ValueError('Archive data is invalid.')
                if not isinstance(record,dict) or str(record.get('id',''))!=ident:raise ValueError('Archive IDs do not match.')
                preserved[ident]=record
        item_map={};number_map={}
        if sheets.get('Items'):
            h=sheets['Items'][0][0]
            if [h.get(i,'') for i in range(1,9)]!=ITEM_HEADERS:raise ValueError('Items columns were renamed or reordered.')
            for values,formulas in sheets['Items'][1:]:
                if formulas:raise ValueError('Formulas in editable Items cells are not supported. Paste values first.')
                if not any(values.values()):continue
                ident=values.get(1,'')
                if not ident:raise ValueError('An Items row is missing Request ID.')
                try:num=int(float(values.get(2,'0')))
                except ValueError:raise ValueError('Item No must be a positive integer.')
                if num<1 or (ident,num) in number_map:raise ValueError('Each request needs unique positive Item No values.')
                number_map[(ident,num)]=True
                item_map.setdefault(ident,[]).append((num,[values.get(i,'') for i in range(3,9)]))
        records=[];seen=set()
        def date_text(value):
            if re.fullmatch(r'\d{1,5}(?:\.\d+)?',value or ''):
                try:return (date(1899,12,30)+timedelta(days=int(float(value)))).isoformat()
                except (OverflowError,ValueError):pass
            return value
        for values,formulas in sheets['Requests'][1:]:
            if not any(values.values()):continue
            if any(c<=16 for c in formulas):raise ValueError('Formulas in editable Requests cells are not supported. Paste values first.')
            ident=values.get(1,'');company=values.get(2,'')
            if not ident or not company or ident in seen:raise ValueError('Requests need unique IDs and a Company ID.')
            seen.add(ident);status=values.get(8,'') or 'draft';priority=values.get(9,'') or 'normal'
            if status not in STATUSES:raise ValueError('Unknown status for '+ident+': '+status)
            if priority not in PRIORITIES:raise ValueError('Unknown priority for '+ident+': '+priority)
            record=copy.deepcopy(preserved.get(ident,{}));record.update(id=ident,company=company)
            form=record.setdefault('form',{});tracking=record.setdefault('tracking',{})
            for key,col in [('number',4),('date',5),('recipient',6),('title',7)]:
                incoming=date_text(values.get(col,'')) if key=='date' else values.get(col,'')
                # Preserve the original Word date representation on an unchanged Excel round trip.
                if key=='date' and excel_date(incoming)==excel_date(form.get(key,'')):incoming=form.get(key,'')
                if incoming or key in form:form[key]=incoming
            for key,col in [('owner',10),('supplier',11),('dueDate',12),('notes',13)]:
                incoming=date_text(values.get(col,'')) if key=='dueDate' else values.get(col,'')
                if incoming or key in tracking:tracking[key]=incoming
            tracking.update(status=status,priority=priority)
            record['savedAt']=values.get(14,'') or record.get('savedAt') or now()
            record['updatedAt']=values.get(15,'') or record.get('updatedAt') or ''
            if 'Items' in sheets:
                incoming_rows=[r for _,r in sorted(item_map.get(ident,[]))] or [['']*6]
                original_rows=form.get('rows',[])
                def normalized_rows(rows):
                    return [[*r[:3],quantity_value(r[3]),*r[4:]] for r in rows if any(str(v or '').strip() for v in r)]
                # Blank layout rows and Arabic quantities belong to the Word form, not Excel formatting.
                if normalized_rows(incoming_rows)!=normalized_rows(original_rows):form['rows']=incoming_rows
                elif 'rows' not in form:form['rows']=incoming_rows
            elif 'rows' not in form:form['rows']=[['']*6]
            records.append(record)
            if len(records)>20000:raise ValueError('Import supports up to 20,000 requests at a time.')
        if any(ident not in seen for ident in item_map):raise ValueError('An Items row points to a missing request. Check Request ID.')
        if not preserved:warnings.append('No hidden Archive data found. Template-specific Word fields may need completing for new requests.')
        return {'records':records,'warnings':warnings,'count':len(records)}


class LegacyHandler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,code,body,mime):
        self.send_response(code);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass
    def json_reply(self,code,value):self.reply(code,json.dumps(value,ensure_ascii=False).encode(),'application/json; charset=utf-8')
    def authorized(self):
        origin=self.headers.get('Origin')
        allowed={'http://127.0.0.1:'+str(self.server.server_port),'http://localhost:'+str(self.server.server_port)}
        return (origin is None or origin in allowed) and secrets.compare_digest(self.headers.get('X-Workspace-Token',''),TOKEN)
    def do_GET(self):
        if self.path == "/favicon.ico": return self.reply(204, b"", "image/x-icon")
        if urlsplit(self.path).path in ('/','/index.html'):
            html=(ROOT/'index.html').read_text(encoding='utf-8')
            html=html.replace('<meta charset="utf-8">','<meta charset="utf-8"><script>window.WORKSPACE_TOKEN='+json.dumps(TOKEN)+';</script>',1)
            return self.reply(200,html.encode(),'text/html; charset=utf-8')
        if self.path in ('/assets/pro.js','/assets/pro.css'):
            p=ROOT/self.path.lstrip('/')
            if not p.is_file():return self.reply(404,b'Not found','text/plain')
            return self.reply(200,p.read_bytes(),'text/javascript; charset=utf-8' if p.suffix=='.js' else 'text/css; charset=utf-8')
        if self.path.startswith('/api/'):
            if not self.authorized():return self.json_reply(403,{'error':'Workspace token missing or invalid. Reload the dashboard.'})
            try:
                if self.path=='/api/state':return self.json_reply(200,load_state())
                if self.path=='/api/health':return self.json_reply(200,{'app':'shamara-dashboard','version':2,'wordPreview':bool(SOFFICE)})
            except ValueError as error:return self.json_reply(500,{'error':str(error)})
        self.reply(404,b'Not found','text/plain')
    def do_POST(self):
        if not self.authorized():return self.json_reply(403,{'error':'Workspace token missing or invalid. Reload the dashboard.'})
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:return self.json_reply(400,{'error':'Invalid content length.'})
        if not 0<length<=MAX_UPLOAD:return self.json_reply(413,{'error':'Choose a non-empty file smaller than 50 MB.'})
        body=self.rfile.read(length)
        try:
            if self.path=='/api/state':
                data=json.loads(body);result=save_state(data.get('state'),data.get('revision'),data.get('companies'));return self.json_reply(200,{'ok':True,**result})
            if self.path=='/api/excel/export':
                data=export_excel(json.loads(body));return self.reply(200,data,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            if self.path=='/api/excel/import':return self.json_reply(200,import_excel(body))
            if self.path=='/render':
                if not SOFFICE:return self.json_reply(503,{'error':'LibreOffice is unavailable. Tracking and Excel still work. Open the downloaded Word document for printing.'})
                with checked_zip(body) as archive:
                    if 'word/document.xml' not in archive.namelist():raise ValueError('Not a Word document.')
                with LOCK,tempfile.TemporaryDirectory(prefix='word-dashboard-') as folder:
                    folder=Path(folder);doc=folder/'request.docx';doc.write_bytes(body)
                    subprocess.run([SOFFICE,'-env:UserInstallation='+(folder/'profile').as_uri(),'--headless','--convert-to','pdf:writer_pdf_Export','--outdir',str(folder),str(doc)],capture_output=True,timeout=90)
                    pdf=folder/'request.pdf'
                    if not pdf.exists():raise RuntimeError('Word renderer did not produce a PDF. Reopen index.command or download Word.')
                    return self.reply(200,pdf.read_bytes(),'application/pdf')
            return self.json_reply(404,{'error':'Endpoint not found.'})
        except ConflictError as error:self.json_reply(409,{'error':str(error)})
        except (ValueError,KeyError,TypeError,AttributeError,ET.ParseError,IndexError,zipfile.BadZipFile) as error:self.json_reply(400,{'error':str(error) or 'Invalid file or request.'})
        except subprocess.TimeoutExpired:self.json_reply(504,{'error':'Word preview timed out. Try fewer items or download Word.'})
        except Exception:self.json_reply(500,{'error':'The local operation could not be completed. Check available disk space and restart the dashboard.'})


from http.cookies import SimpleCookie
from urllib.parse import urlsplit, parse_qs
from team_store import Store, Denied, Conflict
from mail_service import configuration_status, start_worker, retry_notification
import ssl
TEAM = None

def store():
    global TEAM
    if TEAM is None:
        text=(ROOT/'index.html').read_text();decoder=json.JSONDecoder()
        companies,_=decoder.raw_decode(text.split('const templates=',1)[1])
        TEAM=Store(DATA,{t['id']:t['name'] for t in companies})
    return TEAM

def update_tracking_excel(result):
    if result.pop('changed',False):
        with STATE_LOCK:
            store().backup()
            try:
                with store().connect() as db:records=[json.loads(row[0]) for row in db.execute('SELECT payload FROM records')]
                excel=export_excel({'records':records,'companies':store().companies if store().has_permission(user,'accessPurchases') else {}});target=DATA/'Purchase_Tracking.xlsx'
                fd,name=tempfile.mkstemp(prefix='.excel-',dir=DATA)
                try:
                    with os.fdopen(fd,'wb') as f:f.write(excel)
                    os.replace(name,target)
                finally:
                    if os.path.exists(name):os.unlink(name)
                result['excelSaved']=True
            except Exception:result['excelSaved']=False;result['warning']='السجل محفوظ في قاعدة البيانات. تعذر تحديث Excel.'
    result.setdefault('excelSaved',True)
    return result

class Handler(LegacyHandler):
    def host_ok(self):
        host=urlsplit('//'+self.headers.get('Host','')).hostname
        allowed=getattr(self.server,'allowed_hosts',{'localhost','127.0.0.1'})
        return host in allowed
    def same_origin(self):
        expected=('https' if isinstance(self.connection,ssl.SSLSocket) else 'http')+'://'+self.headers.get('Host','')
        return self.host_ok() and self.headers.get('Origin',expected)==expected and self.headers.get('Sec-Fetch-Site','same-origin') not in ('cross-site',)
    def token(self):
        try:
            c=SimpleCookie();c.load(self.headers.get('Cookie',''));return c['shamara_session'].value if 'shamara_session' in c else ''
        except Exception:return ''
    def identity(self):return store().session(self.token())
    def authorized(self):
        identity=self.identity()
        return bool(identity and self.same_origin() and secrets.compare_digest(self.headers.get('X-Workspace-Token',''),identity[1]))
    def reply(self,code,body,mime):
        self.send_response(code);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','SAMEORIGIN');self.send_header('Referrer-Policy','same-origin')
        if getattr(self,'response_cookie',None):self.send_header('Set-Cookie',self.response_cookie)
        self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass
    def set_cookie(self,token):
        self.response_cookie='shamara_session='+token+'; Path=/; HttpOnly; SameSite=Strict; Max-Age='+('28800' if token else '0')+('; Secure' if isinstance(self.connection,ssl.SSLSocket) else '')
    def do_GET(self):
        if not self.host_ok():return self.json_reply(403,{'error':'Host is not configured for this server.'})
        if self.path=='/favicon.ico':return self.reply(204,b'','image/x-icon')
        page=urlsplit(self.path).path
        if page=='/Dashboard.html':
            query=urlsplit(self.path).query
            self.send_response(302);self.send_header('Location','/index.html'+('?' + query if query else ''));self.send_header('Content-Length','0');self.send_header('Cache-Control','no-store');self.end_headers();return
        identity=self.identity()
        if page in ('/','/index.html','/purchases','/correspondence'):
            status=200
            if not identity:
                html=(ROOT/'assets/auth.html').read_text().replace('__AUTH_CONFIG__',json.dumps({'setup':not store().configured(),'local':self.client_address[0] in ('127.0.0.1','::1')}))
            else:
                user=identity[0]
                purchase_page=page in ('/purchases','/index.html') or bool(parse_qs(urlsplit(self.path).query).get('request'))
                allowed=True
                if purchase_page:allowed=store().has_permission(user,'accessPurchases')
                if page=='/correspondence':allowed=store().has_permission(user,'viewCorrespondence')
                if not allowed:status=403
                html=(ROOT/'index.html' if purchase_page and allowed else ROOT/'assets'/'portal.html').read_text()
                context='<script>window.CURRENT_USER='+json.dumps(user,ensure_ascii=False).replace('<',chr(92)+'u003c')+';window.WORKSPACE_TOKEN='+json.dumps(identity[1])+';window.ACTIVE_MODULE='+json.dumps('home' if not allowed or page!='/correspondence' else 'correspondence')+';</script>'
                html=html.replace('<meta charset="utf-8">','<meta charset="utf-8">'+context,1)
                if purchase_page and allowed:
                    before,closing,after=html.rpartition('</html>')
                    html=before+'<script src="/assets/purchase-assist.js"></script>'+closing+after
            return self.reply(status,html.encode(),'text/html; charset=utf-8')
        if not identity:return self.json_reply(401,{'error':'انتهت جلسة الدخول. سجّل الدخول مجدداً.'})
        if self.path in ('/assets/pro.js','/assets/pro.css','/assets/team.js','/assets/portal.js','/assets/portal.css','/assets/purchase-assist.js'):
            file=ROOT/self.path.lstrip('/');return self.reply(200,file.read_bytes(),'text/css; charset=utf-8' if file.suffix=='.css' else 'text/javascript; charset=utf-8')
        if not self.authorized():return self.json_reply(403,{'error':'أعد تحميل الصفحة للتحقق من الجلسة.'})
        user=identity[0]
        try:
            api_path=urlsplit(self.path).path
            purchase_routes={'/api/state','/api/workflow/plan','/api/inbox','/api/inbox/preview','/api/directory','/api/notifications','/api/audit'}
            if api_path in purchase_routes and not store().has_permission(user,'accessPurchases'):raise Denied('الدخول إلى طلبات الشراء غير مسموح لحسابك.')
            if self.path=='/api/portal':return self.json_reply(200,store().portal_summary(user))
            if api_path=='/api/correspondence':
                filters={key:values[0] for key,values in parse_qs(urlsplit(self.path).query).items()}
                return self.json_reply(200,store().correspondence_list(user,filters))
            if api_path=='/api/correspondence/next-number':
                direction=parse_qs(urlsplit(self.path).query).get('direction',[''])[0]
                return self.json_reply(200,store().correspondence_next_number(user,direction))
            if api_path=='/api/correspondence/history':
                params=parse_qs(urlsplit(self.path).query)
                return self.json_reply(200,store().correspondence_history(user,params.get('id',[''])[0],int(params.get('before',['0'])[0])))
            if api_path=='/api/correspondence/item':
                ident=parse_qs(urlsplit(self.path).query).get('id',[''])[0]
                return self.json_reply(200,store().correspondence_item(user,ident))
            if self.path=='/api/auth/me':return self.json_reply(200,{'user':user,'companies':store().companies})
            if self.path=='/api/state':return self.json_reply(200,store().load(user))
            if self.path=='/api/health':return self.json_reply(200,{'app':'shamara-dashboard','version':22,'wordPreview':bool(SOFFICE),'database':'SQLite','shared':True})
            if self.path=='/api/purchase-reference/status':return self.json_reply(200,store().purchase_reference_status(user))
            if api_path=='/api/purchase-assist':
                params=parse_qs(urlsplit(self.path).query)
                get=lambda key,default='':params.get(key,[default])[0]
                return self.json_reply(200,store().purchase_assistance(user,get('company'),int(get('year','2026')),get('q'),get('sources')=='1'))
            if self.path=='/api/workflow/plan':return self.json_reply(200,{'plan':store().workflow_plan()})
            if self.path=='/api/inbox':return self.json_reply(200,store().inbox(user))
            if urlsplit(self.path).path=='/api/inbox/preview':
                task=parse_qs(urlsplit(self.path).query).get('task',[''])[0]
                return self.json_reply(200,store().preview_task(user,task))
            if self.path=='/api/directory':return self.json_reply(200,{'users':store().directory(user)})
            if urlsplit(self.path).path=='/api/notifications':return self.json_reply(200,store().notifications(user,parse_qs(urlsplit(self.path).query).get('record',[None])[0]))
            if self.path=='/api/mail/status':
                if user['role']!='admin':raise Denied('إعداد البريد متاح لمدير النظام فقط.')
                return self.json_reply(200,configuration_status()|{'counts':store().notifications(user)['counts']})
            if self.path=='/api/departments':return self.json_reply(200,{'departments':store().departments(user)})
            if self.path=='/api/permission-catalog':return self.json_reply(200,store().permission_catalog())
            if self.path=='/api/users':return self.json_reply(200,{'users':store().users(user)})
            if urlsplit(self.path).path=='/api/audit':return self.json_reply(200,{'events':store().audit_log(user,parse_qs(urlsplit(self.path).query).get('record',[None])[0])})
            return self.json_reply(404,{'error':'Not found'})
        except Denied as e:return self.json_reply(403,{'error':str(e)})
        except ValueError as e:return self.json_reply(400,{'error':str(e)})
    def do_POST(self):
        if not self.same_origin():return self.json_reply(403,{'error':'طلب من مصدر غير مسموح.'})
        if self.path=='/render':
            identity=self.identity()
            if not identity:return self.json_reply(401,{'error':'سجّل الدخول لمعاينة المستند.'})
            if not self.authorized():return self.json_reply(403,{'error':'جلسة غير صالحة. حدّث الصفحة.'})
            if not store().has_permission(identity[0],'accessPurchases') or not store().has_permission(identity[0],'previewRequest'):return self.json_reply(403,{'error':'لا تملك صلاحية معاينة المستند.'})
            return super().do_POST()
        public=self.path in ('/api/auth/login','/api/auth/setup')
        if not public and not self.authorized():return self.json_reply(401 if not self.identity() else 403,{'error':'جلسة غير صالحة أو صلاحية غير متاحة. سجّل الدخول مجدداً.'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=MAX_UPLOAD:raise ValueError('حجم الطلب غير صالح.')
            raw=self.rfile.read(length)
            if self.path in ('/api/excel/import','/api/purchase-reference/import'):data=None
            else:data=json.loads(raw)
            if self.path=='/api/auth/setup':
                if self.client_address[0] not in ('127.0.0.1','::1'):raise Denied('إنشاء أول مدير يجب أن يتم من الجهاز المركزي نفسه.')
                store().setup(data);return self.json_reply(200,{'ok':True})
            if self.path=='/api/auth/login':
                token,csrf,user=store().login(data.get('username',''),data.get('password',''),self.client_address[0]);self.set_cookie(token);return self.json_reply(200,{'user':user})
            user=self.identity()[0]
            if (self.path.startswith('/api/workflow/') or self.path.startswith('/api/excel/') or self.path=='/api/state' or self.path.startswith('/api/inbox/')) and not store().has_permission(user,'accessPurchases'):raise Denied('الدخول إلى طلبات الشراء غير مسموح لحسابك.')
            if self.path=='/api/purchase-reference/import':
                if user['role']!='admin':raise Denied('تحديث مرجع Excel متاح لمدير النظام فقط.')
                from purchase_learning import read_reference
                templates,_=json.JSONDecoder().raw_decode((ROOT/'index.html').read_text().split('const templates=',1)[1])
                parsed=read_reference(raw,templates)
                result=store().import_purchase_reference(user,parsed)
                return self.json_reply(200,result)
            if self.path=='/api/correspondence':
                result=store().save_correspondence(user,data);return self.json_reply(200,result)
            if self.path=='/api/correspondence/delete':
                result=store().delete_correspondence(user,data.get('id'),data.get('version'));return self.json_reply(200,result)
            if self.path=='/api/correspondence/export':
                rows=store().correspondence_list(user,data,export=True)
                return self.reply(200,export_correspondence(rows,data.get('direction','all')),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            if self.path=='/api/auth/logout':store().logout(self.token());self.set_cookie('');return self.json_reply(200,{'ok':True})
            if self.path=='/api/auth/password':store().change_password(user,data.get('current',''),data.get('password',''));self.set_cookie('');return self.json_reply(200,{'ok':True})
            if self.path=='/api/departments/delete':result=store().delete_department(user,data.get('id'),data.get('version'),data.get('replacementId',''));store().backup();return self.json_reply(200,result)
            if self.path=='/api/departments':result=store().manage_department(user,data);store().backup();return self.json_reply(200,{'department':result})
            if self.path=='/api/users':result=store().manage_user(user,data);store().backup();return self.json_reply(200,{'user':result})
            if self.path=='/api/mail/retry':return self.json_reply(200,retry_notification(store(),user,data.get('id')))
            if self.path=='/api/inbox/read':return self.json_reply(200,store().read_inbox(user,data.get('id'),data.get('all') is True))
            if self.path=='/api/inbox/preview':return self.json_reply(200,store().request_preview(user,data.get('recordId'),data.get('revision'),data.get('recipientId'),data.get('message','')))
            if self.path=='/api/inbox/preview/complete':return self.json_reply(200,store().complete_preview(user,data.get('id'),data.get('revision')))
            if self.path=='/api/workflow/plan':
                result=store().update_workflow_plan(user,data);store().backup();return self.json_reply(200,result)
            if self.path=='/api/workflow/admin':
                result=store().admin_update(user,data.get('id'),data.get('revision'),data.get('status'),data.get('assigneeId',''),data.get('trackingPatch',{}),data.get('reason',''))
                return self.json_reply(200,update_tracking_excel(result))
            if self.path=='/api/workflow/action':
                result=store().action(user,data.get('id'),data.get('revision'),data.get('action'),data.get('trackingPatch',{}))
                return self.json_reply(200,update_tracking_excel(result))
            if self.path=='/api/state':
                result=store().save(user,data.get('state'),data.get('view'))
                return self.json_reply(200,update_tracking_excel(result))
            if self.path=='/api/excel/export':
                if not store().has_permission(user,'exportExcel'):raise Denied('لا تملك صلاحية تصدير Excel.')
                allowed={record['id']:record for rows in store().load(user)['state']['archives'].values() for record in rows}
                requested=[r.get('id') for r in data.get('records',[])]
                if any(ident not in allowed for ident in requested):raise Denied('التصدير متاح للطلبات التي تملك صلاحية عرضها فقط.')
                return self.reply(200,export_excel({'records':[allowed[i] for i in requested],'companies':store().companies}),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            if self.path=='/api/excel/import':
                if not store().has_permission(user,'importExcel'):raise Denied('لا تملك صلاحية استيراد Excel.')
                result=import_excel(raw)
                with store().connect() as db:
                    for record in result['records']:
                        store().validate(record)
                        if not store().scope(user,record['company']):raise Denied('الملف يحتوي شركات خارج صلاحياتك.')
                        row=db.execute('SELECT payload FROM records WHERE id=?',(record['id'],)).fetchone();old=json.loads(row[0]) if row else None
                        if old is None or digest_record(old)!=digest_record(record):store().permitted(user,old,record)
                return self.json_reply(200,result)
            return self.json_reply(404,{'error':'Not found'})
        except Denied as e:self.json_reply(403,{'error':str(e)})
        except Conflict as e:self.json_reply(409,{'error':str(e)})
        except (ValueError,KeyError,TypeError,AttributeError,IndexError,ET.ParseError,zipfile.BadZipFile) as e:self.json_reply(400,{'error':str(e)})
        except Exception:self.json_reply(500,{'error':'تعذر إكمال العملية. لم يتم تجاوز الصلاحيات. افحص الخادم.'})

from team_store import digest as digest_record

def main():
    store()
    host=os.environ.get('SHAMARA_HOST','127.0.0.1');port=int(os.environ.get('SHAMARA_PORT','8765'))
    cert=os.environ.get('SHAMARA_TLS_CERT');key=os.environ.get('SHAMARA_TLS_KEY')
    if host not in ('127.0.0.1','localhost') and not (cert and key):raise SystemExit('LAN access requires HTTPS: set SHAMARA_TLS_CERT and SHAMARA_TLS_KEY.')
    try:server=ThreadingHTTPServer((host,port),Handler)
    except OSError:raise SystemExit('Port is already in use. Close the previous Dashboard Terminal and start again.')
    server.allowed_hosts={'localhost','127.0.0.1',*filter(None,os.environ.get('SHAMARA_ALLOWED_HOSTS','').split(','))}
    if cert and key:
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2;context.load_cert_chain(cert,key);server.socket=context.wrap_socket(server.socket,server_side=True)
    url=('https' if cert else 'http')+'://localhost:'+str(port)+'/'
    print('Shamara Team Dashboard: '+url+'\nCentral database: '+str(DATA/'team.sqlite3')+'\nKeep this server running for all employees.',flush=True)
    if os.environ.get('SHAMARA_NO_BROWSER')!='1':webbrowser.open(url)
    mail_worker=start_worker(store())
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        mail_worker.stop()
        server.server_close()
if __name__=='__main__':main()
